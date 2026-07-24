#!/usr/bin/env python3
"""Deploy a reviewed plugin through a temporary Code Snippets REST route."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import math
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
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
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
MAX_BOUNDARY_RECEIPT_BYTES = 64 * 1024
MAX_BOUNDARY_SCANNER_BYTES = 4 * 1024 * 1024
MAX_DEPLOY_ROUTE_TEMPLATE_BYTES = 1024 * 1024
MAX_BOUNDARY_RELEASE_ARTIFACTS = 10_000
MAX_TRUSTED_GIT_EXECUTABLE_BYTES = 128 * 1024 * 1024
MAX_TRUSTED_GIT_OUTPUT_BYTES = 128 * 1024 * 1024
MAX_CODE_SNIPPETS_RECORDS = 98
BOUNDARY_RECEIPT_TYPE = "robbottx_public_boundary_release"
BOUNDARY_RECEIPT_MAX_AGE = timedelta(minutes=15)
BOUNDARY_RECEIPT_MAX_FUTURE_SKEW = timedelta(0)
BOUNDARY_SCANNER_MODULE_NAME = "_robbottx_reviewed_boundary_scanner"
TRUSTED_GIT_TIMEOUT_SECONDS = 60
TRUSTED_GIT_SUBCOMMANDS = {
    "cat-file",
    "check-ignore",
    "ls-files",
    "rev-parse",
    "status",
}
DEPLOY_CALLBACK_FIELDS = {
    "result",
    "active",
    "version",
    "artifact_verified",
}


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
    parser.add_argument(
        "--boundary-receipt",
        required=True,
        type=Path,
    )
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


def _json_object_without_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate JSON object key")
        document[key] = value
    return document


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"invalid JSON constant: {value}")


def _parse_finite_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("non-finite JSON number")
    return parsed


def _strict_json_loads(body: str) -> object:
    return json.loads(
        body,
        object_pairs_hook=_json_object_without_duplicate_keys,
        parse_constant=_reject_json_constant,
        parse_float=_parse_finite_json_float,
    )


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{64}", value) is not None
    )


def _has_exact_keys(value: object, expected: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == expected


def _trusted_windows_git_roots() -> list[Path]:
    roots = [Path("C:/Program Files/Git")]
    try:
        import winreg
    except ImportError:
        return roots

    access_modes = [winreg.KEY_READ]
    for attribute in ("KEY_WOW64_64KEY", "KEY_WOW64_32KEY"):
        mode = getattr(winreg, attribute, 0)
        if mode:
            access_modes.append(winreg.KEY_READ | mode)
    for access_mode in access_modes:
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
        "No protected absolute Git executable is available for boundary verification."
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


class _TrustedGitSubprocess:
    def __init__(
        self,
        run_callable,
        git_executable: Path,
        repository_root: Path,
    ) -> None:
        self._run_callable = run_callable
        self._git_executable = git_executable
        self._repository_root = repository_root
        self._environment = _trusted_git_environment(git_executable)

    def run(self, command, *positional, **kwargs):
        if (
            not isinstance(command, (list, tuple))
            or len(command) < 4
            or len(command) > 16
            or any(
                not isinstance(argument, str)
                or "\x00" in argument
                or len(argument) > 32_768
                for argument in command
            )
            or command[0] != "git"
            or command[1] != "-C"
            or command[3] not in TRUSTED_GIT_SUBCOMMANDS
            or positional
            or not set(kwargs).issubset(
                {"capture_output", "check", "text"}
            )
            or kwargs.get("capture_output") is not True
            or kwargs.get("check") not in (None, False)
            or kwargs.get("text") not in (None, False, True)
        ):
            raise OSError("unreviewed Git invocation")
        try:
            command_root = Path(command[2]).resolve(strict=True)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            raise OSError("Git repository root could not be resolved") from error
        if command_root != self._repository_root:
            raise OSError("Git invocation escaped the reviewed repository")

        kwargs["timeout"] = TRUSTED_GIT_TIMEOUT_SECONDS
        kwargs["env"] = self._environment
        result = self._run_callable(
            [str(self._git_executable), *command[1:]],
            **kwargs,
        )
        for stream in (result.stdout, result.stderr):
            if (
                isinstance(stream, (bytes, str))
                and len(stream) > MAX_TRUSTED_GIT_OUTPUT_BYTES
            ):
                raise OSError("Git output exceeded the boundary verification limit")
        return result


def read_clean_index_file(
    repository_root: Path,
    relative_path: str,
    *,
    max_bytes: int,
) -> tuple[bytes, str]:
    try:
        resolved_root = Path(repository_root).resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
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
        raise DeployFailure("Reviewed repository file path is invalid.")

    git_executable = resolve_trusted_git_executable()
    git = _TrustedGitSubprocess(
        subprocess.run,
        git_executable,
        resolved_root,
    )

    def read_head_and_status() -> str:
        head_result = git.run(
            ["git", "-C", str(resolved_root), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
        status_result = git.run(
            ["git", "-C", str(resolved_root), "status", "--porcelain=v1"],
            check=False,
            capture_output=True,
            text=True,
        )
        head = (
            head_result.stdout.strip()
            if head_result.returncode == 0
            and isinstance(head_result.stdout, str)
            else ""
        )
        if (
            re.fullmatch(r"[0-9a-f]{40}", head) is None
            or status_result.returncode != 0
            or not isinstance(status_result.stdout, str)
            or status_result.stdout
        ):
            raise DeployFailure(
                "Reviewed repository must be clean before loading release code."
            )
        return head

    initial_head = read_head_and_status()
    index_result = git.run(
        [
            "git",
            "-C",
            str(resolved_root),
            "ls-files",
            "-z",
            "--cached",
            "--stage",
            "--",
            relative_path,
        ],
        check=False,
        capture_output=True,
    )
    if (
        index_result.returncode != 0
        or not isinstance(index_result.stdout, bytes)
    ):
        raise DeployFailure(
            "Reviewed repository file index entry could not be read."
        )
    entries = [
        entry
        for entry in index_result.stdout.split(b"\x00")
        if entry
    ]
    if len(entries) != 1:
        raise DeployFailure(
            "Reviewed repository file has no unique index entry."
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
            "Reviewed repository file index entry is malformed."
        ) from error
    if (
        mode not in {b"100644", b"100755"}
        or stage != b"0"
        or indexed_path != relative_path
        or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", object_id)
        is None
    ):
        raise DeployFailure(
            "Reviewed repository file index entry is not an exact regular file."
        )

    size_result = git.run(
        [
            "git",
            "-C",
            str(resolved_root),
            "cat-file",
            "-s",
            object_id,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    try:
        object_size = int(size_result.stdout.strip())
    except (AttributeError, TypeError, ValueError) as error:
        raise DeployFailure(
            "Reviewed repository file size could not be established."
        ) from error
    if (
        size_result.returncode != 0
        or object_size <= 0
        or object_size > max_bytes
    ):
        raise DeployFailure(
            "Reviewed repository file exceeds its execution limit."
        )

    blob_result = git.run(
        [
            "git",
            "-C",
            str(resolved_root),
            "cat-file",
            "blob",
            object_id,
        ],
        check=False,
        capture_output=True,
    )
    if (
        blob_result.returncode != 0
        or not isinstance(blob_result.stdout, bytes)
        or len(blob_result.stdout) != object_size
    ):
        raise DeployFailure(
            "Reviewed repository file bytes could not be read exactly."
        )

    worktree_path = resolved_root.joinpath(*candidate.parts)
    try:
        metadata = worktree_path.lstat()
        if (
            worktree_path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size != object_size
            or metadata.st_size > max_bytes
        ):
            raise OSError("worktree file metadata mismatch")
        with worktree_path.open("rb") as handle:
            worktree_payload = handle.read(max_bytes + 1)
    except OSError as error:
        raise DeployFailure(
            "Reviewed worktree file could not be verified."
        ) from error
    if (
        len(worktree_payload) != object_size
        or not secrets.compare_digest(
            worktree_payload,
            blob_result.stdout,
        )
    ):
        raise DeployFailure(
            "Reviewed worktree file differs from its clean Git index bytes."
        )

    final_head = read_head_and_status()
    if final_head != initial_head:
        raise DeployFailure(
            "Reviewed repository changed while release code was loaded."
        )
    return blob_result.stdout, initial_head


def run_reviewed_boundary_scan(repository_root: Path) -> object:
    expected_root = Path(__file__).resolve().parents[1]
    try:
        resolved_root = Path(repository_root).resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise DeployFailure(
            "Reviewed public-boundary scanner repository could not be resolved."
        ) from error
    if resolved_root != expected_root:
        raise DeployFailure(
            "Reviewed public-boundary scanner must run from this repository."
        )

    scanner_path = resolved_root / "scripts" / "validate-proprietary-boundary.py"
    scanner_payload, bootstrap_head = read_clean_index_file(
        resolved_root,
        "scripts/validate-proprietary-boundary.py",
        max_bytes=MAX_BOUNDARY_SCANNER_BYTES,
    )

    previous_module = sys.modules.get(BOUNDARY_SCANNER_MODULE_NAME)
    had_previous_module = BOUNDARY_SCANNER_MODULE_NAME in sys.modules
    try:
        scanner_module = types.ModuleType(BOUNDARY_SCANNER_MODULE_NAME)
        scanner_module.__file__ = str(scanner_path)
        scanner_module.__package__ = None
        sys.modules[BOUNDARY_SCANNER_MODULE_NAME] = scanner_module
        scanner_code = compile(
            scanner_payload,
            str(scanner_path),
            "exec",
        )
        exec(scanner_code, scanner_module.__dict__)
        if (
            not callable(
                getattr(scanner_module, "resolve_trusted_git_executable", None)
            )
            or not callable(getattr(scanner_module, "run_git", None))
        ):
            raise AttributeError(
                "boundary scanner protected Git execution unavailable"
            )
        scanner = getattr(scanner_module, "scan_repository_report", None)
        if not callable(scanner):
            raise AttributeError("boundary scanner entry point unavailable")
        report = scanner(resolved_root)
        if (
            getattr(report, "git_head", None) != bootstrap_head
            or getattr(report, "git_dirty", None) is not False
        ):
            raise ValueError(
                "boundary scanner did not retain the reviewed clean commit"
            )
        return report
    except Exception as error:
        raise DeployFailure(
            "Reviewed public-boundary scanner could not be executed."
        ) from error
    finally:
        if had_previous_module:
            sys.modules[BOUNDARY_SCANNER_MODULE_NAME] = previous_module
        else:
            sys.modules.pop(BOUNDARY_SCANNER_MODULE_NAME, None)


def verify_current_boundary_scan(
    scan_report: object,
    receipt: dict[str, object],
    *,
    expected_artifact_path: str,
    expected_zip_sha256: str,
    expected_record_hash: str,
) -> None:
    try:
        findings = scan_report.findings
        git_head = scan_report.git_head
        git_dirty = scan_report.git_dirty
        git_index_sha256 = scan_report.git_index_content_sha256
        worktree_sha256 = scan_report.worktree_content_sha256
        repository_sha256 = scan_report.repository_content_sha256
        asset_manifest_sha256 = scan_report.asset_manifest_sha256
        public_snapshot_sha256 = (
            scan_report.public_snapshot_payload_sha256
        )
        release_artifacts = scan_report.release_artifacts
    except (AttributeError, TypeError) as error:
        raise DeployFailure(
            "Reviewed public-boundary scanner returned an invalid report."
        ) from error

    if (
        not isinstance(findings, tuple)
        or findings
        or git_dirty is not False
        or not isinstance(git_head, str)
        or re.fullmatch(r"[0-9a-f]{40}", git_head) is None
        or not _is_sha256(git_index_sha256)
        or not _is_sha256(worktree_sha256)
        or not _is_sha256(repository_sha256)
        or not _is_sha256(asset_manifest_sha256)
        or not _is_sha256(public_snapshot_sha256)
        or git_index_sha256 != worktree_sha256
        or repository_sha256 != worktree_sha256
        or public_snapshot_sha256 != expected_record_hash
        or not isinstance(release_artifacts, tuple)
        or len(release_artifacts) > MAX_BOUNDARY_RELEASE_ARTIFACTS
    ):
        raise DeployFailure(
            "Reviewed public-boundary scan did not prove a clean current release."
        )

    matching_artifact_hashes: list[str] = []
    for entry in release_artifacts:
        if (
            not isinstance(entry, tuple)
            or len(entry) != 2
            or not isinstance(entry[0], str)
            or not _is_sha256(entry[1])
        ):
            raise DeployFailure(
                "Reviewed public-boundary scanner returned an invalid artifact inventory."
            )
        if entry[0] == expected_artifact_path:
            matching_artifact_hashes.append(entry[1])
    if matching_artifact_hashes != [expected_zip_sha256]:
        raise DeployFailure(
            "Reviewed public-boundary scan did not match the exact release artifact."
        )

    repository = receipt["repository"]
    public_boundary = receipt["public_boundary"]
    artifact = receipt["artifact"]
    assert isinstance(repository, dict)
    assert isinstance(public_boundary, dict)
    assert isinstance(artifact, dict)
    if (
        repository["git_head"] != git_head
        or repository["git_dirty"] is not False
        or repository["git_index_content_sha256"] != git_index_sha256
        or repository["worktree_content_sha256"] != worktree_sha256
        or public_boundary["repository_content_sha256"]
        != repository_sha256
        or public_boundary["asset_manifest_sha256"]
        != asset_manifest_sha256
        or public_boundary["public_snapshot_payload_sha256"]
        != public_snapshot_sha256
        or public_boundary["finding_count"] != 0
        or artifact["path"] != expected_artifact_path
        or artifact["sha256"] != expected_zip_sha256
    ):
        raise DeployFailure(
            "Public boundary release receipt does not match the current reviewed repository."
        )


def validate_boundary_receipt(
    receipt_path: Path,
    *,
    version: str,
    slug: str,
    zip_sha256: str,
    record_hash: str,
    artifact_path: str | None = None,
    repository_root: Path | None = None,
    current_time: datetime | None = None,
    scan_report: object | None = None,
) -> dict[str, str]:
    try:
        with Path(receipt_path).open("rb") as receipt_file:
            payload = receipt_file.read(MAX_BOUNDARY_RECEIPT_BYTES + 1)
    except (OSError, TypeError, ValueError) as error:
        raise DeployFailure(
            "Public boundary release receipt could not be read."
        ) from error
    if len(payload) > MAX_BOUNDARY_RECEIPT_BYTES:
        raise DeployFailure(
            "Public boundary release receipt exceeds the safe size limit."
        )

    try:
        receipt = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_json_object_without_duplicate_keys,
        )
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as error:
        raise DeployFailure(
            "Public boundary release receipt is invalid JSON."
        ) from error

    if not _has_exact_keys(
        receipt,
        {
            "schema_version",
            "receipt_type",
            "release_mode",
            "created_at",
            "repository",
            "public_boundary",
            "artifact",
            "receipt_body_sha256",
        },
    ):
        raise DeployFailure(
            "Public boundary release receipt has an unexpected shape."
        )
    assert isinstance(receipt, dict)

    stored_body_sha256 = receipt["receipt_body_sha256"]
    if not _is_sha256(stored_body_sha256):
        raise DeployFailure(
            "Public boundary release receipt body hash is invalid."
        )
    receipt_body = {
        key: value
        for key, value in receipt.items()
        if key != "receipt_body_sha256"
    }
    try:
        canonical_body = json.dumps(
            receipt_body,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise DeployFailure(
            "Public boundary release receipt body is not canonicalizable."
        ) from error
    recomputed_body_sha256 = hashlib.sha256(canonical_body).hexdigest()
    assert isinstance(stored_body_sha256, str)
    if not secrets.compare_digest(
        stored_body_sha256,
        recomputed_body_sha256,
    ):
        raise DeployFailure(
            "Public boundary release receipt body hash does not match."
        )

    repository = receipt["repository"]
    public_boundary = receipt["public_boundary"]
    artifact = receipt["artifact"]
    if (
        type(receipt["schema_version"]) is not int
        or receipt["schema_version"] != 1
        or receipt["receipt_type"] != BOUNDARY_RECEIPT_TYPE
        or receipt["release_mode"] is not True
        or not _has_exact_keys(
            repository,
            {
                "git_head",
                "git_dirty",
                "git_index_content_sha256",
                "worktree_content_sha256",
            },
        )
        or not _has_exact_keys(
            public_boundary,
            {
                "repository_content_sha256",
                "asset_manifest_sha256",
                "public_snapshot_payload_sha256",
                "finding_count",
            },
        )
        or not _has_exact_keys(artifact, {"path", "sha256"})
    ):
        raise DeployFailure(
            "Public boundary release receipt is not a valid release receipt."
        )
    assert isinstance(repository, dict)
    assert isinstance(public_boundary, dict)
    assert isinstance(artifact, dict)

    created_at = receipt["created_at"]
    if (
        not isinstance(created_at, str)
        or re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
            r"(?:\.\d{1,6})?(?:Z|\+00:00)",
            created_at,
        )
        is None
    ):
        raise DeployFailure(
            "Public boundary release receipt timestamp is not UTC."
        )
    try:
        parsed_created_at = datetime.fromisoformat(
            created_at.removesuffix("Z") + (
                "+00:00" if created_at.endswith("Z") else ""
            )
        )
    except ValueError as error:
        raise DeployFailure(
            "Public boundary release receipt timestamp is invalid."
        ) from error
    if parsed_created_at.utcoffset() != timedelta(0):
        raise DeployFailure(
            "Public boundary release receipt timestamp is not UTC."
        )
    now = current_time or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise DeployFailure(
            "Current release time must include a UTC offset."
        )
    now = now.astimezone(timezone.utc)
    receipt_age = now - parsed_created_at
    if (
        receipt_age > BOUNDARY_RECEIPT_MAX_AGE
        or receipt_age < -BOUNDARY_RECEIPT_MAX_FUTURE_SKEW
    ):
        raise DeployFailure(
            "Public boundary release receipt timestamp is outside the release window."
        )

    git_head = repository["git_head"]
    if (
        repository["git_dirty"] is not False
        or not isinstance(git_head, str)
        or re.fullmatch(r"[0-9a-f]{40}", git_head) is None
        or not _is_sha256(repository["git_index_content_sha256"])
        or not _is_sha256(repository["worktree_content_sha256"])
        or not _is_sha256(public_boundary["repository_content_sha256"])
        or not _is_sha256(public_boundary["asset_manifest_sha256"])
        or not _is_sha256(public_boundary["public_snapshot_payload_sha256"])
        or type(public_boundary["finding_count"]) is not int
        or public_boundary["finding_count"] != 0
        or repository["git_index_content_sha256"]
        != repository["worktree_content_sha256"]
        or public_boundary["repository_content_sha256"]
        != repository["worktree_content_sha256"]
    ):
        raise DeployFailure(
            "Public boundary release receipt did not pass the release gate."
        )

    if artifact_path is not None and artifact_path != "hosting/robots.txt":
        raise DeployFailure(
            "Public boundary release artifact path is not approved."
        )
    expected_artifact_path = (
        artifact_path
        if artifact_path is not None
        else f"plugin-dist/{slug}-{version}.zip"
    )
    expected_zip_sha256 = zip_sha256.lower()
    expected_record_hash = record_hash.lower()
    if (
        artifact["path"] != expected_artifact_path
        or artifact["sha256"] != expected_zip_sha256
        or public_boundary["public_snapshot_payload_sha256"]
        != expected_record_hash
    ):
        raise DeployFailure(
            "Public boundary release receipt does not match the reviewed release."
        )

    if scan_report is None:
        scan_report = run_reviewed_boundary_scan(
            repository_root or Path(__file__).resolve().parents[1]
        )
    verify_current_boundary_scan(
        scan_report,
        receipt,
        expected_artifact_path=expected_artifact_path,
        expected_zip_sha256=expected_zip_sha256,
        expected_record_hash=expected_record_hash,
    )

    return {
        "receipt_body_sha256": recomputed_body_sha256,
        "git_head": git_head,
        "artifact_path": expected_artifact_path,
    }


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
    if content_type.split(";", 1)[0].strip().lower() != "application/json":
        raise DeployFailure(f"{context} returned an unexpected content type.")
    try:
        parsed = _strict_json_loads(body)
    except (
        json.JSONDecodeError,
        RecursionError,
        UnicodeError,
        ValueError,
    ) as error:
        raise DeployFailure(f"{context} returned invalid JSON.") from error
    if not isinstance(parsed, dict):
        raise DeployFailure(f"{context} returned an unexpected JSON shape.")
    return parsed


def verify_deploy_callback(
    status: int,
    content_type: str,
    body: str,
    *,
    expected_version: str,
) -> dict[str, object]:
    if status != 200 or "json" not in content_type.lower():
        raise DeployFailure(
            "Plugin deploy callback did not exactly confirm the bound release."
        )
    try:
        parsed = json.loads(
            body,
            object_pairs_hook=_json_object_without_duplicate_keys,
        )
    except (
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as error:
        raise DeployFailure(
            "Plugin deploy callback did not exactly confirm the bound release."
        ) from error
    if (
        not _has_exact_keys(parsed, DEPLOY_CALLBACK_FIELDS)
        or parsed["result"] is not True
        or parsed["active"] is not True
        or parsed["version"] != expected_version
        or parsed["artifact_verified"] is not True
    ):
        raise DeployFailure(
            "Plugin deploy callback did not exactly confirm the bound release."
        )
    return parsed


def add_cache_buster(url: str) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}rbtxcb={time.time_ns()}"


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
    if status < 200 or status >= 300:
        kind = (
            "managed-host HTML/WAF response"
            if "html" in content_type.lower()
            else "JSON/API response"
        )
        raise DeployFailure(
            f"{context} failed with HTTP {status} ({kind})."
        )
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type not in {"application/json", "text/plain"}:
        raise DeployFailure(
            f"{context} returned an unexpected content type."
        )
    try:
        parsed = _strict_json_loads(body)
    except (
        json.JSONDecodeError,
        RecursionError,
        UnicodeError,
        ValueError,
    ) as error:
        raise DeployFailure(
            f"{context} returned invalid JSON."
        ) from error
    if not isinstance(parsed, dict):
        raise DeployFailure(
            f"{context} returned an unexpected JSON shape."
        )
    return parsed


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
    if set(manifest) != REQUIRED_MANIFEST_FIELDS:
        raise DeployFailure(
            "Public update manifest fields are not exact."
        )
    if (
        any(
            not isinstance(manifest.get(field), str)
            or not manifest[field].strip()
            for field in {
                "author",
                "homepage",
                "last_updated",
                "name",
                "requires",
                "requires_php",
                "slug",
                "tested",
                "version",
                "download_url",
                "download_sha256",
                "inventory_url",
                "record_hash",
            }
        )
        or not isinstance(manifest.get("download_size"), int)
        or isinstance(manifest.get("download_size"), bool)
        or manifest.get("slug") != slug
        or manifest.get("version") != version
        or manifest.get("download_url") != zip_url
        or manifest.get("download_sha256") != zip_sha256.lower()
        or manifest.get("download_size") != zip_size
        or manifest.get("inventory_url") != inventory_url
        or manifest.get("record_hash") != record_hash.lower()
        or manifest.get("homepage") != "https://robbottx.com/"
        or not _has_exact_keys(manifest.get("sections"), {"changelog"})
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
        set(inventory) != {
            "artifact",
            "files",
            "version",
            "zip_bytes",
            "zip_sha256",
        }
        or not isinstance(inventory.get("artifact"), str)
        or not isinstance(inventory.get("version"), str)
        or not isinstance(inventory.get("zip_sha256"), str)
        or not isinstance(inventory.get("zip_bytes"), int)
        or isinstance(inventory.get("zip_bytes"), bool)
        or not isinstance(inventory.get("files"), list)
        or any(
            not _has_exact_keys(file_record, {"bytes", "path", "sha256"})
            or not isinstance(file_record["path"], str)
            or not isinstance(file_record["bytes"], int)
            or isinstance(file_record["bytes"], bool)
            or file_record["bytes"] < 0
            or not _is_sha256(file_record["sha256"])
            for file_record in inventory.get("files", [])
        )
        or inventory.get("artifact") != expected_artifact
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


def require_snippet_capacity(base_url: str, auth: str) -> int:
    status, content_type, body = request(
        (
            f"{base_url}/wp-json/code-snippets/v1/snippets"
            "?per_page=100&page=1"
        ),
        auth=auth,
        timeout=60,
    )
    if status < 200 or status >= 300:
        raise DeployFailure("Code Snippets capacity verification failed.")
    try:
        snippets = _strict_json_loads(body)
    except (
        json.JSONDecodeError,
        RecursionError,
        UnicodeError,
        ValueError,
    ) as error:
        raise DeployFailure(
            "Code Snippets capacity verification returned invalid JSON."
        ) from error
    if (
        content_type.split(";", 1)[0].strip().lower()
        != "application/json"
        or not isinstance(snippets, list)
    ):
        raise DeployFailure(
            "Code Snippets capacity verification returned an unexpected shape."
        )
    snippet_count = len(snippets)
    if snippet_count > MAX_CODE_SNIPPETS_RECORDS:
        raise DeployFailure(
            "Code Snippets has insufficient safe temporary capacity."
        )
    return snippet_count


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
        add_cache_buster(
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
                add_cache_buster(
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
            add_cache_buster(
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
    if code_snippets_record_is_missing(status, content_type, body):
        return False, []
    if status < 200 or status >= 300:
        return False, [
            f"snippet ownership lookup returned HTTP {status}"
        ]
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
    return False, [
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
    if snippet_id is not None and snippet_id not in ids:
        owned, ownership_failures = snippet_record_has_exact_name(
            base_url,
            snippet_id,
            snippet_name,
            auth,
        )
        failures.extend(ownership_failures)
        identity_ok = not ownership_failures
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

    return (
        deletion_ok
        and lookup_ok
        and identity_ok
        and not remaining
    ), failures


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


def prove_route_not_registered(
    base_url: str,
    route_path: str,
) -> tuple[bool, list[str]]:
    try:
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
            return False, [
                "WordPress REST route inventory has an unexpected shape"
            ]
        if route_path.removeprefix("/wp-json") in routes:
            return False, [
                "the route remains registered in REST inventory"
            ]
        return True, []
    except Exception as error:
        return False, [
            f"REST inventory verification raised {type(error).__name__}"
        ]


def require_route_not_registered(
    base_url: str,
    route_path: str,
) -> None:
    absent, failures = prove_route_not_registered(base_url, route_path)
    if absent:
        return
    summary = "; ".join(failures)
    message = "A stale deploy route is registered before release creation."
    if summary:
        message = f"{message} {summary}."
    raise DeployFailure(message)


def parse_created_snippet_id(created: dict) -> int:
    snippet_id = created.get("id")
    if type(snippet_id) is not int or snippet_id <= 0:
        raise DeployFailure(
            "Temporary route creation returned no usable snippet ID."
        )
    return snippet_id


def require_current_boundary_for_mutation(
    args: argparse.Namespace,
    initial_identity: dict[str, str],
    route_template_head: str,
) -> None:
    current_identity = validate_boundary_receipt(
        args.boundary_receipt,
        version=args.version,
        slug=args.plugin_slug,
        zip_sha256=args.zip_sha256,
        record_hash=args.record_hash,
    )
    if (
        current_identity != initial_identity
        or current_identity.get("git_head") != route_template_head
    ):
        raise DeployFailure(
            "Public boundary changed before the WordPress mutation."
        )


def main() -> int:
    args = parse_args()
    boundary_identity = validate_boundary_receipt(
        args.boundary_receipt,
        version=args.version,
        slug=args.plugin_slug,
        zip_sha256=args.zip_sha256,
        record_hash=args.record_hash,
    )
    route_template_payload, route_template_head = read_clean_index_file(
        Path(__file__).resolve().parents[1],
        "scripts/templates/deploy-route.php.txt",
        max_bytes=MAX_DEPLOY_ROUTE_TEMPLATE_BYTES,
    )
    if route_template_head != boundary_identity["git_head"]:
        raise DeployFailure(
            "Deploy route template is not bound to the reviewed release commit."
        )
    try:
        route_template = route_template_payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DeployFailure(
            "Deploy route template is not valid UTF-8."
        ) from error

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

    snippet_count = require_snippet_capacity(base_url, auth)
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
                    "snippet_count": snippet_count,
                    "snippet_limit": MAX_CODE_SNIPPETS_RECORDS,
                    "route_absent": True,
                    "snippet_name_absent": True,
                    "execute": False,
                },
                sort_keys=True,
            )
        )
        return 0

    route_code = route_template
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

    require_current_boundary_for_mutation(
        args,
        boundary_identity,
        route_template_head,
    )

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

        status, content_type, body = request(
            f"{base_url}{route_path}",
            method="POST",
            auth=auth,
            payload={},
            timeout=180,
        )
        verify_deploy_callback(
            status,
            content_type,
            body,
            expected_version=args.version,
        )
        callback_confirmed = True

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
        unique_route_unregistered = False
        try:
            (
                unique_route_unregistered,
                inventory_failures,
            ) = prove_route_not_registered(base_url, route_path)
            cleanup_failures.extend(inventory_failures)
        except Exception as error:
            cleanup_failures.append(
                "unique route inventory check raised "
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
            and unique_route_unregistered
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
