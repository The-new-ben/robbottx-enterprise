#!/usr/bin/env python3
"""Deploy a reviewed WordPress theme through a one-use Code Snippets route."""

from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import io
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import time
import types
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ElementTree
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile


USER_AGENT = "RobbottX-Agent-Theme-Deploy/0.1"
LEGACY_ROUTE_PATH = "/wp-json/agenttheme/v1/run"
MAX_ARCHIVE_FILES = 10_000
MAX_PUBLIC_ZIP_BYTES = 256 * 1024 * 1024
MAX_TEXT_ARCHIVE_MEMBER_BYTES = 16 * 1024 * 1024
MAX_TEXT_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_UNCOMPRESSED_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_CODE_SNIPPETS_RECORDS = 98
MAX_BOUNDARY_VERIFIER_BYTES = 4 * 1024 * 1024
MAX_THEME_ROUTE_TEMPLATE_BYTES = 1024 * 1024
MAX_TRUSTED_GIT_EXECUTABLE_BYTES = 128 * 1024 * 1024
MAX_TRUSTED_GIT_OUTPUT_BYTES = 128 * 1024 * 1024
TRUSTED_GIT_TIMEOUT_SECONDS = 60
BOUNDARY_VERIFIER_MODULE_NAME = "_robbottx_theme_boundary_verifier"
BOUNDARY_VERIFIER_RELATIVE_PATH = "scripts/deploy-wordpress.py"
THEME_ROUTE_TEMPLATE_RELATIVE_PATH = (
    "scripts/templates/deploy-theme-route.php.txt"
)
THEME_ROUTE_TEMPLATE_SHA256 = (
    "560cebf499e769e1139d0b60cacf5d365"
    "71870a6bbd96b4698cf2c91d845c44e"
)
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
RENDER_EVIDENCE_SCHEMA = {
    "assets_fetched": None,
    "base_mode": None,
    "favicon_mode": None,
    "favicon_path": None,
    "icon_count": None,
    "stylesheet_path": None,
    "version": None,
}
DEPLOY_EVIDENCE_SCHEMA = {
    "after": {
        "active_block_theme": None,
        "active_version": None,
        "configured_site_icon_id": None,
        "new_marker_present": None,
        "old_marker_absent": None,
        "rendered_assets": RENDER_EVIDENCE_SCHEMA,
        "site_icon_identity_unchanged": None,
    },
    "artifact": {
        "files": None,
        "sha256": None,
        "size": None,
    },
    "authority_verified": None,
    "before": {
        "active_block_theme": None,
        "active_version": None,
        "configured_site_icon_id": None,
        "new_marker_absent": None,
        "old_marker_present": None,
        "rendered_assets": RENDER_EVIDENCE_SCHEMA,
    },
    "callback": {
        "artifact_sha256": None,
        "artifact_size": None,
        "artifact_verified": None,
        "confirmed": None,
        "target_version": None,
    },
    "cleanup": {
        "attempted": None,
        "legacy_route_absent": None,
        "proven": None,
        "route_absent": None,
        "snippet_absent": None,
    },
    "execute": None,
    "failure_stage": None,
    "failure_type": None,
    "previous_version": None,
    "recorded_at": None,
    "schema_version": None,
    "status": None,
    "target_version": None,
    "temporary_surface": {
        "legacy_route_absent": None,
        "route_absent": None,
        "snippet_count": None,
        "snippet_limit": None,
        "snippet_name_absent": None,
    },
    "theme": None,
}


class DeployFailure(RuntimeError):
    """A redacted release or deployment failure."""


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    """Do not forward release credentials or accept redirected artifacts."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


NO_REDIRECT_OPENER = urllib.request.build_opener(RejectRedirects())


class ThemeHeadFacts(HTMLParser):
    """Collect link elements that actually occur inside the document head."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[dict[str, str]] = []
        self.base_hrefs: list[str | None] = []
        self.base_outside_head = False
        self._in_head = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        tag = tag.lower()
        if tag == "head":
            self._in_head = True
            return
        if tag == "base":
            attributes = {
                name.lower(): value
                for name, value in attrs
            }
            self.base_hrefs.append(attributes.get("href"))
            if not self._in_head:
                self.base_outside_head = True
        elif tag == "link" and self._in_head:
            self.links.append(
                {
                    name.lower(): value or ""
                    for name, value in attrs
                }
            )

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "head":
            self._in_head = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify and optionally deploy a reviewed WordPress theme package."
        )
    )
    parser.add_argument("--version", required=True)
    parser.add_argument("--previous-version", required=True)
    parser.add_argument("--zip-url", required=True)
    parser.add_argument("--zip-sha256", required=True)
    parser.add_argument("--zip-size", required=True, type=int)
    parser.add_argument(
        "--boundary-receipt",
        required=True,
        type=Path,
    )
    parser.add_argument("--package-marker", required=True)
    parser.add_argument("--theme-slug", default="robbottx")
    parser.add_argument("--render-path", default="/")
    parser.add_argument("--new-body-marker", required=True)
    parser.add_argument("--old-body-marker", required=True)
    parser.add_argument(
        "--expect-fallback-favicon",
        action=argparse.BooleanOptionalAction,
        required=True,
        help=(
            "Require the theme fallback favicon, or use the negative form "
            "when WordPress has a configured site icon."
        ),
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="New durable JSON evidence path. Existing paths are refused.",
    )
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def required_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise DeployFailure(
            f"Required environment variable {name} is absent."
        )
    return value


def _posix_system_owned_path(path: Path) -> bool:
    current = path
    while True:
        try:
            metadata = current.stat()
        except OSError:
            return False
        if metadata.st_uid != 0 or metadata.st_mode & 0o022:
            return False
        if current.parent == current:
            return True
        current = current.parent


def _trusted_windows_git_roots() -> list[Path]:
    roots = [Path("C:/Program Files/Git")]
    try:
        import winreg
    except ImportError:
        return roots
    for access_mode in {
        winreg.KEY_READ,
        winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0),
        winreg.KEY_READ | getattr(winreg, "KEY_WOW64_32KEY", 0),
    }:
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\GitForWindows",
                0,
                access_mode,
            ) as key:
                install_path, value_type = winreg.QueryValueEx(
                    key,
                    "InstallPath",
                )
        except OSError:
            continue
        if (
            value_type in (winreg.REG_SZ, winreg.REG_EXPAND_SZ)
            and isinstance(install_path, str)
            and install_path
        ):
            roots.append(Path(install_path))
    return roots


def resolve_trusted_git_executable() -> Path:
    candidates: list[tuple[Path, Path | None]] = []
    if os.name == "nt":
        for root in _trusted_windows_git_roots():
            candidates.extend(
                (
                    (root / "cmd" / "git.exe", root),
                    (root / "bin" / "git.exe", root),
                )
            )
    else:
        candidates.extend(
            (Path(value), None)
            for value in (
                "/usr/bin/git",
                "/bin/git",
                "/usr/local/bin/git",
            )
        )
    seen: set[Path] = set()
    for candidate, trusted_root in candidates:
        try:
            resolved = candidate.resolve(strict=True)
            metadata = resolved.stat()
        except (OSError, RuntimeError):
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size <= 0
            or metadata.st_size > MAX_TRUSTED_GIT_EXECUTABLE_BYTES
        ):
            continue
        if trusted_root is not None:
            try:
                resolved.relative_to(trusted_root.resolve(strict=True))
            except (OSError, RuntimeError, ValueError):
                continue
        elif not _posix_system_owned_path(resolved):
            continue
        return resolved
    raise DeployFailure(
        "No protected absolute Git executable is available."
    )


def _trusted_git_environment(git_executable: Path) -> dict[str, str]:
    path_entries = [str(git_executable.parent)]
    if os.name == "nt":
        git_root = git_executable.parent.parent
        path_entries.extend(
            str(path)
            for path in (
                git_root / "cmd",
                git_root / "bin",
                git_root / "mingw64" / "bin",
                Path("C:/Windows/System32"),
            )
            if path.is_dir()
        )
    else:
        path_entries.extend(("/usr/bin", "/bin"))
    return {
        "PATH": os.pathsep.join(dict.fromkeys(path_entries)),
        "LANG": "C",
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.fsmonitor",
        "GIT_CONFIG_VALUE_0": "false",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
        "GIT_TERMINAL_PROMPT": "0",
        "PAGER": "cat",
    }


def _run_trusted_git(
    repository_root: Path,
    arguments: list[str],
    *,
    text: bool,
) -> subprocess.CompletedProcess:
    git_executable = resolve_trusted_git_executable()
    completed = subprocess.run(
        [
            str(git_executable),
            "-C",
            str(repository_root),
            *arguments,
        ],
        capture_output=True,
        check=False,
        text=text,
        timeout=TRUSTED_GIT_TIMEOUT_SECONDS,
        env=_trusted_git_environment(git_executable),
    )
    for stream in (completed.stdout, completed.stderr):
        if (
            isinstance(stream, (bytes, str))
            and len(stream) > MAX_TRUSTED_GIT_OUTPUT_BYTES
        ):
            raise DeployFailure(
                "Git output exceeded the boundary bootstrap limit."
            )
    return completed


def _read_head_index_file(
    repository_root: Path,
    relative_path: str,
    *,
    max_bytes: int,
) -> tuple[bytes, str]:
    """Read a stage-zero index blob only when it exactly matches HEAD."""

    try:
        resolved_root = repository_root.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise DeployFailure(
            "Reviewed repository root could not be resolved."
        ) from error
    candidate = PurePosixPath(relative_path)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or "." in candidate.parts
        or ".." in candidate.parts
        or candidate.as_posix() != relative_path
        or max_bytes <= 0
    ):
        raise DeployFailure("Reviewed repository path is invalid.")

    head_result = _run_trusted_git(
        resolved_root,
        ["rev-parse", "HEAD"],
        text=True,
    )
    head = (
        head_result.stdout.strip()
        if head_result.returncode == 0
        and isinstance(head_result.stdout, str)
        else ""
    )
    if re.fullmatch(r"[0-9a-f]{40}", head) is None:
        raise DeployFailure("Reviewed Git HEAD could not be established.")

    index_result = _run_trusted_git(
        resolved_root,
        [
            "ls-files",
            "-z",
            "--cached",
            "--stage",
            "--",
            relative_path,
        ],
        text=False,
    )
    if (
        index_result.returncode != 0
        or not isinstance(index_result.stdout, bytes)
    ):
        raise DeployFailure("Reviewed Git index entry could not be read.")
    entries = [
        entry
        for entry in index_result.stdout.split(b"\x00")
        if entry
    ]
    if len(entries) != 1:
        raise DeployFailure(
            "Reviewed file has no unique stage-zero Git index entry."
        )
    try:
        metadata, raw_path = entries[0].split(b"\t", 1)
        mode, object_id_bytes, stage = metadata.split()
        indexed_path = raw_path.decode(
            "utf-8",
            errors="surrogateescape",
        ).replace("\\", "/")
        object_id = object_id_bytes.decode("ascii")
    except (UnicodeDecodeError, ValueError) as error:
        raise DeployFailure(
            "Reviewed Git index entry is malformed."
        ) from error
    if (
        mode not in {b"100644", b"100755"}
        or stage != b"0"
        or indexed_path != relative_path
        or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", object_id)
        is None
    ):
        raise DeployFailure(
            "Reviewed Git index entry is not an exact ordinary file."
        )

    head_blob_result = _run_trusted_git(
        resolved_root,
        ["rev-parse", f"HEAD:{relative_path}"],
        text=True,
    )
    head_object_id = (
        head_blob_result.stdout.strip()
        if head_blob_result.returncode == 0
        and isinstance(head_blob_result.stdout, str)
        else ""
    )
    if not secrets.compare_digest(object_id, head_object_id):
        raise DeployFailure(
            "Reviewed verifier is staged differently from the current HEAD."
        )

    size_result = _run_trusted_git(
        resolved_root,
        ["cat-file", "-s", object_id],
        text=True,
    )
    try:
        object_size = int(size_result.stdout.strip())
    except (AttributeError, TypeError, ValueError) as error:
        raise DeployFailure(
            "Reviewed Git object size could not be established."
        ) from error
    if (
        size_result.returncode != 0
        or object_size <= 0
        or object_size > max_bytes
    ):
        raise DeployFailure(
            "Reviewed Git object exceeds its execution limit."
        )
    blob_result = _run_trusted_git(
        resolved_root,
        ["cat-file", "blob", object_id],
        text=False,
    )
    if (
        blob_result.returncode != 0
        or not isinstance(blob_result.stdout, bytes)
        or len(blob_result.stdout) != object_size
    ):
        raise DeployFailure(
            "Reviewed Git object bytes could not be read exactly."
        )
    final_head_result = _run_trusted_git(
        resolved_root,
        ["rev-parse", "HEAD"],
        text=True,
    )
    final_head = (
        final_head_result.stdout.strip()
        if final_head_result.returncode == 0
        and isinstance(final_head_result.stdout, str)
        else ""
    )
    if not secrets.compare_digest(head, final_head):
        raise DeployFailure(
            "Reviewed Git HEAD changed during verifier bootstrap."
        )
    return blob_result.stdout, head


def load_reviewed_boundary_verifier() -> object:
    repository_root = Path(__file__).resolve().parents[1]
    verifier_path = repository_root / "scripts" / "deploy-wordpress.py"
    try:
        verifier_payload, git_head = _read_head_index_file(
            repository_root,
            BOUNDARY_VERIFIER_RELATIVE_PATH,
            max_bytes=MAX_BOUNDARY_VERIFIER_BYTES,
        )
    except Exception as error:
        if isinstance(error, DeployFailure):
            raise
        raise DeployFailure(
            "Reviewed public-boundary verifier could not be read."
        ) from error

    previous_module = sys.modules.get(BOUNDARY_VERIFIER_MODULE_NAME)
    had_previous_module = BOUNDARY_VERIFIER_MODULE_NAME in sys.modules
    try:
        verifier = types.ModuleType(BOUNDARY_VERIFIER_MODULE_NAME)
        verifier.__file__ = str(verifier_path)
        verifier.__package__ = None
        sys.modules[BOUNDARY_VERIFIER_MODULE_NAME] = verifier
        exec(
            compile(
                verifier_payload,
                str(verifier_path),
                "exec",
            ),
            verifier.__dict__,
        )
        if (
            not callable(
                getattr(verifier, "read_clean_index_file", None)
            )
            or not callable(
                getattr(verifier, "run_reviewed_boundary_scan", None)
            )
            or not callable(
                getattr(verifier, "validate_boundary_receipt", None)
            )
        ):
            raise AttributeError("boundary verifier entry points unavailable")
        verifier._reviewed_git_head = git_head
        return verifier
    except Exception as error:
        raise DeployFailure(
            "Reviewed public-boundary verifier could not be loaded."
        ) from error
    finally:
        if had_previous_module:
            sys.modules[BOUNDARY_VERIFIER_MODULE_NAME] = previous_module
        else:
            sys.modules.pop(BOUNDARY_VERIFIER_MODULE_NAME, None)


def validate_theme_boundary_receipt(
    args: argparse.Namespace,
) -> dict[str, object]:
    repository_root = Path(__file__).resolve().parents[1]
    verifier = load_reviewed_boundary_verifier()
    try:
        template_payload, template_head = verifier.read_clean_index_file(
            repository_root,
            THEME_ROUTE_TEMPLATE_RELATIVE_PATH,
            max_bytes=MAX_THEME_ROUTE_TEMPLATE_BYTES,
        )
        if (
            not isinstance(template_payload, bytes)
            or getattr(verifier, "_reviewed_git_head", None)
            != template_head
            or hashlib.sha256(template_payload).hexdigest()
            != THEME_ROUTE_TEMPLATE_SHA256
        ):
            raise DeployFailure(
                "Theme route template did not match the reviewed Git HEAD."
            )
        try:
            route_template = template_payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise DeployFailure(
                "Theme route template is not valid UTF-8."
            ) from error

        scan_report = verifier.run_reviewed_boundary_scan(repository_root)
        if getattr(scan_report, "git_head", None) != template_head:
            raise DeployFailure(
                "Current public-boundary scan did not retain the frozen release."
            )
        public_snapshot_sha256 = getattr(
            scan_report,
            "public_snapshot_payload_sha256",
            None,
        )
        if (
            not isinstance(public_snapshot_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", public_snapshot_sha256) is None
        ):
            raise DeployFailure(
                "Current public-boundary scan returned no public snapshot hash."
            )
        result = verifier.validate_boundary_receipt(
            args.boundary_receipt,
            version=args.version,
            slug="robbottx",
            zip_sha256=args.zip_sha256,
            record_hash=public_snapshot_sha256,
            repository_root=repository_root,
            scan_report=scan_report,
        )
    except Exception as error:
        verifier_failure = getattr(verifier, "DeployFailure", ())
        if (
            isinstance(verifier_failure, type)
            and isinstance(error, verifier_failure)
        ):
            raise DeployFailure(str(error)) from error
        if isinstance(error, DeployFailure):
            raise
        raise DeployFailure(
            "Theme public-boundary verification failed with "
            f"{type(error).__name__}."
        ) from error
    if (
        not isinstance(result, dict)
        or set(result)
        != {"artifact_path", "git_head", "receipt_body_sha256"}
        or result.get("artifact_path")
        != f"plugin-dist/robbottx-{args.version}.zip"
        or result.get("git_head") != template_head
        or re.fullmatch(
            r"[0-9a-f]{64}",
            str(result.get("receipt_body_sha256", "")),
        )
        is None
    ):
        raise DeployFailure(
            "Theme public-boundary verifier returned an invalid result."
        )
    return {**result, "route_template": route_template}


def validate_inputs(args: argparse.Namespace) -> None:
    if not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z._+-]{0,63}", args.version):
        raise DeployFailure("--version contains unsupported characters.")
    if not re.fullmatch(
        r"[0-9A-Za-z][0-9A-Za-z._+-]{0,63}",
        args.previous_version,
    ):
        raise DeployFailure(
            "--previous-version contains unsupported characters."
        )
    if args.previous_version == args.version:
        raise DeployFailure(
            "--previous-version must differ from --version."
        )
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
    accept: str = "application/json, text/html;q=0.8",
) -> tuple[int, str, str]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "Accept": accept,
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


def _json_object_without_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate JSON object key")
        document[key] = value
    return document


def confirm_exact_deployment_callback(
    status: int,
    content_type: str,
    body: str,
    *,
    theme_slug: str,
    version: str,
) -> None:
    if (
        status < 200
        or status >= 300
        or not is_json_content_type(content_type)
        or not isinstance(body, str)
        or len(body.encode("utf-8")) > MAX_TEXT_RESPONSE_BYTES
    ):
        raise DeployFailure(
            "Theme deploy callback did not confirm the bound artifact."
        )
    try:
        callback = json.loads(
            body,
            object_pairs_hook=_json_object_without_duplicate_keys,
        )
    except (
        json.JSONDecodeError,
        RecursionError,
        UnicodeError,
        ValueError,
    ) as error:
        raise DeployFailure(
            "Theme deploy callback did not confirm the bound artifact."
        ) from error
    if (
        not isinstance(callback, dict)
        or set(callback)
        != {
            "active",
            "artifact_verified",
            "result",
            "stylesheet",
            "template",
            "version",
        }
        or callback["result"] is not True
        or callback["active"] is not True
        or callback["artifact_verified"] is not True
        or callback["stylesheet"] != theme_slug
        or callback["template"] != theme_slug
        or callback["version"] != version
    ):
        raise DeployFailure(
            "Theme deploy callback did not confirm the bound artifact."
        )


def add_cache_buster(url: str) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}rbtxcb={time.time_ns()}"


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
                add_cache_buster(
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
                add_cache_buster(
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
                add_cache_buster(
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
            add_cache_buster(
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


def read_theme_rest_record(
    base_url: str,
    auth: str,
    theme_slug: str,
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
        or theme.get("is_block_theme") is not True
    ):
        raise DeployFailure(
            "WordPress REST did not confirm the required active block theme."
        )
    return theme


def verify_theme_rest_record(
    base_url: str,
    auth: str,
    theme_slug: str,
    version: str,
) -> dict:
    theme = read_theme_rest_record(base_url, auth, theme_slug)
    if theme.get("version") != version:
        raise DeployFailure(
            "WordPress REST did not confirm the requested theme version."
        )
    return theme


def require_snippet_capacity(
    base_url: str,
    auth: str,
) -> int:
    status, content_type, body = request(
        (
            f"{base_url}/wp-json/code-snippets/v1/snippets"
            "?per_page=100&page=1"
        ),
        auth=auth,
        timeout=60,
    )
    if status < 200 or status >= 300:
        raise DeployFailure(
            "Code Snippets capacity verification failed."
        )
    snippets = decode_json(
        content_type,
        body,
        "Code Snippets capacity verification",
    )
    if not isinstance(snippets, list):
        raise DeployFailure(
            "Code Snippets capacity verification returned an "
            "unexpected JSON shape."
        )
    snippet_count = len(snippets)
    if snippet_count > MAX_CODE_SNIPPETS_RECORDS:
        raise DeployFailure(
            "Code Snippets has insufficient safe temporary capacity."
        )
    return snippet_count


def _same_origin(left: str, right: str) -> bool:
    left_parts = urllib.parse.urlsplit(left)
    right_parts = urllib.parse.urlsplit(right)
    return (
        left_parts.scheme.lower() == right_parts.scheme.lower()
        and left_parts.netloc.lower() == right_parts.netloc.lower()
    )


def _effective_document_base(
    document_url: str,
    base_hrefs: list[str | None],
) -> tuple[str, str]:
    if not base_hrefs:
        return document_url, "document_url"

    resolved_bases: list[str] = []
    for href in base_hrefs:
        if href is None or not href.strip():
            raise DeployFailure(
                "Rendered head contains a base element without an href."
            )
        resolved = urllib.parse.urljoin(document_url, href)
        parsed = urllib.parse.urlsplit(resolved)
        if (
            parsed.scheme.lower() != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or not _same_origin(document_url, resolved)
        ):
            raise DeployFailure(
                "Rendered head contains an external or unsafe base URL."
            )
        resolved_bases.append(resolved)

    if len(set(resolved_bases)) != 1:
        raise DeployFailure(
            "Rendered head contains mixed base URLs."
        )
    return resolved_bases[0], "same_origin_base"


def _resolve_head_href(
    document_url: str,
    effective_base: str,
    href: str,
    *,
    require_same_origin: bool = True,
) -> str:
    if any(ord(character) < 32 for character in href):
        raise DeployFailure("Rendered head contains an unsafe asset URL.")
    resolved = urllib.parse.urljoin(effective_base, href)
    parsed = urllib.parse.urlsplit(resolved)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise DeployFailure("Rendered head contains an unsafe asset URL.")
    if require_same_origin and not _same_origin(document_url, resolved):
        raise DeployFailure("Rendered head contains an external asset URL.")
    return resolved


def _has_only_version_query(url: str, version: str) -> bool:
    return urllib.parse.parse_qsl(
        urllib.parse.urlsplit(url).query,
        keep_blank_values=True,
    ) == [("ver", version)]


def _fetch_exact_asset(
    url: str,
    *,
    label: str,
    allowed_media_types: set[str],
) -> None:
    status, content_type, body = request(
        url,
        timeout=90,
        accept=", ".join(sorted(allowed_media_types)),
    )
    media_type = content_type.split(";", 1)[0].strip().lower()
    if (
        status != 200
        or media_type not in allowed_media_types
        or not body
    ):
        raise DeployFailure(
            f"{label} did not return the exact expected public asset."
        )
    if media_type == "text/css" and "\ufffd" in body:
        raise DeployFailure(
            f"{label} did not return valid text content."
        )
    if media_type == "image/svg+xml":
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError as error:
            raise DeployFailure(
                f"{label} did not return a valid SVG document."
            ) from error
        if root.tag.rsplit("}", 1)[-1].lower() != "svg":
            raise DeployFailure(
                f"{label} did not return a valid SVG document."
            )


def read_site_icon_identity(
    base_url: str,
    auth: str,
    *,
    expect_fallback_favicon: bool,
) -> dict:
    status, content_type, body = request(
        f"{base_url}/wp-json/wp/v2/settings?_fields=site_icon",
        auth=auth,
        timeout=60,
    )
    settings = json_object(
        status,
        content_type,
        body,
        "WordPress site-icon settings verification",
    )
    site_icon_id = settings.get("site_icon", 0)
    if (
        site_icon_id is None
        or site_icon_id is False
        or site_icon_id == ""
    ):
        site_icon_id = 0
    if (
        isinstance(site_icon_id, bool)
        or not isinstance(site_icon_id, int)
        or site_icon_id < 0
    ):
        raise DeployFailure(
            "WordPress returned an invalid site-icon identity."
        )

    if expect_fallback_favicon:
        if site_icon_id != 0:
            raise DeployFailure(
                "Fallback favicon mode conflicts with the configured "
                "WordPress site icon."
            )
        return {
            "id": 0,
            "mime_by_url": {},
            "mode": "theme_fallback",
            "urls": set(),
        }

    if site_icon_id <= 0:
        raise DeployFailure(
            "Configured site-icon mode requires a WordPress site icon."
        )
    status, content_type, body = request(
        (
            f"{base_url}/wp-json/wp/v2/media/{site_icon_id}"
            "?context=edit&_fields=id,source_url,media_type,mime_type,"
            "media_details"
        ),
        auth=auth,
        timeout=60,
    )
    media = json_object(
        status,
        content_type,
        body,
        "WordPress site-icon media verification",
    )
    mime_type = media.get("mime_type")
    if (
        media.get("id") != site_icon_id
        or media.get("media_type") != "image"
        or not isinstance(mime_type, str)
        or not mime_type.lower().startswith("image/")
    ):
        raise DeployFailure(
            "Configured WordPress site icon is not the expected image media."
        )

    candidates: list[tuple[str, str]] = []
    source_url = media.get("source_url")
    if isinstance(source_url, str) and source_url:
        candidates.append((source_url, mime_type.lower()))
    media_details = media.get("media_details")
    if isinstance(media_details, dict):
        sizes = media_details.get("sizes")
        if isinstance(sizes, dict):
            for size in sizes.values():
                if not isinstance(size, dict):
                    continue
                size_url = size.get("source_url")
                size_mime = size.get("mime_type", mime_type)
                if (
                    isinstance(size_url, str)
                    and size_url
                    and isinstance(size_mime, str)
                    and size_mime.lower().startswith("image/")
                ):
                    candidates.append((size_url, size_mime.lower()))

    mime_by_url: dict[str, str] = {}
    for url, candidate_mime in candidates:
        validate_https_url(url, "WordPress site-icon media URL")
        if not _same_origin(base_url, url):
            raise DeployFailure(
                "WordPress site-icon media URL is not on the site origin."
            )
        mime_by_url[url] = candidate_mime
    if not mime_by_url:
        raise DeployFailure(
            "WordPress site-icon media has no usable public URL."
        )
    return {
        "id": site_icon_id,
        "mime_by_url": mime_by_url,
        "mode": "configured_site_icon",
        "urls": set(mime_by_url),
    }


def _site_icon_identity_equal(left: dict, right: dict) -> bool:
    return (
        left.get("id") == right.get("id")
        and left.get("mode") == right.get("mode")
        and left.get("urls") == right.get("urls")
        and left.get("mime_by_url") == right.get("mime_by_url")
    )


def verify_rendered_transition(
    base_url: str,
    render_path: str,
    required_marker: str,
    forbidden_marker: str,
    theme_slug: str,
    theme_version: str,
    site_icon_identity: dict,
    *,
    fetch_assets: bool = True,
) -> dict:
    document_url = add_cache_buster(f"{base_url}{render_path}")
    status, content_type, rendered = request(
        document_url,
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
    if required_marker not in rendered_body:
        raise DeployFailure("Required rendered-body marker is absent.")
    if forbidden_marker in rendered_body:
        raise DeployFailure("Forbidden rendered-body marker is present.")

    head_facts = ThemeHeadFacts()
    try:
        head_facts.feed(rendered)
        head_facts.close()
    except Exception as error:
        raise DeployFailure(
            "Rendered page head could not be parsed."
        ) from error

    effective_base, base_mode = _effective_document_base(
        document_url,
        head_facts.base_hrefs,
    )
    if head_facts.base_outside_head:
        raise DeployFailure(
            "Rendered document contains a base element outside the head."
        )
    expected_style_path = f"/wp-content/themes/{theme_slug}/style.css"
    expected_favicon_path = (
        f"/wp-content/themes/{theme_slug}/assets/favicon.svg"
    )

    style_urls: list[str] = []
    icon_urls: list[str] = []
    for link in head_facts.links:
        relations = {
            value.lower()
            for value in link.get("rel", "").split()
        }
        href = link.get("href", "")
        if not href or not relations.intersection({"stylesheet", "icon"}):
            continue
        resolved = _resolve_head_href(
            document_url,
            effective_base,
            href,
            require_same_origin=False,
        )
        path = urllib.parse.urlsplit(resolved).path
        if not _same_origin(document_url, resolved):
            if "icon" in relations or path == expected_style_path:
                raise DeployFailure(
                    "Rendered head contains an external release asset URL."
                )
            continue
        if "stylesheet" in relations and path == expected_style_path:
            style_urls.append(resolved)
        if "icon" in relations:
            icon_urls.append(resolved)

    if (
        len(style_urls) != 1
        or not _has_only_version_query(style_urls[0], theme_version)
    ):
        raise DeployFailure(
            "Rendered head does not contain exactly one versioned "
            "theme stylesheet."
        )
    if fetch_assets:
        _fetch_exact_asset(
            style_urls[0],
            label="Theme stylesheet",
            allowed_media_types={"text/css"},
        )

    favicon_mode = site_icon_identity.get("mode")
    if favicon_mode == "theme_fallback":
        if (
            site_icon_identity.get("id") != 0
            or len(icon_urls) != 1
            or urllib.parse.urlsplit(icon_urls[0]).path
            != expected_favicon_path
            or not _has_only_version_query(icon_urls[0], theme_version)
        ):
            raise DeployFailure(
                "Rendered head does not contain exactly one versioned "
                "theme favicon."
            )
        verified_favicon_path = expected_favicon_path
        if fetch_assets:
            _fetch_exact_asset(
                icon_urls[0],
                label="Theme favicon",
                allowed_media_types={"image/svg+xml"},
            )
    elif favicon_mode == "configured_site_icon":
        allowed_urls = site_icon_identity.get("urls")
        mime_by_url = site_icon_identity.get("mime_by_url")
        if (
            not isinstance(allowed_urls, set)
            or not isinstance(mime_by_url, dict)
            or not icon_urls
            or any(url not in allowed_urls for url in icon_urls)
            or any(
                urllib.parse.urlsplit(url).path == expected_favicon_path
                for url in icon_urls
            )
        ):
            raise DeployFailure(
                "Rendered head does not contain the expected configured "
                "WordPress site icon."
            )
        verified_favicon_path = urllib.parse.urlsplit(icon_urls[0]).path
        if fetch_assets:
            for icon_url in sorted(set(icon_urls)):
                _fetch_exact_asset(
                    icon_url,
                    label="Configured WordPress site icon",
                    allowed_media_types={mime_by_url[icon_url]},
                )
    else:
        raise DeployFailure("Site-icon verification mode is invalid.")

    return {
        "assets_fetched": fetch_assets,
        "base_mode": base_mode,
        "favicon_path": verified_favicon_path,
        "favicon_mode": favicon_mode,
        "icon_count": len(icon_urls),
        "stylesheet_path": expected_style_path,
        "version": theme_version,
    }


def verify_rendered_body(
    base_url: str,
    render_path: str,
    new_marker: str,
    old_marker: str,
    theme_slug: str,
    theme_version: str,
    expect_fallback_favicon: bool,
) -> dict:
    """Compatibility wrapper for focused parser tests.

    The deployment workflow uses verify_rendered_transition with an
    authenticated WordPress site-icon identity and exact asset fetching.
    """
    if expect_fallback_favicon:
        identity = {
            "id": 0,
            "mime_by_url": {},
            "mode": "theme_fallback",
            "urls": set(),
        }
    else:
        identity = {
            "id": 1,
            "mime_by_url": {},
            "mode": "configured_site_icon",
            "urls": set(),
        }
        status, content_type, rendered = request(
            add_cache_buster(f"{base_url}{render_path}"),
            timeout=90,
        )
        if status != 200 or "html" not in content_type.lower():
            raise DeployFailure(
                "Rendered page did not return HTML with HTTP 200."
            )
        facts = ThemeHeadFacts()
        facts.feed(rendered)
        effective_base, _ = _effective_document_base(
            f"{base_url}{render_path}",
            facts.base_hrefs,
        )
        urls = {
            _resolve_head_href(
                f"{base_url}{render_path}",
                effective_base,
                link.get("href", ""),
            )
            for link in facts.links
            if "icon" in {
                value.lower()
                for value in link.get("rel", "").split()
            }
            and link.get("href")
        }
        identity["urls"] = urls
        identity["mime_by_url"] = {
            url: "image/png"
            for url in urls
        }
    return verify_rendered_transition(
        base_url,
        render_path,
        new_marker,
        old_marker,
        theme_slug,
        theme_version,
        identity,
        fetch_assets=False,
    )


def build_route_code(
    *,
    route_template: str,
    theme_slug: str,
    version: str,
    zip_url: str,
    zip_sha256: str,
    zip_size: int,
    route_token: str,
) -> str:
    if (
        not isinstance(route_template, str)
        or hashlib.sha256(route_template.encode("utf-8")).hexdigest()
        != THEME_ROUTE_TEMPLATE_SHA256
    ):
        raise DeployFailure(
            "Theme route template does not match the frozen release."
        )
    route_code = route_template
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


def prepare_output_path(value: Path | str) -> Path:
    output_path = Path(value).expanduser().resolve()
    if output_path.exists() or output_path.is_symlink():
        raise DeployFailure("--output already exists; refusing to overwrite it.")
    if not output_path.parent.is_dir():
        raise DeployFailure("--output parent directory does not exist.")
    return output_path


def require_allowlisted_evidence(
    payload: dict,
    schema: dict = DEPLOY_EVIDENCE_SCHEMA,
    *,
    context: str = "evidence",
) -> None:
    if not isinstance(payload, dict):
        raise DeployFailure("Deployment evidence has an invalid shape.")
    unexpected = set(payload).difference(schema)
    if unexpected:
        raise DeployFailure(
            f"Deployment {context} contains a non-allowlisted field."
        )
    for key, value in payload.items():
        child_schema = schema[key]
        if isinstance(child_schema, dict):
            if not isinstance(value, dict):
                raise DeployFailure(
                    f"Deployment {context} has an invalid nested shape."
                )
            require_allowlisted_evidence(
                value,
                child_schema,
                context=f"{context}.{key}",
            )
        elif isinstance(value, (dict, list, set, tuple)):
            raise DeployFailure(
                f"Deployment {context} has an invalid field value."
            )


def write_new_evidence(output_path: Path, payload: dict) -> None:
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    temporary_path = output_path.with_name(
        f".{output_path.name}.tmp-{os.getpid()}-{secrets.token_hex(8)}"
    )
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary_path, output_path)
        except FileExistsError as error:
            raise DeployFailure(
                "--output was created concurrently; refusing to overwrite it."
            ) from error
    except DeployFailure:
        raise
    except OSError as error:
        raise DeployFailure(
            "Durable deployment evidence could not be written."
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def _safe_render_evidence(rendered: dict) -> dict:
    return {
        "assets_fetched": rendered.get("assets_fetched") is True,
        "base_mode": rendered.get("base_mode"),
        "favicon_mode": rendered.get("favicon_mode"),
        "favicon_path": rendered.get("favicon_path"),
        "icon_count": rendered.get("icon_count"),
        "stylesheet_path": rendered.get("stylesheet_path"),
        "version": rendered.get("version"),
    }


def _run_deployment(args: argparse.Namespace, evidence: dict) -> None:
    evidence["failure_stage"] = "input_validation"
    validate_inputs(args)
    evidence.update(
        {
            "previous_version": args.previous_version,
            "target_version": args.version,
            "theme": args.theme_slug,
        }
    )

    evidence["failure_stage"] = "public_boundary"
    boundary = validate_theme_boundary_receipt(args)
    route_template = boundary.get("route_template")
    if not isinstance(route_template, str):
        raise DeployFailure(
            "Theme public-boundary proof did not freeze the route template."
        )

    evidence["failure_stage"] = "runtime_authority"
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
    evidence["authority_verified"] = True

    evidence["failure_stage"] = "artifact_preflight"
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
    evidence["artifact"] = {
        "files": artifact["zip_files"],
        "sha256": artifact["zip_sha256"],
        "size": artifact["zip_bytes"],
    }

    evidence["failure_stage"] = "temporary_surface_preflight"
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
    snippet_count = require_snippet_capacity(base_url, auth)
    evidence["temporary_surface"] = {
        "legacy_route_absent": True,
        "route_absent": True,
        "snippet_count": snippet_count,
        "snippet_limit": MAX_CODE_SNIPPETS_RECORDS,
        "snippet_name_absent": True,
    }

    evidence["failure_stage"] = "before_state"
    before_theme = verify_theme_rest_record(
        base_url,
        auth,
        args.theme_slug,
        args.previous_version,
    )
    before_site_icon = read_site_icon_identity(
        base_url,
        auth,
        expect_fallback_favicon=args.expect_fallback_favicon,
    )
    before_render = verify_rendered_transition(
        base_url,
        args.render_path,
        args.old_body_marker,
        args.new_body_marker,
        args.theme_slug,
        args.previous_version,
        before_site_icon,
    )
    evidence["before"] = {
        "active_block_theme": True,
        "active_version": before_theme["version"],
        "configured_site_icon_id": before_site_icon["id"],
        "new_marker_absent": True,
        "old_marker_present": True,
        "rendered_assets": _safe_render_evidence(before_render),
    }

    if not args.execute:
        evidence.pop("failure_stage", None)
        evidence["cleanup"] = {
            "attempted": False,
            "legacy_route_absent": True,
            "proven": True,
            "route_absent": True,
            "snippet_absent": True,
        }
        evidence["status"] = "preflight_ok"
        return

    route_code = build_route_code(
        route_template=route_template,
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
    failure_stage = "temporary_route_creation"

    try:
        failure_stage = "action_boundary"
        evidence["failure_stage"] = failure_stage
        action_boundary = validate_theme_boundary_receipt(args)
        if (
            action_boundary.get("route_template") != route_template
            or action_boundary.get("artifact_path")
            != boundary.get("artifact_path")
            or action_boundary.get("git_head") != boundary.get("git_head")
            or action_boundary.get("receipt_body_sha256")
            != boundary.get("receipt_body_sha256")
        ):
            raise DeployFailure(
                "Theme release boundary changed before the mutation."
            )

        failure_stage = "temporary_route_creation"
        evidence["failure_stage"] = failure_stage
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

        callback_failure: Exception | None = None
        callback_confirmed = False
        failure_stage = "deployment_callback"
        evidence["failure_stage"] = failure_stage
        try:
            status, content_type, body = request(
                f"{base_url}{route_path}",
                method="POST",
                auth=auth,
                payload={},
                timeout=300,
            )
            confirm_exact_deployment_callback(
                status,
                content_type,
                body,
                theme_slug=args.theme_slug,
                version=args.version,
            )
            callback_confirmed = True
        except Exception as exception:
            callback_failure = exception
        evidence["callback"] = {
            "artifact_sha256": artifact["zip_sha256"],
            "artifact_size": artifact["zip_bytes"],
            "artifact_verified": callback_confirmed,
            "confirmed": callback_confirmed,
            "target_version": args.version,
        }

        independent_failures: list[str] = []
        after_theme: dict = {}
        after_render: dict = {}
        after_site_icon: dict = {}
        failure_stage = "after_state"
        evidence["failure_stage"] = failure_stage
        try:
            after_theme = verify_theme_rest_record(
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
            after_site_icon = read_site_icon_identity(
                base_url,
                auth,
                expect_fallback_favicon=args.expect_fallback_favicon,
            )
            if not _site_icon_identity_equal(
                before_site_icon,
                after_site_icon,
            ):
                raise DeployFailure(
                    "WordPress site-icon identity changed during deployment."
                )
        except Exception as exception:
            independent_failures.append(
                "site-icon identity verification failed with "
                f"{type(exception).__name__}"
            )
        if after_site_icon:
            try:
                after_render = verify_rendered_transition(
                    base_url,
                    args.render_path,
                    args.new_body_marker,
                    args.old_body_marker,
                    args.theme_slug,
                    args.version,
                    after_site_icon,
                )
            except Exception as exception:
                independent_failures.append(
                    "rendered release verification failed with "
                    f"{type(exception).__name__}"
                )

        if after_theme and after_render and after_site_icon:
            evidence["after"] = {
                "active_block_theme": True,
                "active_version": after_theme["version"],
                "configured_site_icon_id": after_site_icon["id"],
                "new_marker_present": True,
                "old_marker_absent": True,
                "rendered_assets": _safe_render_evidence(after_render),
                "site_icon_identity_unchanged": True,
            }
        verification_failures = list(independent_failures)
        if callback_failure is not None:
            verification_failures.insert(
                0,
                "bound deployment callback verification failed with "
                f"{type(callback_failure).__name__}",
            )
        if verification_failures:
            if callback_failure is not None and not independent_failures:
                failure_stage = "deployment_callback"
                evidence["failure_stage"] = failure_stage
            raise DeployFailure(
                "Theme deployment verification failed: "
                + "; ".join(verification_failures)
                + "."
            )
    except Exception as exception:
        failure = exception
        evidence["failure_stage"] = failure_stage
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
        evidence["cleanup"] = {
            "attempted": True,
            "legacy_route_absent": legacy_route_absent_after,
            "proven": cleanup_proven,
            "route_absent": route_absent_after,
            "snippet_absent": snippet_absent_after,
        }
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
                evidence["failure_stage"] = "cleanup"
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

    evidence.pop("failure_stage", None)
    evidence["status"] = "deployed"


def main() -> int:
    args = parse_args()
    output_path = prepare_output_path(args.output)
    evidence = {
        "execute": bool(args.execute),
        "recorded_at": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
        "schema_version": 1,
        "status": "started",
    }
    try:
        _run_deployment(args, evidence)
    except Exception as error:
        evidence["failure_stage"] = evidence.get(
            "failure_stage",
            "unclassified",
        )
        evidence["failure_type"] = type(error).__name__
        evidence["status"] = "failed"
        temporary_surface = evidence.get("temporary_surface", {})
        surface_proven = (
            isinstance(temporary_surface, dict)
            and temporary_surface.get("legacy_route_absent") is True
            and temporary_surface.get("route_absent") is True
            and temporary_surface.get("snippet_name_absent") is True
        )
        evidence.setdefault(
            "cleanup",
            {
                "attempted": False,
                "legacy_route_absent": (
                    True if surface_proven else None
                ),
                "proven": surface_proven,
                "route_absent": True if surface_proven else None,
                "snippet_absent": True if surface_proven else None,
            },
        )
        require_allowlisted_evidence(evidence)
        write_new_evidence(output_path, evidence)
        emit_evidence(evidence)
        if isinstance(error, DeployFailure):
            raise
        raise DeployFailure(
            f"Theme deployment failed with {type(error).__name__}."
        ) from error

    require_allowlisted_evidence(evidence)
    write_new_evidence(output_path, evidence)
    emit_evidence(evidence)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except DeployFailure as error:
        print(f"Theme deployment failed: {error}", file=sys.stderr)
        sys.exit(1)
