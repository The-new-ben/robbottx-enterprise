#!/usr/bin/env python3
"""Deploy a reviewed plugin through a temporary Code Snippets REST route."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zipfile import BadZipFile, ZipFile


USER_AGENT = "RobbottX-Agent-Deploy/0.1"
EXPECTED_SITE_HOST = "robbottx.com"
EXPECTED_RAW_HOST = "raw.githubusercontent.com"
EXPECTED_RAW_ROOT = (
    "https://raw.githubusercontent.com/"
    "The-new-ben/robbottx-enterprise/main/plugin-dist"
)
REQUIRED_MANIFEST_FIELDS = {
    "name",
    "slug",
    "version",
    "author",
    "homepage",
    "requires",
    "tested",
    "requires_php",
    "download_url",
    "download_sha256",
    "download_size",
    "inventory_url",
    "record_hash",
    "last_updated",
    "sections",
}
MAX_ARCHIVE_FILES = 10_000
MAX_PUBLIC_ZIP_BYTES = 256 * 1024 * 1024
MAX_TEXT_ARCHIVE_MEMBER_BYTES = 16 * 1024 * 1024
MAX_TEXT_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_UNCOMPRESSED_ARCHIVE_BYTES = 1024 * 1024 * 1024


class DeployFailure(RuntimeError):
    pass


def redact_deployment_failure(error: Exception) -> DeployFailure:
    if isinstance(error, DeployFailure):
        return error
    return DeployFailure(
        f"Plugin deployment failed with {type(error).__name__}."
    )


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request_object,
        file_pointer,
        code,
        message,
        headers,
        new_url,
    ):
        return None


NO_REDIRECT_OPENER = urllib.request.build_opener(NoRedirectHandler())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--zip-url", required=True)
    parser.add_argument(
        "--manifest-url",
        default=f"{EXPECTED_RAW_ROOT}/robbottx-core.json",
    )
    parser.add_argument("--inventory-url", default="")
    parser.add_argument("--zip-sha256", required=True)
    parser.add_argument("--zip-size", required=True, type=int)
    parser.add_argument("--record-hash", required=True)
    parser.add_argument("--package-marker", required=True)
    parser.add_argument("--plugin-slug", default="robbottx-core")
    parser.add_argument("--plugin-main-file", default="robbottx-core.php")
    parser.add_argument("--version-constant", default="ROBBOTTX_CORE_VERSION")
    parser.add_argument(
        "--health-path",
        default="/wp-json/robbottx/v1/healthcheck",
    )
    parser.add_argument("--render-path", default="/")
    parser.add_argument(
        "--new-body-marker",
        default="",
    )
    parser.add_argument("--old-body-marker", required=True)
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def required_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise DeployFailure(f"Required environment variable {name} is absent.")
    return value


def validate_release_inputs(
    args: argparse.Namespace,
    base_url: str,
) -> tuple[str, str]:
    if re.fullmatch(r"\d+\.\d+\.\d+", args.version) is None:
        raise DeployFailure("--version must be a three-part numeric release.")
    if re.fullmatch(r"[a-z0-9-]+", args.plugin_slug) is None:
        raise DeployFailure("--plugin-slug contains unsafe characters.")
    if re.fullmatch(r"[A-Za-z0-9-]+\.php", args.plugin_main_file) is None:
        raise DeployFailure("--plugin-main-file contains unsafe characters.")
    if re.fullmatch(r"[A-Z][A-Z0-9_]+", args.version_constant) is None:
        raise DeployFailure("--version-constant contains unsafe characters.")
    if re.fullmatch(r"[0-9a-fA-F]{64}", args.zip_sha256) is None:
        raise DeployFailure("--zip-sha256 must be a 64-character hexadecimal value.")
    if re.fullmatch(r"[0-9a-fA-F]{64}", args.record_hash) is None:
        raise DeployFailure("--record-hash must be a 64-character hexadecimal value.")
    if args.zip_size <= 0 or args.zip_size > MAX_PUBLIC_ZIP_BYTES:
        raise DeployFailure("--zip-size is outside the allowed release range.")

    site = urllib.parse.urlsplit(base_url)
    if (
        site.scheme != "https"
        or site.hostname != EXPECTED_SITE_HOST
        or site.netloc != EXPECTED_SITE_HOST
        or site.path not in ("", "/")
        or site.query
        or site.fragment
        or site.username
        or site.password
    ):
        raise DeployFailure("WP_BASE_URL must be the canonical HTTPS site origin.")

    expected_zip_url = (
        f"{EXPECTED_RAW_ROOT}/{args.plugin_slug}-{args.version}.zip"
    )
    expected_manifest_url = (
        f"{EXPECTED_RAW_ROOT}/{args.plugin_slug}.json"
    )
    expected_inventory_url = (
        f"{EXPECTED_RAW_ROOT}/{args.plugin_slug}-{args.version}.inventory.json"
    )
    inventory_url = args.inventory_url or expected_inventory_url
    if args.zip_url != expected_zip_url:
        raise DeployFailure("--zip-url does not match the reviewed release path.")
    if args.manifest_url != expected_manifest_url:
        raise DeployFailure("--manifest-url does not match the reviewed release path.")
    if inventory_url != expected_inventory_url:
        raise DeployFailure("--inventory-url does not match the reviewed release path.")

    for label, path_value in (
        ("--health-path", args.health_path),
        ("--render-path", args.render_path),
    ):
        parsed_path = urllib.parse.urlsplit(path_value)
        if (
            not path_value.startswith("/")
            or parsed_path.scheme
            or parsed_path.netloc
            or "\\" in path_value
            or any(ord(character) < 32 for character in path_value)
        ):
            raise DeployFailure(f"{label} is not a safe site-relative path.")

    for label, marker in (
        ("--package-marker", args.package_marker),
        ("--new-body-marker", args.new_body_marker),
        ("--old-body-marker", args.old_body_marker),
    ):
        if len(marker) > 300 or "\r" in marker or "\n" in marker:
            raise DeployFailure(f"{label} contains unsafe marker text.")
    if not args.package_marker:
        raise DeployFailure("--package-marker must not be empty.")
    if not args.old_body_marker:
        raise DeployFailure("--old-body-marker must not be empty.")

    return expected_inventory_url, expected_manifest_url


def make_auth(user: str, password: str) -> str:
    encoded = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {encoded}"


def request(
    url: str,
    *,
    method: str = "GET",
    auth: str | None = None,
    payload: dict | None = None,
    timeout: int = 60,
) -> tuple[int, str, str]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "Accept": "application/json, text/html;q=0.8",
        "User-Agent": USER_AGENT,
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    if auth:
        headers["Authorization"] = auth

    request_object = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with NO_REDIRECT_OPENER.open(
            request_object,
            timeout=timeout,
        ) as response:
            response_bytes = response.read(MAX_TEXT_RESPONSE_BYTES + 1)
            if len(response_bytes) > MAX_TEXT_RESPONSE_BYTES:
                raise DeployFailure(
                    "A WordPress response exceeded the safe size limit."
                )
            body = response_bytes.decode("utf-8", errors="replace")
            return response.status, response.headers.get("Content-Type", ""), body
    except urllib.error.HTTPError as error:
        response_bytes = error.read(MAX_TEXT_RESPONSE_BYTES + 1)
        if len(response_bytes) > MAX_TEXT_RESPONSE_BYTES:
            raise DeployFailure(
                "A WordPress error response exceeded the safe size limit."
            )
        body = response_bytes.decode("utf-8", errors="replace")
        return error.code, error.headers.get("Content-Type", ""), body
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        host = urllib.parse.urlsplit(url).netloc
        raise DeployFailure(
            f"Transport failure while requesting {host}."
        ) from error


def request_bytes(
    url: str,
    *,
    max_bytes: int,
    timeout: int = 90,
) -> tuple[int, str, bytes, str]:
    request_object = urllib.request.Request(
        url,
        headers={
            "Accept": "application/zip, application/octet-stream",
            "User-Agent": USER_AGENT,
        },
        method="GET",
    )

    try:
        with NO_REDIRECT_OPENER.open(
            request_object,
            timeout=timeout,
        ) as response:
            return (
                response.status,
                response.headers.get("Content-Type", ""),
                response.read(max_bytes + 1),
                response.geturl(),
            )
    except urllib.error.HTTPError as error:
        return (
            error.code,
            error.headers.get("Content-Type", ""),
            error.read(64 * 1024),
            error.geturl(),
        )
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        host = urllib.parse.urlsplit(url).netloc
        raise DeployFailure(
            f"Transport failure while downloading artifact from {host}."
        ) from error


def json_body(status: int, content_type: str, body: str, context: str) -> dict:
    if status < 200 or status >= 300:
        kind = "managed-host HTML/WAF response" if "html" in content_type else "JSON/API response"
        raise DeployFailure(f"{context} failed with HTTP {status} ({kind}).")
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as error:
        raise DeployFailure(f"{context} returned invalid JSON.") from error
    if not isinstance(parsed, dict):
        raise DeployFailure(f"{context} returned an unexpected JSON shape.")
    return parsed


def add_cache_buster(url: str) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}rbtxcb={int(time.time())}"


def verify_public_download_location(
    requested_url: str,
    final_url: str,
) -> None:
    requested = urllib.parse.urlsplit(requested_url)
    final = urllib.parse.urlsplit(final_url)
    if (
        requested.scheme != "https"
        or requested.hostname != EXPECTED_RAW_HOST
        or final.scheme != "https"
        or final.hostname != EXPECTED_RAW_HOST
        or final.path != requested.path
    ):
        raise DeployFailure("Public artifact download changed origin or path.")


def load_public_json(url: str, context: str) -> dict:
    status, content_type, body = request(
        add_cache_buster(url),
        timeout=60,
    )
    return json_body(status, content_type, body, context)


def wordpress_json_error_code(
    status: int,
    content_type: str,
    body: str,
) -> str | None:
    if "json" not in content_type.lower():
        return None
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    code = parsed.get("code")
    data = parsed.get("data")
    if (
        not isinstance(code, str)
        or not isinstance(data, dict)
        or data.get("status") != status
    ):
        return None
    return code


def code_snippets_record_is_missing(
    status: int,
    content_type: str,
    body: str,
) -> bool:
    if status != 500 or "json" not in content_type.lower():
        return False
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return False
    return (
        isinstance(parsed, dict)
        and parsed.get("code") == "rest_cannot_get"
        and parsed.get("message") == "The snippet could not be found."
        and isinstance(parsed.get("data"), dict)
        and parsed["data"].get("status") == 500
    )


def verify_manifest(
    manifest: dict,
    *,
    version: str,
    slug: str,
    zip_url: str,
    zip_sha256: str,
    zip_size: int,
    inventory_url: str,
    record_hash: str,
) -> dict[str, str | int]:
    missing = sorted(REQUIRED_MANIFEST_FIELDS - set(manifest))
    if missing:
        raise DeployFailure(
            "Public update manifest is missing required fields."
        )
    if (
        manifest.get("slug") != slug
        or manifest.get("version") != version
        or manifest.get("download_url") != zip_url
        or manifest.get("download_sha256") != zip_sha256.lower()
        or manifest.get("download_size") != zip_size
        or manifest.get("inventory_url") != inventory_url
        or manifest.get("record_hash") != record_hash.lower()
        or manifest.get("homepage") != "https://robbottx.com/"
        or not isinstance(manifest.get("sections"), dict)
        or not isinstance(manifest["sections"].get("changelog"), str)
        or not manifest["sections"]["changelog"].strip()
    ):
        raise DeployFailure(
            "Public update manifest does not match the reviewed release."
        )
    return {
        "manifest_version": version,
        "manifest_download_sha256": zip_sha256.lower(),
        "manifest_download_size": zip_size,
    }


def verify_inventory(
    inventory: dict,
    *,
    version: str,
    slug: str,
    zip_sha256: str,
    zip_size: int,
    packaged_files: list[dict[str, int | str]],
) -> dict[str, int | str]:
    expected_artifact = f"{slug}-{version}.zip"
    if (
        inventory.get("artifact") != expected_artifact
        or inventory.get("version") != version
        or inventory.get("zip_sha256") != zip_sha256.lower()
        or inventory.get("zip_bytes") != zip_size
        or inventory.get("files") != packaged_files
    ):
        raise DeployFailure(
            "Public artifact inventory does not match the reviewed ZIP."
        )
    return {
        "inventory_files": len(packaged_files),
        "inventory_zip_sha256": zip_sha256.lower(),
    }


def verify_rendered_body(
    rendered: str,
    *,
    new_marker: str,
    old_marker: str,
) -> str:
    rendered_lower = rendered.lower()
    body_start = rendered_lower.find("<body")
    if body_start < 0:
        raise DeployFailure("Rendered page has no body element.")
    body_end = rendered_lower.find("</body>", body_start)
    if body_end < 0:
        raise DeployFailure("Rendered page has no closing body element.")
    rendered_body = rendered[body_start:body_end]
    if new_marker not in rendered_body:
        raise DeployFailure("New rendered-body marker is absent.")
    if old_marker and old_marker in rendered_body:
        raise DeployFailure("Old rendered-body marker is still present.")
    return hashlib.sha256(rendered_body.encode("utf-8")).hexdigest()


def verify_plugin_zip(
    archive_bytes: bytes,
    *,
    expected_size: int,
    expected_sha256: str,
    slug: str,
    main_file: str,
    version: str,
    version_constant: str,
    package_marker: str,
    expected_record_hash: str,
) -> dict[str, object]:
    actual_size = len(archive_bytes)
    actual_sha256 = hashlib.sha256(archive_bytes).hexdigest()
    if actual_size != expected_size:
        raise DeployFailure("Public ZIP byte size does not match the release.")
    if actual_sha256 != expected_sha256.lower():
        raise DeployFailure("Public ZIP SHA-256 does not match the release.")

    try:
        with ZipFile(io.BytesIO(archive_bytes), "r") as archive:
            infos = archive.infolist()
            names = [member.filename for member in infos]
            if not names:
                raise DeployFailure("Public ZIP is empty.")
            if len(infos) > MAX_ARCHIVE_FILES:
                raise DeployFailure("Public ZIP contains too many members.")
            if len(names) != len(set(names)):
                raise DeployFailure("Public ZIP contains duplicate paths.")
            if any("\\" in name for name in names):
                raise DeployFailure("Public ZIP contains Windows path separators.")
            for member in infos:
                name = member.filename
                parts = name.split("/")
                unix_mode = (member.external_attr >> 16) & 0o170000
                if (
                    name.endswith("/")
                    or name.startswith("/")
                    or any(part in ("", ".", "..") for part in parts)
                    or parts[0] != slug
                    or ":" in parts[0]
                    or unix_mode == 0o120000
                ):
                    raise DeployFailure(
                        "Public ZIP contains an unsafe or unexpected path."
                    )
                if (
                    member.file_size > MAX_TEXT_ARCHIVE_MEMBER_BYTES
                    and name.lower().endswith(
                        (".css", ".html", ".json", ".md", ".php", ".txt")
                    )
                ):
                    raise DeployFailure(
                        "Public ZIP contains an oversized text member."
                    )
                lower_name = parts[-1].lower()
                if (
                    lower_name
                    in {
                        ".env",
                        "credentials",
                        "credentials.json",
                        "id_dsa",
                        "id_ed25519",
                        "id_rsa",
                        "secrets",
                        "secrets.json",
                    }
                    or lower_name.endswith(
                        (".key", ".p12", ".pem", ".pfx", ".sql", ".sqlite")
                    )
                ):
                    raise DeployFailure(
                        "Public ZIP contains a forbidden release path."
                    )
            if (
                sum(member.file_size for member in infos)
                > MAX_UNCOMPRESSED_ARCHIVE_BYTES
            ):
                raise DeployFailure(
                    "Public ZIP expands beyond the safe release limit."
                )
            if archive.testzip() is not None:
                raise DeployFailure("Public ZIP integrity check failed.")

            packaged_main_path = f"{slug}/{main_file}"
            if packaged_main_path not in names:
                raise DeployFailure("Public ZIP is missing the plugin main file.")
            packaged_main = archive.read(packaged_main_path).decode("utf-8")
            if not re.search(
                rf"^\s*\*\s*Version:\s*{re.escape(version)}\s*$",
                packaged_main,
                re.MULTILINE,
            ):
                raise DeployFailure("Public ZIP plugin header version is wrong.")
            constant_pattern = re.compile(
                rf"define\s*\(\s*['\"]{re.escape(version_constant)}['\"]"
                rf"\s*,\s*['\"]{re.escape(version)}['\"]\s*\)"
            )
            if not constant_pattern.search(packaged_main):
                raise DeployFailure("Public ZIP plugin version constant is wrong.")

            marker_found = False
            record_hash_found = False
            for name in names:
                if not name.lower().endswith(
                    (".php", ".json", ".js", ".css", ".txt", ".md")
                ):
                    continue
                try:
                    text = archive.read(name).decode("utf-8")
                except UnicodeDecodeError:
                    continue
                if package_marker in text:
                    marker_found = True
                if expected_record_hash.lower() in text.lower():
                    record_hash_found = True
            if not marker_found:
                raise DeployFailure("Public ZIP release marker is absent.")
            if not record_hash_found:
                raise DeployFailure(
                    "Public ZIP does not contain the expected record hash."
                )

            packaged_files = [
                {
                    "path": name,
                    "bytes": len(archive.read(name)),
                    "sha256": hashlib.sha256(archive.read(name)).hexdigest(),
                }
                for name in names
            ]
    except BadZipFile as error:
        raise DeployFailure("Public artifact is not a valid ZIP.") from error

    return {
        "zip_bytes": actual_size,
        "zip_sha256": actual_sha256,
        "zip_files": len(names),
        "files": packaged_files,
    }


def prove_snippet_record_absent(
    base_url: str,
    snippet_id: int,
    auth: str,
) -> tuple[bool, str]:
    status, content_type, body = request(
        (
            f"{base_url}/wp-json/code-snippets/v1/snippets/"
            f"{snippet_id}"
        ),
        auth=auth,
        timeout=30,
    )
    if code_snippets_record_is_missing(status, content_type, body):
        return True, ""
    if status == 404:
        return False, "snippet record returned an untrusted 404 response"
    return False, f"snippet record still returned HTTP {status}"


def delete_temporary_snippet(
    base_url: str,
    snippet_id: int,
    auth: str,
    *,
    attempts: int = 3,
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    for attempt in range(1, attempts + 1):
        try:
            status, content_type, body = request(
                (
                    f"{base_url}/wp-json/code-snippets/v1/snippets/"
                    f"{snippet_id}?_method=DELETE"
                ),
                method="POST",
                auth=auth,
                payload={},
                timeout=30,
            )
            already_absent = code_snippets_record_is_missing(
                status,
                content_type,
                body,
            )
            if 200 <= status < 300 or already_absent:
                absent, proof_failure = prove_snippet_record_absent(
                    base_url,
                    snippet_id,
                    auth,
                )
                if absent:
                    return True, failures
                failures.append(
                    f"delete attempt {attempt}: {proof_failure}"
                )
            else:
                failures.append(
                    f"delete attempt {attempt} returned HTTP {status}"
                )
        except Exception as error:  # cleanup must continue to the absence proof
            failures.append(
                f"delete attempt {attempt} raised {type(error).__name__}"
            )
        if attempt < attempts:
            time.sleep(attempt)
    return False, failures


def find_snippet_ids_by_name(
    base_url: str,
    snippet_name: str,
    auth: str,
    *,
    max_pages: int = 20,
) -> tuple[list[int], list[str]]:
    matches: list[int] = []
    failures: list[str] = []
    exhaustive = False

    for page in range(1, max_pages + 1):
        try:
            status, content_type, body = request(
                (
                    f"{base_url}/wp-json/code-snippets/v1/snippets"
                    f"?per_page=100&page={page}"
                ),
                auth=auth,
                timeout=30,
            )
        except Exception as error:
            failures.append(
                f"snippet lookup page {page} raised "
                f"{type(error).__name__}"
            )
            break
        if status < 200 or status >= 300:
            failures.append(
                f"snippet lookup page {page} returned HTTP {status}"
            )
            break
        try:
            records = json.loads(body)
        except json.JSONDecodeError:
            failures.append(f"snippet lookup page {page} returned invalid JSON")
            break
        if not isinstance(records, list):
            kind = (
                "managed-host HTML/WAF response"
                if "html" in content_type
                else "unexpected API response"
            )
            failures.append(f"snippet lookup page {page} returned {kind}")
            break

        for record in records:
            if not isinstance(record, dict):
                continue
            if record.get("name") != snippet_name:
                continue
            if not isinstance(record.get("id"), int):
                failures.append(
                    "exact-name snippet record has an unusable ID"
                )
                continue
            matches.append(record["id"])

        if len(records) < 100:
            exhaustive = True
            break

    if not exhaustive and not failures:
        failures.append(
            "snippet lookup did not prove exhaustive pagination"
        )

    return sorted(set(matches)), failures


def snippet_record_has_exact_name(
    base_url: str,
    snippet_id: int,
    snippet_name: str,
    auth: str,
) -> tuple[bool, list[str]]:
    try:
        status, content_type, body = request(
            (
                f"{base_url}/wp-json/code-snippets/v1/snippets/"
                f"{snippet_id}"
            ),
            auth=auth,
            timeout=30,
        )
    except Exception as error:
        return False, [
            "snippet ownership lookup raised "
            f"{type(error).__name__}"
        ]
    if status < 200 or status >= 300:
        return False, []
    try:
        record = json.loads(body)
    except json.JSONDecodeError:
        return False, ["snippet ownership lookup returned invalid JSON"]
    if "json" not in content_type.lower() or not isinstance(record, dict):
        return False, ["snippet ownership lookup returned an unexpected response"]
    if (
        record.get("id") == snippet_id
        and record.get("name") == snippet_name
    ):
        return True, []
    return False, []


def cleanup_temporary_snippets(
    base_url: str,
    auth: str,
    snippet_name: str,
    snippet_id: int | None,
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    ids: set[int] = set()

    discovered, lookup_failures = find_snippet_ids_by_name(
        base_url,
        snippet_name,
        auth,
    )
    ids.update(discovered)
    failures.extend(lookup_failures)

    if snippet_id is not None and snippet_id not in ids:
        owned, ownership_failures = snippet_record_has_exact_name(
            base_url,
            snippet_id,
            snippet_name,
            auth,
        )
        failures.extend(ownership_failures)
        if owned:
            ids.add(snippet_id)

    deletion_ok = True
    for discovered_id in sorted(ids):
        deleted, delete_failures = delete_temporary_snippet(
            base_url,
            discovered_id,
            auth,
        )
        deletion_ok = deletion_ok and deleted
        failures.extend(delete_failures)

    remaining, proof_failures = find_snippet_ids_by_name(
        base_url,
        snippet_name,
        auth,
    )
    failures.extend(proof_failures)
    lookup_ok = not lookup_failures and not proof_failures

    if remaining:
        failures.append(
            "temporary snippet name still resolves after deletion"
        )

    return deletion_ok and lookup_ok and not remaining, failures


def prove_deploy_route_absent(
    base_url: str,
    auth: str,
    route_path: str,
    *,
    attempts: int = 3,
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    for attempt in range(1, attempts + 1):
        try:
            status, content_type, body = request(
                f"{base_url}{route_path}",
                method="POST",
                auth=auth,
                payload={},
                timeout=30,
            )
            if (
                status == 404
                and wordpress_json_error_code(
                    status,
                    content_type,
                    body,
                )
                == "rest_no_route"
            ):
                return True, failures
            failures.append(
                f"absence attempt {attempt} returned untrusted HTTP {status}"
            )
        except Exception as error:  # retry independently of deletion outcome
            failures.append(
                f"absence attempt {attempt} raised {type(error).__name__}"
            )
        if attempt < attempts:
            time.sleep(attempt)
    return False, failures


def require_deploy_route_absent(
    base_url: str,
    auth: str,
    route_path: str,
    context: str,
) -> None:
    route_absent, failures = prove_deploy_route_absent(
        base_url,
        auth,
        route_path,
    )
    if route_absent:
        return

    summary = "; ".join(failures)
    message = f"{context}: temporary deploy route is not absent."
    if summary:
        message = f"{message} {summary}."
    raise DeployFailure(message)


def require_route_not_registered(
    base_url: str,
    route_path: str,
) -> None:
    status, content_type, body = request(
        add_cache_buster(f"{base_url}/wp-json/"),
        timeout=30,
    )
    index = json_body(
        status,
        content_type,
        body,
        "WordPress REST route inventory",
    )
    routes = index.get("routes")
    if not isinstance(routes, dict):
        raise DeployFailure(
            "WordPress REST route inventory has an unexpected shape."
        )
    if route_path.removeprefix("/wp-json") in routes:
        raise DeployFailure(
            "A stale deploy route is registered before release creation."
        )


def parse_created_snippet_id(created: dict) -> int:
    snippet_id = created.get("id")
    if type(snippet_id) is not int or snippet_id <= 0:
        raise DeployFailure(
            "Temporary route creation returned no usable snippet ID."
        )
    return snippet_id


def main() -> int:
    args = parse_args()
    base_url = required_env("WP_BASE_URL").rstrip("/")
    inventory_url, manifest_url = validate_release_inputs(args, base_url)
    user = required_env("WP_USER")
    password = required_env("WP_APP_PASSWORD")
    auth = make_auth(user, password)
    safe_version = re.sub(r"[^a-zA-Z0-9-]+", "-", args.version)
    route_token = (
        f"{safe_version.lower().strip('-')}-"
        f"{int(time.time())}-{secrets.token_hex(8)}"
    )
    route_path = f"/wp-json/agentdeploy/v1/run-{route_token}"
    legacy_route_path = "/wp-json/agentdeploy/v1/run"
    snippet_name = f"tmp-robbottx-deploy-{route_token}"
    new_body_marker = (
        args.new_body_marker
        if args.new_body_marker
        else f"<!-- robbottx-core:{args.version} -->"
    )
    if new_body_marker == args.old_body_marker:
        raise DeployFailure(
            "New and old rendered-body markers must be different."
        )

    status, content_type, body = request(
        f"{base_url}/wp-json/wp/v2/users/me?context=edit&_fields=id,roles,capabilities",
        auth=auth,
    )
    identity = json_body(status, content_type, body, "Application Password verification")
    if (
        "administrator" not in identity.get("roles", [])
        or identity.get("capabilities", {}).get("update_plugins") is not True
    ):
        raise DeployFailure(
            "Authenticated WordPress user lacks administrator/update_plugins authority."
        )

    manifest = load_public_json(
        manifest_url,
        "Public update manifest",
    )
    manifest_receipt = verify_manifest(
        manifest,
        version=args.version,
        slug=args.plugin_slug,
        zip_url=args.zip_url,
        zip_sha256=args.zip_sha256,
        zip_size=args.zip_size,
        inventory_url=inventory_url,
        record_hash=args.record_hash,
    )

    zip_request_url = add_cache_buster(args.zip_url)
    zip_status, zip_content_type, zip_bytes, zip_final_url = request_bytes(
        zip_request_url,
        max_bytes=args.zip_size,
        timeout=90,
    )
    if zip_status != 200 or "html" in zip_content_type:
        raise DeployFailure(
            f"Raw ZIP preflight failed with HTTP {zip_status}."
        )
    verify_public_download_location(zip_request_url, zip_final_url)
    artifact = verify_plugin_zip(
        zip_bytes,
        expected_size=args.zip_size,
        expected_sha256=args.zip_sha256,
        slug=args.plugin_slug,
        main_file=args.plugin_main_file,
        version=args.version,
        version_constant=args.version_constant,
        package_marker=args.package_marker,
        expected_record_hash=args.record_hash,
    )
    packaged_files = artifact.get("files")
    if not isinstance(packaged_files, list):
        raise DeployFailure("Public ZIP verification returned no file inventory.")
    inventory = load_public_json(
        inventory_url,
        "Public artifact inventory",
    )
    inventory_receipt = verify_inventory(
        inventory,
        version=args.version,
        slug=args.plugin_slug,
        zip_sha256=args.zip_sha256,
        zip_size=args.zip_size,
        packaged_files=packaged_files,
    )

    require_route_not_registered(base_url, legacy_route_path)
    require_route_not_registered(base_url, route_path)
    require_deploy_route_absent(
        base_url,
        auth,
        route_path,
        "Pre-create verification",
    )
    existing_snippets, precreate_lookup_failures = find_snippet_ids_by_name(
        base_url,
        snippet_name,
        auth,
    )
    if precreate_lookup_failures:
        raise DeployFailure(
            "Pre-create snippet-name lookup was not proven exhaustive."
        )
    if existing_snippets:
        raise DeployFailure(
            "A temporary snippet with the release-unique name already exists."
        )

    if not args.execute:
        print(
            json.dumps(
                {
                    "status": "preflight_ok",
                    "wordpress_user_id": identity.get("id"),
                    "zip_http_status": zip_status,
                    "zip_bytes": artifact["zip_bytes"],
                    "zip_sha256": artifact["zip_sha256"],
                    "zip_files": artifact["zip_files"],
                    "manifest_version": manifest_receipt["manifest_version"],
                    "manifest_verified": True,
                    "inventory_files": inventory_receipt["inventory_files"],
                    "inventory_verified": True,
                    "route_absent": True,
                    "snippet_name_absent": True,
                    "execute": False,
                },
                sort_keys=True,
            )
        )
        return 0

    template_path = (
        Path(__file__).resolve().parent
        / "templates"
        / "deploy-route.php.txt"
    )
    route_code = template_path.read_text(encoding="utf-8")
    encoded_zip_url = base64.b64encode(
        args.zip_url.encode("utf-8")
    ).decode("ascii")
    route_code = (
        route_code.replace("{{PLUGIN_SLUG}}", args.plugin_slug)
        .replace("{{PLUGIN_MAIN_FILE}}", args.plugin_main_file)
        .replace("{{PLUGIN_VERSION}}", args.version)
        .replace("{{RAW_ZIP_URL_B64}}", encoded_zip_url)
        .replace("{{ZIP_SHA256}}", args.zip_sha256.lower())
        .replace("{{ZIP_SIZE}}", str(args.zip_size))
        .replace("{{ROUTE_TOKEN}}", route_token)
    )
    if re.search(r"\{\{[A-Z0-9_]+\}\}", route_code):
        raise DeployFailure("Deploy route template contains unresolved placeholders.")

    snippet_id: int | None = None
    snippet_deleted = False
    route_removed = False
    failure: Exception | None = None
    health: dict = {}
    rendered_body_sha256 = ""
    callback_confirmed = False

    try:
        status, content_type, body = request(
            f"{base_url}/wp-json/code-snippets/v1/snippets",
            method="POST",
            auth=auth,
            payload={
                "name": snippet_name,
                "code": route_code,
                "scope": "global",
                "active": True,
            },
        )
        created = json_body(status, content_type, body, "Temporary route creation")
        snippet_id = parse_created_snippet_id(created)

        try:
            status, content_type, body = request(
                f"{base_url}{route_path}",
                method="POST",
                auth=auth,
                payload={},
                timeout=180,
            )
            deployed = json_body(
                status,
                content_type,
                body,
                "Plugin_Upgrader deployment",
            )
            callback_confirmed = (
                deployed.get("result") is True
                and deployed.get("active") is True
                and deployed.get("version") == args.version
            )
        except Exception:
            callback_confirmed = False

        status, content_type, body = request(
            add_cache_buster(f"{base_url}{args.health_path}"),
            timeout=60,
        )
        health = json_body(status, content_type, body, "Healthcheck verification")
        if (
            health.get("status") != "ok"
            or health.get("version") != args.version
            or health.get("record_hash") != args.record_hash.lower()
        ):
            raise DeployFailure(
                "Healthcheck did not return the requested version and record hash."
            )

        status, _, rendered = request(
            add_cache_buster(f"{base_url}{args.render_path}"),
            timeout=90,
        )
        if status != 200:
            raise DeployFailure(f"Rendered page returned HTTP {status}.")
        rendered_body_sha256 = verify_rendered_body(
            rendered,
            new_marker=new_body_marker,
            old_marker=args.old_body_marker,
        )
    except Exception as exception:  # deletion must still execute
        failure = exception
    finally:
        cleanup_failures: list[str] = []
        try:
            snippet_deleted, delete_failures = cleanup_temporary_snippets(
                base_url,
                auth,
                snippet_name,
                snippet_id,
            )
            cleanup_failures.extend(delete_failures)
        except Exception as error:
            snippet_deleted = False
            cleanup_failures.append(
                "snippet cleanup raised "
                f"{type(error).__name__}"
            )

        route_absent = False
        try:
            route_absent, absence_failures = prove_deploy_route_absent(
                base_url,
                auth,
                route_path,
            )
            cleanup_failures.extend(absence_failures)
        except Exception as error:
            cleanup_failures.append(
                "route absence proof raised "
                f"{type(error).__name__}"
            )
        legacy_route_absent = True
        try:
            require_route_not_registered(base_url, legacy_route_path)
        except Exception as error:
            legacy_route_absent = False
            cleanup_failures.append(
                f"legacy route inventory check raised {type(error).__name__}"
            )
        route_removed = (
            snippet_deleted
            and route_absent
            and legacy_route_absent
        )

        if not route_removed:
            cleanup_summary = "; ".join(cleanup_failures)
            cleanup_error = "Temporary deploy route cleanup was not proven."
            if cleanup_summary:
                cleanup_error = f"{cleanup_error} {cleanup_summary}."
            if failure is None:
                failure = DeployFailure(cleanup_error)
            else:
                failure_summary = str(redact_deployment_failure(failure))
                failure = DeployFailure(
                    f"{failure_summary} {cleanup_error}"
                )

    if failure is not None:
        if isinstance(failure, DeployFailure):
            raise failure
        raise redact_deployment_failure(failure) from failure

    print(
        json.dumps(
            {
                "status": "deployed",
                "version": args.version,
                "plugin": args.plugin_slug,
                "zip_bytes": artifact["zip_bytes"],
                "zip_sha256": artifact["zip_sha256"],
                "zip_files": artifact["zip_files"],
                "manifest_verified": True,
                "inventory_verified": True,
                "pre_create_route_absent": True,
                "callback_confirmed": callback_confirmed,
                "independent_health_verified": True,
                "snippet_record_removed": snippet_deleted,
                "health_record_id": health.get("record_id"),
                "health_record_hash": health.get("record_hash"),
                "rendered_body_sha256": rendered_body_sha256,
                "rendered_new_marker_present": True,
                "rendered_old_marker_absent": True,
                "route_removed": route_removed,
            },
            sort_keys=True,
        )
    )
    return 0


def run_cli() -> int:
    try:
        return main()
    except Exception as error:
        failure = redact_deployment_failure(error)
        print(f"Deployment failed: {failure}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(run_cli())
