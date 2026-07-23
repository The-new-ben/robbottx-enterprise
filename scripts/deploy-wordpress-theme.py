#!/usr/bin/env python3
"""Deploy a reviewed WordPress theme through a one-use Code Snippets route."""

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
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile


USER_AGENT = "RobbottX-Agent-Theme-Deploy/0.1"
LEGACY_ROUTE_PATH = "/wp-json/agenttheme/v1/run"
MAX_ARCHIVE_FILES = 10_000
MAX_PUBLIC_ZIP_BYTES = 256 * 1024 * 1024
MAX_TEXT_ARCHIVE_MEMBER_BYTES = 16 * 1024 * 1024
MAX_TEXT_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_UNCOMPRESSED_ARCHIVE_BYTES = 1024 * 1024 * 1024
TEXT_ARCHIVE_SUFFIXES = {
    ".css",
    ".html",
    ".json",
    ".md",
    ".php",
    ".svg",
    ".txt",
}
FORBIDDEN_ARCHIVE_NAMES = {
    ".env",
    "credentials",
    "credentials.json",
    "id_dsa",
    "id_ed25519",
    "id_rsa",
    "secrets",
    "secrets.json",
}
FORBIDDEN_ARCHIVE_SUFFIXES = {
    ".key",
    ".log",
    ".map",
    ".p12",
    ".pem",
    ".pfx",
    ".sql",
    ".sqlite",
}


class DeployFailure(RuntimeError):
    """A redacted release or deployment failure."""


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    """Do not forward release credentials or accept redirected artifacts."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


NO_REDIRECT_OPENER = urllib.request.build_opener(RejectRedirects())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify and optionally deploy a reviewed WordPress theme package."
        )
    )
    parser.add_argument("--version", required=True)
    parser.add_argument("--zip-url", required=True)
    parser.add_argument("--zip-sha256", required=True)
    parser.add_argument("--zip-size", required=True, type=int)
    parser.add_argument("--package-marker", required=True)
    parser.add_argument("--theme-slug", default="robbottx")
    parser.add_argument("--render-path", default="/")
    parser.add_argument("--new-body-marker", required=True)
    parser.add_argument("--old-body-marker", required=True)
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def required_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise DeployFailure(
            f"Required environment variable {name} is absent."
        )
    return value


def validate_inputs(args: argparse.Namespace) -> None:
    if not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z._+-]{0,63}", args.version):
        raise DeployFailure("--version contains unsupported characters.")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", args.theme_slug):
        raise DeployFailure("--theme-slug must be a lowercase WordPress slug.")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", args.zip_sha256):
        raise DeployFailure(
            "--zip-sha256 must be a 64-character hexadecimal value."
        )
    if (
        args.zip_size <= 0
        or args.zip_size > MAX_PUBLIC_ZIP_BYTES
    ):
        raise DeployFailure("--zip-size is outside the allowed release range.")
    markers = {
        "--package-marker": args.package_marker,
        "--new-body-marker": args.new_body_marker,
        "--old-body-marker": args.old_body_marker,
    }
    for label, marker in markers.items():
        if (
            len(marker) < 8
            or marker != marker.strip()
            or any(ord(character) < 32 for character in marker)
        ):
            raise DeployFailure(
                f"{label} must be a trimmed, release-specific marker."
            )
    if args.new_body_marker == args.old_body_marker:
        raise DeployFailure("Rendered-body markers must be different.")
    validate_site_path(args.render_path, "--render-path")
    validate_https_url(args.zip_url, "--zip-url", require_zip=True)
    expected_zip_url = (
        "https://raw.githubusercontent.com/The-new-ben/"
        "robbottx-enterprise/main/plugin-dist/"
        f"robbottx-{args.version}.zip"
    )
    if args.zip_url != expected_zip_url:
        raise DeployFailure(
            "--zip-url is not the canonical versioned RobbottX theme ZIP."
        )


def validate_site_path(value: str, label: str) -> None:
    parsed = urllib.parse.urlsplit(value)
    if (
        any(ord(character) < 32 for character in value)
        or not value.startswith("/")
        or value.startswith("//")
        or parsed.scheme
        or parsed.netloc
        or parsed.fragment
    ):
        raise DeployFailure(f"{label} must be a site-relative path.")


def validate_https_url(
    value: str,
    label: str,
    *,
    require_zip: bool = False,
) -> str:
    parsed = urllib.parse.urlsplit(value)
    if (
        any(ord(character) < 32 for character in value)
        or parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise DeployFailure(
            f"{label} must be an HTTPS URL without credentials or a fragment."
        )
    if require_zip and not parsed.path.lower().endswith(".zip"):
        raise DeployFailure(f"{label} path must end in .zip.")
    return value


def normalize_base_url(value: str) -> str:
    validate_https_url(value, "WP_BASE_URL")
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.netloc.lower() != "robbottx.com"
        or parsed.path not in {"", "/"}
        or parsed.query
    ):
        raise DeployFailure(
            "WP_BASE_URL must be exactly the RobbottX HTTPS origin."
        )
    return "https://robbottx.com"


def make_auth(user: str, password: str) -> str:
    encoded = base64.b64encode(
        f"{user}:{password}".encode("utf-8")
    ).decode("ascii")
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
            return (
                response.status,
                response.headers.get("Content-Type", ""),
                body,
            )
    except urllib.error.HTTPError as error:
        response_bytes = error.read(MAX_TEXT_RESPONSE_BYTES + 1)
        if len(response_bytes) > MAX_TEXT_RESPONSE_BYTES:
            raise DeployFailure(
                "A WordPress error response exceeded the safe size limit."
            )
        body = response_bytes.decode("utf-8", errors="replace")
        return (
            error.code,
            error.headers.get("Content-Type", ""),
            body,
        )
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise DeployFailure("A WordPress transport request failed.") from error


def request_bytes(
    url: str,
    *,
    max_bytes: int,
    timeout: int = 90,
) -> tuple[int, str, bytes]:
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
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise DeployFailure(
                    "The public artifact exceeded the declared byte size."
                )
            return (
                response.status,
                response.headers.get("Content-Type", ""),
                body,
            )
    except urllib.error.HTTPError as error:
        return (
            error.code,
            error.headers.get("Content-Type", ""),
            error.read(64 * 1024),
        )
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise DeployFailure("The public artifact download failed.") from error


def is_json_content_type(content_type: str) -> bool:
    media_type = content_type.split(";", 1)[0].strip().lower()
    return media_type == "application/json" or media_type.endswith("+json")


def decode_json(
    content_type: str,
    body: str,
    context: str,
) -> object:
    if not is_json_content_type(content_type):
        raise DeployFailure(f"{context} did not return WordPress JSON.")
    try:
        return json.loads(body)
    except json.JSONDecodeError as error:
        raise DeployFailure(f"{context} returned invalid JSON.") from error


def json_object(
    status: int,
    content_type: str,
    body: str,
    context: str,
) -> dict:
    if status < 200 or status >= 300:
        raise DeployFailure(f"{context} failed with HTTP {status}.")
    parsed = decode_json(content_type, body, context)
    if not isinstance(parsed, dict):
        raise DeployFailure(f"{context} returned an unexpected JSON shape.")
    return parsed


def add_cache_buster(url: str) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}rbtxcb={int(time.time())}"


def verify_theme_zip(
    archive_bytes: bytes,
    *,
    expected_size: int,
    expected_sha256: str,
    slug: str,
    version: str,
    package_marker: str,
) -> dict[str, int | str]:
    actual_size = len(archive_bytes)
    actual_sha256 = hashlib.sha256(archive_bytes).hexdigest()
    if actual_size != expected_size:
        raise DeployFailure("Public ZIP byte size does not match the release.")
    if actual_sha256 != expected_sha256.lower():
        raise DeployFailure("Public ZIP SHA-256 does not match the release.")

    try:
        with ZipFile(io.BytesIO(archive_bytes), "r") as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if not names:
                raise DeployFailure("Public ZIP is empty.")
            if len(infos) > MAX_ARCHIVE_FILES:
                raise DeployFailure("Public ZIP contains too many members.")
            if len(names) != len(set(names)):
                raise DeployFailure("Public ZIP contains duplicate paths.")
            if any("\\" in name for name in names):
                raise DeployFailure(
                    "Public ZIP contains Windows path separators."
                )

            for info in infos:
                path = PurePosixPath(info.filename)
                parts = path.parts
                if (
                    path.is_absolute()
                    or not parts
                    or parts[0] != slug
                    or ".." in parts
                ):
                    raise DeployFailure("Public ZIP contains an unexpected root.")
                unix_mode = (info.external_attr >> 16) & 0o170000
                if unix_mode == 0o120000:
                    raise DeployFailure("Public ZIP contains a symbolic link.")
                if (
                    path.suffix.lower() in TEXT_ARCHIVE_SUFFIXES
                    and info.file_size > MAX_TEXT_ARCHIVE_MEMBER_BYTES
                ):
                    raise DeployFailure(
                        "Public ZIP contains an oversized text member."
                    )

                lower_name = path.name.lower()
                lower_parts = {part.lower() for part in parts}
                if (
                    lower_name in FORBIDDEN_ARCHIVE_NAMES
                    or lower_parts.intersection(
                        {"node_modules", ".git", ".svn"}
                    )
                    or path.suffix.lower() in FORBIDDEN_ARCHIVE_SUFFIXES
                ):
                    raise DeployFailure(
                        "Public ZIP contains a forbidden release path."
                    )

            if (
                sum(info.file_size for info in infos)
                > MAX_UNCOMPRESSED_ARCHIVE_BYTES
            ):
                raise DeployFailure(
                    "Public ZIP expands beyond the safe release limit."
                )

            failed_member = archive.testzip()
            if failed_member is not None:
                raise DeployFailure("Public ZIP integrity check failed.")

            style_path = f"{slug}/style.css"
            if style_path not in names:
                raise DeployFailure("Public ZIP is missing theme style.css.")
            try:
                style_text = archive.read(style_path).decode("utf-8")
            except UnicodeDecodeError as error:
                raise DeployFailure(
                    "Public ZIP theme style.css is not UTF-8."
                ) from error
            if not re.search(
                rf"^\s*Version:\s*{re.escape(version)}\s*$",
                style_text,
                re.MULTILINE,
            ):
                raise DeployFailure(
                    "Public ZIP theme header version is wrong."
                )
            if re.search(
                r"^\s*Template:\s*\S+\s*$",
                style_text,
                re.IGNORECASE | re.MULTILINE,
            ):
                raise DeployFailure(
                    "Child-theme packages are not allowed for this deployment."
                )

            marker_found = False
            for info in infos:
                path = PurePosixPath(info.filename)
                if info.is_dir() or path.suffix.lower() not in TEXT_ARCHIVE_SUFFIXES:
                    continue
                try:
                    text = archive.read(info).decode("utf-8")
                except UnicodeDecodeError:
                    continue
                if package_marker in text:
                    marker_found = True
                    break
            if not marker_found:
                raise DeployFailure("Public ZIP release marker is absent.")
    except BadZipFile as error:
        raise DeployFailure("Public artifact is not a valid ZIP.") from error

    return {
        "zip_bytes": actual_size,
        "zip_sha256": actual_sha256,
        "zip_files": len(names),
    }


def wordpress_error_is(
    status: int,
    content_type: str,
    body: str,
    *,
    expected_code: str | None,
    reject_code: str | None = None,
) -> bool:
    if status != 404 or not is_json_content_type(content_type):
        return False
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return False
    if not isinstance(parsed, dict):
        return False
    code = parsed.get("code")
    data = parsed.get("data")
    if not isinstance(code, str) or not code:
        return False
    if expected_code is not None and code != expected_code:
        return False
    if reject_code is not None and code == reject_code:
        return False
    return isinstance(data, dict) and data.get("status") == 404


def code_snippets_record_is_absent(
    status: int,
    content_type: str,
    body: str,
) -> bool:
    if status not in {404, 500} or not is_json_content_type(content_type):
        return False
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return False
    if not isinstance(parsed, dict):
        return False
    return (
        parsed.get("code") == "rest_cannot_get"
        and parsed.get("message") == "The snippet could not be found."
        and isinstance(parsed.get("data"), dict)
        and parsed["data"].get("status") == status
    )


def prove_deploy_route_absent(
    base_url: str,
    auth: str,
    route_path: str,
    *,
    attempts: int = 3,
    method: str = "POST",
) -> tuple[bool, list[str]]:
    if method not in {"OPTIONS", "POST"}:
        raise ValueError("Route absence proof method is not allowed.")
    failures: list[str] = []
    for attempt in range(1, attempts + 1):
        try:
            status, content_type, body = request(
                f"{base_url}{route_path}",
                method=method,
                auth=auth,
                payload={} if method == "POST" else None,
                timeout=30,
            )
            if wordpress_error_is(
                status,
                content_type,
                body,
                expected_code="rest_no_route",
            ):
                return True, failures
            failures.append(
                f"route absence attempt {attempt} lacked WordPress rest_no_route"
            )
        except Exception as error:
            failures.append(
                f"route absence attempt {attempt} raised "
                f"{type(error).__name__}"
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


def prove_route_not_registered(
    base_url: str,
    route_path: str,
) -> tuple[bool, list[str]]:
    try:
        status, content_type, body = request(
            add_cache_buster(f"{base_url}/wp-json/"),
            timeout=30,
        )
        index = json_object(
            status,
            content_type,
            body,
            "WordPress REST route inventory",
        )
        routes = index.get("routes")
        if not isinstance(routes, dict):
            return False, [
                "WordPress REST route inventory has an unexpected shape"
            ]
        inventory_path = route_path.removeprefix("/wp-json")
        if inventory_path in routes:
            return False, ["the route remains registered in REST inventory"]
        return True, []
    except Exception as error:
        return False, [
            f"REST inventory verification raised {type(error).__name__}"
        ]


def require_route_not_registered(
    base_url: str,
    route_path: str,
    context: str,
) -> None:
    absent, failures = prove_route_not_registered(base_url, route_path)
    if absent:
        return
    summary = "; ".join(failures)
    raise DeployFailure(f"{context}: {summary}.")


def prove_legacy_route_absent(
    base_url: str,
) -> tuple[bool, list[str]]:
    # The production edge closes OPTIONS before WordPress receives it.
    # Exact absence from the REST index is the authoritative read-only proof
    # for the fixed legacy route. Never call the legacy callback itself.
    return prove_route_not_registered(
        base_url,
        LEGACY_ROUTE_PATH,
    )


def require_legacy_route_absent(
    base_url: str,
    context: str,
) -> None:
    absent, failures = prove_legacy_route_absent(base_url)
    if absent:
        return
    summary = "; ".join(failures)
    message = f"{context}: legacy theme route absence was not proven."
    if summary:
        message = f"{message} {summary}."
    raise DeployFailure(message)


def find_snippet_ids_by_name(
    base_url: str,
    snippet_name: str,
    auth: str,
    *,
    max_pages: int = 20,
) -> tuple[list[int], list[str]]:
    matches: list[int] = []
    failures: list[str] = []

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
            records = decode_json(
                content_type,
                body,
                f"snippet lookup page {page}",
            )
        except DeployFailure:
            failures.append(
                f"snippet lookup page {page} did not return valid JSON"
            )
            break
        if not isinstance(records, list):
            failures.append(
                f"snippet lookup page {page} returned an unexpected shape"
            )
            break

        for record in records:
            if not isinstance(record, dict) or record.get("name") != snippet_name:
                continue
            record_id = record.get("id")
            if not isinstance(record_id, int) or record_id <= 0:
                failures.append(
                    "an exact-name snippet had no usable numeric ID"
                )
                continue
            matches.append(record_id)

        if len(records) < 100:
            break
        if page == max_pages:
            failures.append("snippet lookup reached its pagination limit")

    return sorted(set(matches)), failures


def require_snippet_name_absent(
    base_url: str,
    snippet_name: str,
    auth: str,
) -> None:
    matches, failures = find_snippet_ids_by_name(
        base_url,
        snippet_name,
        auth,
    )
    if failures:
        raise DeployFailure(
            "Pre-create exact-name snippet lookup was not proven."
        )
    if matches:
        raise DeployFailure(
            "The one-use snippet name already exists before creation."
        )


def prove_snippet_record_absent(
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
                    f"{snippet_id}"
                ),
                auth=auth,
                timeout=30,
            )
            if code_snippets_record_is_absent(
                status,
                content_type,
                body,
            ):
                return True, failures
            failures.append(
                f"snippet record proof attempt {attempt} was not a "
                "WordPress JSON record-level 404"
            )
        except Exception as error:
            failures.append(
                f"snippet record proof attempt {attempt} raised "
                f"{type(error).__name__}"
            )
        if attempt < attempts:
            time.sleep(attempt)
    return False, failures


def delete_and_prove_snippet(
    base_url: str,
    snippet_id: int,
    auth: str,
    *,
    attempts: int = 3,
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    for attempt in range(1, attempts + 1):
        try:
            status, _, _ = request(
                (
                    f"{base_url}/wp-json/code-snippets/v1/snippets/"
                    f"{snippet_id}?_method=DELETE"
                ),
                method="POST",
                auth=auth,
                payload={},
                timeout=30,
            )
            if not (200 <= status < 300 or status == 404):
                failures.append(
                    f"snippet delete attempt {attempt} returned HTTP {status}"
                )
        except Exception as error:
            failures.append(
                f"snippet delete attempt {attempt} raised "
                f"{type(error).__name__}"
            )

        absent, proof_failures = prove_snippet_record_absent(
            base_url,
            snippet_id,
            auth,
            attempts=1,
        )
        failures.extend(proof_failures)
        if absent:
            return True, failures
        if attempt < attempts:
            time.sleep(attempt)
    return False, failures


def verify_snippet_id_matches_name(
    base_url: str,
    snippet_id: int,
    snippet_name: str,
    auth: str,
) -> tuple[bool, bool, list[str]]:
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
        return False, False, [
            "created snippet identity lookup raised "
            f"{type(error).__name__}"
        ]

    if code_snippets_record_is_absent(status, content_type, body):
        return False, True, []
    if status < 200 or status >= 300:
        return False, False, [
            f"created snippet identity lookup returned HTTP {status}"
        ]
    try:
        record = decode_json(
            content_type,
            body,
            "created snippet identity lookup",
        )
    except DeployFailure:
        return False, False, [
            "created snippet identity lookup did not return valid JSON"
        ]
    if not isinstance(record, dict):
        return False, False, [
            "created snippet identity lookup returned an unexpected shape"
        ]
    if (
        record.get("id") == snippet_id
        and record.get("name") == snippet_name
    ):
        return True, False, []
    return False, False, [
        "created snippet ID did not resolve to the exact one-use name"
    ]


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

    identity_ok = True
    if snippet_id is not None:
        matches_name, already_absent, identity_failures = (
            verify_snippet_id_matches_name(
                base_url,
                snippet_id,
                snippet_name,
                auth,
            )
        )
        failures.extend(identity_failures)
        identity_ok = not identity_failures
        if matches_name:
            ids.add(snippet_id)
        elif not already_absent:
            identity_ok = False

    deletion_ok = True
    for discovered_id in sorted(ids):
        deleted, delete_failures = delete_and_prove_snippet(
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
            "the temporary exact-name snippet still exists after deletion"
        )

    return (
        deletion_ok
        and lookup_ok
        and identity_ok
        and not remaining
    ), failures


def verify_theme_rest_record(
    base_url: str,
    auth: str,
    theme_slug: str,
    version: str,
) -> dict:
    quoted_slug = urllib.parse.quote(theme_slug, safe="")
    status, content_type, body = request(
        (
            f"{base_url}/wp-json/wp/v2/themes/{quoted_slug}"
            "?context=edit&_fields=stylesheet,template,status,version,"
            "is_block_theme"
        ),
        auth=auth,
        timeout=60,
    )
    theme = json_object(
        status,
        content_type,
        body,
        "Active theme REST verification",
    )
    if (
        theme.get("stylesheet") != theme_slug
        or theme.get("template") != theme_slug
        or theme.get("status") != "active"
        or theme.get("version") != version
        or theme.get("is_block_theme") is not True
    ):
        raise DeployFailure(
            "WordPress REST did not confirm the requested active block theme."
        )
    return theme


def verify_rendered_body(
    base_url: str,
    render_path: str,
    new_marker: str,
    old_marker: str,
) -> None:
    status, content_type, rendered = request(
        add_cache_buster(f"{base_url}{render_path}"),
        timeout=90,
    )
    if status != 200 or "html" not in content_type.lower():
        raise DeployFailure("Rendered page did not return HTML with HTTP 200.")
    body_open = re.search(r"<body(?:\s[^>]*)?>", rendered, re.IGNORECASE)
    if body_open is None:
        raise DeployFailure("Rendered page has no body element.")
    body_close = re.search(
        r"</body\s*>",
        rendered[body_open.end():],
        re.IGNORECASE,
    )
    if body_close is None:
        raise DeployFailure("Rendered page has no closing body element.")
    rendered_body = rendered[
        body_open.start():body_open.end() + body_close.start()
    ]
    if new_marker not in rendered_body:
        raise DeployFailure("New rendered-body marker is absent.")
    if old_marker in rendered_body:
        raise DeployFailure("Old rendered-body marker is still present.")


def build_route_code(
    *,
    theme_slug: str,
    version: str,
    zip_url: str,
    zip_sha256: str,
    zip_size: int,
    route_token: str,
) -> str:
    template_path = (
        Path(__file__).resolve().parent
        / "templates"
        / "deploy-theme-route.php.txt"
    )
    route_code = template_path.read_text(encoding="utf-8")
    replacements = {
        "{{THEME_SLUG}}": theme_slug,
        "{{THEME_VERSION}}": version,
        "{{RAW_ZIP_URL_B64}}": base64.b64encode(
            zip_url.encode("utf-8")
        ).decode("ascii"),
        "{{ZIP_SHA256}}": zip_sha256.lower(),
        "{{ZIP_SIZE}}": str(zip_size),
        "{{ROUTE_TOKEN}}": route_token,
    }
    for placeholder, value in replacements.items():
        route_code = route_code.replace(placeholder, value)
    if "{{" in route_code or "}}" in route_code:
        raise DeployFailure("Theme route template has unresolved placeholders.")
    return route_code


def parse_created_snippet_id(created: dict) -> int:
    snippet_id = created.get("id")
    if not isinstance(snippet_id, int) or snippet_id <= 0:
        raise DeployFailure(
            "Temporary route creation returned no usable snippet ID."
        )
    return snippet_id


def make_route_token(version: str) -> str:
    safe_version = re.sub(r"[^a-zA-Z0-9-]+", "-", version)
    return (
        f"{safe_version.lower().strip('-')}-"
        f"{int(time.time())}-{secrets.token_hex(16)}"
    )


def emit_evidence(payload: dict) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def main() -> int:
    args = parse_args()
    validate_inputs(args)

    base_url = normalize_base_url(required_env("WP_BASE_URL"))
    user = required_env("WP_USER")
    password = required_env("WP_APP_PASSWORD")
    auth = make_auth(user, password)

    route_token = make_route_token(args.version)
    route_path = f"/wp-json/agenttheme/v1/run-{route_token}"
    snippet_name = f"tmp-robbottx-theme-deploy-{route_token}"

    status, content_type, body = request(
        (
            f"{base_url}/wp-json/wp/v2/users/me"
            "?context=edit&_fields=roles,capabilities"
        ),
        auth=auth,
    )
    identity = json_object(
        status,
        content_type,
        body,
        "Application Password verification",
    )
    capabilities = identity.get("capabilities", {})
    required_capabilities = {
        "install_themes",
        "switch_themes",
        "update_themes",
    }
    if (
        "administrator" not in identity.get("roles", [])
        or not isinstance(capabilities, dict)
        or any(
            capabilities.get(capability) is not True
            for capability in required_capabilities
        )
    ):
        raise DeployFailure(
            "Authenticated WordPress user lacks required theme authority."
        )

    zip_status, zip_content_type, zip_bytes = request_bytes(
        add_cache_buster(args.zip_url),
        max_bytes=args.zip_size,
        timeout=90,
    )
    if zip_status != 200 or "html" in zip_content_type.lower():
        raise DeployFailure(
            f"Raw ZIP preflight failed with HTTP {zip_status}."
        )
    artifact = verify_theme_zip(
        zip_bytes,
        expected_size=args.zip_size,
        expected_sha256=args.zip_sha256,
        slug=args.theme_slug,
        version=args.version,
        package_marker=args.package_marker,
    )

    require_legacy_route_absent(
        base_url,
        "Pre-create verification",
    )
    require_route_not_registered(
        base_url,
        route_path,
        "Pre-create unique-route inventory",
    )
    require_deploy_route_absent(
        base_url,
        auth,
        route_path,
        "Pre-create verification",
    )
    require_snippet_name_absent(
        base_url,
        snippet_name,
        auth,
    )

    base_evidence = {
        "artifact": {
            "files": artifact["zip_files"],
            "sha256": artifact["zip_sha256"],
            "size": artifact["zip_bytes"],
        },
        "authority_verified": True,
        "legacy_route_absent": True,
        "route_absent_before": True,
        "snippet_name_absent_before": True,
        "theme": args.theme_slug,
        "version": args.version,
    }
    if not args.execute:
        emit_evidence(
            {
                **base_evidence,
                "execute": False,
                "status": "preflight_ok",
            }
        )
        return 0

    route_code = build_route_code(
        theme_slug=args.theme_slug,
        version=args.version,
        zip_url=args.zip_url,
        zip_sha256=args.zip_sha256,
        zip_size=args.zip_size,
        route_token=route_token,
    )

    snippet_id: int | None = None
    snippet_absent_after = False
    route_absent_after = False
    legacy_route_absent_after = False
    failure: Exception | None = None

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
        created = json_object(
            status,
            content_type,
            body,
            "Temporary route creation",
        )
        snippet_id = parse_created_snippet_id(created)

        callback_confirmed = False
        try:
            status, content_type, body = request(
                f"{base_url}{route_path}",
                method="POST",
                auth=auth,
                payload={},
                timeout=300,
            )
            callback_body = json_object(
                status,
                content_type,
                body,
                "Theme_Upgrader deployment",
            )
            callback_confirmed = (
                callback_body.get("result") is True
                and callback_body.get("active") is True
                and callback_body.get("stylesheet") == args.theme_slug
                and callback_body.get("template") == args.theme_slug
                and callback_body.get("version") == args.version
                and callback_body.get("artifact_verified") is True
            )
        except Exception:
            callback_confirmed = False

        independent_failures: list[str] = []
        try:
            verify_theme_rest_record(
                base_url,
                auth,
                args.theme_slug,
                args.version,
            )
        except Exception as exception:
            independent_failures.append(
                "active theme REST verification failed with "
                f"{type(exception).__name__}"
            )
        try:
            verify_rendered_body(
                base_url,
                args.render_path,
                args.new_body_marker,
                args.old_body_marker,
            )
        except Exception as exception:
            independent_failures.append(
                "rendered-body verification failed with "
                f"{type(exception).__name__}"
            )

        if independent_failures:
            raise DeployFailure(
                "Theme deployment verification failed: "
                + "; ".join(independent_failures)
                + "."
            )
    except Exception as exception:
        failure = exception
    finally:
        cleanup_failures: list[str] = []
        try:
            snippet_absent_after, snippet_failures = (
                cleanup_temporary_snippets(
                    base_url,
                    auth,
                    snippet_name,
                    snippet_id,
                )
            )
            cleanup_failures.extend(snippet_failures)
        except Exception as error:
            snippet_absent_after = False
            cleanup_failures.append(
                "snippet cleanup raised "
                f"{type(error).__name__}"
            )

        try:
            strict_route_absent, route_failures = (
                prove_deploy_route_absent(
                    base_url,
                    auth,
                    route_path,
                )
            )
            cleanup_failures.extend(route_failures)
        except Exception as error:
            strict_route_absent = False
            cleanup_failures.append(
                "unique-route cleanup proof raised "
                f"{type(error).__name__}"
            )

        try:
            route_unregistered, inventory_failures = (
                prove_route_not_registered(base_url, route_path)
            )
            cleanup_failures.extend(inventory_failures)
        except Exception as error:
            route_unregistered = False
            cleanup_failures.append(
                "unique-route inventory proof raised "
                f"{type(error).__name__}"
            )
        route_absent_after = strict_route_absent and route_unregistered

        try:
            legacy_route_absent_after, legacy_failures = (
                prove_legacy_route_absent(base_url)
            )
            cleanup_failures.extend(legacy_failures)
        except Exception as error:
            legacy_route_absent_after = False
            cleanup_failures.append(
                "legacy-route cleanup proof raised "
                f"{type(error).__name__}"
            )

        cleanup_proven = (
            snippet_absent_after
            and route_absent_after
            and legacy_route_absent_after
        )
        if not cleanup_proven:
            cleanup_error = (
                "Temporary theme deploy route cleanup was not proven."
            )
            if cleanup_failures:
                cleanup_error = (
                    f"{cleanup_error} {'; '.join(cleanup_failures)}."
                )
            if failure is None:
                failure = DeployFailure(cleanup_error)
            else:
                if isinstance(failure, DeployFailure):
                    failure_summary = str(failure)
                else:
                    failure_summary = (
                        "Theme deployment failed with "
                        f"{type(failure).__name__}."
                    )
                failure = DeployFailure(
                    f"{failure_summary} {cleanup_error}"
                )

    if failure is not None:
        if isinstance(failure, DeployFailure):
            raise failure
        raise DeployFailure(
            f"Theme deployment failed with {type(failure).__name__}."
        ) from failure

    emit_evidence(
        {
            **base_evidence,
            "callback_confirmed": callback_confirmed,
            "execute": True,
            "legacy_route_absent_after": legacy_route_absent_after,
            "rendered_body_verified": True,
            "route_absent_after": route_absent_after,
            "snippet_record_absent_after": snippet_absent_after,
            "status": "deployed",
            "theme_rest_verified": True,
        }
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except DeployFailure as error:
        print(f"Theme deployment failed: {error}", file=sys.stderr)
        sys.exit(1)
