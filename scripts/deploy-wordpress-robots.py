#!/usr/bin/env python3
"""Create and verify the reviewed root robots.txt through a one-use route."""

from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
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
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SITE_ORIGIN = "https://robbottx.com"
EXPECTED_RAW_PREFIX = (
    "https://raw.githubusercontent.com/"
    "The-new-ben/robbottx-enterprise/"
)
ROBOTS_RELATIVE_PATH = "hosting/robots.txt"
OPS_RELATIVE_PATH = "scripts/deploy-wordpress-theme.py"
VERIFIER_RELATIVE_PATH = "scripts/deploy-wordpress.py"
ROUTE_TEMPLATE_RELATIVE_PATH = (
    "scripts/templates/deploy-robots-route.php.txt"
)
ROUTE_TEMPLATE_SHA256 = (
    "b19369e81eb235b314ed5b1e022d7e1e"
    "e38c8da24e893d1c3bd03189a0949dde"
)
VERIFIER_MODULE_NAME = "_robbottx_robots_boundary_verifier"
OPS_MODULE_NAME = "_robbottx_robots_wordpress_ops"
MAX_INDEX_MODULE_BYTES = 4 * 1024 * 1024
MAX_ROUTE_TEMPLATE_BYTES = 1024 * 1024
MAX_ROBOTS_BYTES = 64 * 1024
MAX_PUBLIC_RESPONSE_BYTES = 64 * 1024
MAX_TRUSTED_GIT_EXECUTABLE_BYTES = 128 * 1024 * 1024
MAX_TRUSTED_GIT_OUTPUT_BYTES = 128 * 1024 * 1024
TRUSTED_GIT_TIMEOUT_SECONDS = 60
MAX_CODE_SNIPPETS_RECORDS = 98
ROUTE_NAMESPACE_PREFIX = "/agentrobots"
USER_AGENT = "RobbottX-Agent-Robots-Deploy/0.1"

EVIDENCE_SCHEMA = {
    "artifact": {
        "bytes": None,
        "path": None,
        "sha256": None,
    },
    "authority_verified": None,
    "before": {
        "public_state": None,
    },
    "callback": {
        "confirmed": None,
        "created": None,
        "existing_exact": None,
    },
    "cleanup": {
        "attempted": None,
        "namespace_absent": None,
        "proven": None,
        "route_absent": None,
        "snippet_absent": None,
    },
    "execute": None,
    "failure_stage": None,
    "failure_type": None,
    "git_commit": None,
    "public": {
        "content_type": None,
        "exact_bytes": None,
        "status": None,
    },
    "recorded_at": None,
    "schema_version": None,
    "status": None,
    "temporary_surface": {
        "namespace_absent": None,
        "snippet_count": None,
        "snippet_limit": None,
        "snippet_name_absent": None,
    },
}


class DeployFailure(RuntimeError):
    """A redacted robots deployment failure."""


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


NO_REDIRECT_OPENER = urllib.request.build_opener(RejectRedirects())


@dataclass(frozen=True)
class ReleaseContext:
    git_head: str
    ops: types.ModuleType
    ops_payload_sha256: str
    receipt_body_sha256: str
    robots_payload: bytes
    route_template: str


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


def read_head_index_file(
    repository_root: Path,
    relative_path: str,
    *,
    max_bytes: int,
) -> tuple[bytes, str]:
    """Read a stage-zero index blob only when it exactly matches HEAD."""

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
            "Reviewed file is staged differently from the current HEAD."
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
            "Reviewed Git HEAD changed during boundary bootstrap."
        )
    return blob_result.stdout, head


def execute_index_module(
    payload: bytes,
    relative_path: str,
    module_name: str,
) -> types.ModuleType:
    module_path = REPOSITORY_ROOT.joinpath(
        *PurePosixPath(relative_path).parts
    )
    previous_module = sys.modules.get(module_name)
    had_previous_module = module_name in sys.modules
    try:
        module = types.ModuleType(module_name)
        module.__file__ = str(module_path)
        module.__package__ = None
        sys.modules[module_name] = module
        exec(
            compile(payload, str(module_path), "exec"),
            module.__dict__,
        )
        return module
    except Exception as error:
        raise DeployFailure(
            "Reviewed indexed Python module could not be loaded."
        ) from error
    finally:
        if had_previous_module:
            sys.modules[module_name] = previous_module
        else:
            sys.modules.pop(module_name, None)


def load_head_index_module(
    relative_path: str,
    module_name: str,
    *,
    max_bytes: int = MAX_INDEX_MODULE_BYTES,
) -> tuple[types.ModuleType, bytes, str]:
    payload, git_head = read_head_index_file(
        REPOSITORY_ROOT,
        relative_path,
        max_bytes=max_bytes,
    )
    return (
        execute_index_module(payload, relative_path, module_name),
        payload,
        git_head,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify and optionally create the reviewed root robots.txt."
        )
    )
    parser.add_argument("--commit", required=True)
    parser.add_argument("--robots-url", required=True)
    parser.add_argument("--robots-size", required=True, type=int)
    parser.add_argument("--robots-sha256", required=True)
    parser.add_argument(
        "--boundary-receipt",
        required=True,
        type=Path,
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="New durable JSON evidence path. Existing paths are refused.",
    )
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def validate_inputs(args: argparse.Namespace) -> None:
    if (
        not isinstance(args.commit, str)
        or re.fullmatch(r"[0-9a-f]{40}", args.commit) is None
    ):
        raise DeployFailure(
            "--commit must be a 40-character lowercase Git commit."
        )
    expected_url = (
        f"{EXPECTED_RAW_PREFIX}{args.commit}/{ROBOTS_RELATIVE_PATH}"
    )
    if args.robots_url != expected_url:
        raise DeployFailure(
            "--robots-url must be the immutable commit-pinned raw source."
        )
    parsed = urllib.parse.urlsplit(args.robots_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "raw.githubusercontent.com"
        or parsed.netloc != "raw.githubusercontent.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise DeployFailure("--robots-url is not a safe immutable URL.")
    if (
        type(args.robots_size) is not int
        or args.robots_size <= 0
        or args.robots_size > MAX_ROBOTS_BYTES
    ):
        raise DeployFailure("--robots-size is outside the safe range.")
    if (
        not isinstance(args.robots_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", args.robots_sha256) is None
    ):
        raise DeployFailure(
            "--robots-sha256 must be 64 lowercase hexadecimal characters."
        )
    if not isinstance(args.boundary_receipt, Path):
        raise DeployFailure("--boundary-receipt is required.")


def prepare_release_boundary(args: argparse.Namespace) -> ReleaseContext:
    """Freeze all executable and artifact bytes, then prove the current gate."""

    validate_inputs(args)
    verifier, _verifier_payload, verifier_head = load_head_index_module(
        VERIFIER_RELATIVE_PATH,
        VERIFIER_MODULE_NAME,
    )
    try:
        reader = getattr(verifier, "read_clean_index_file")
        scanner = getattr(verifier, "run_reviewed_boundary_scan")
        validator = getattr(verifier, "validate_boundary_receipt")
        if not all(callable(value) for value in (reader, scanner, validator)):
            raise AttributeError("boundary verifier entry point unavailable")

        ops_payload, ops_head = reader(
            REPOSITORY_ROOT,
            OPS_RELATIVE_PATH,
            max_bytes=MAX_INDEX_MODULE_BYTES,
        )
        template_payload, template_head = reader(
            REPOSITORY_ROOT,
            ROUTE_TEMPLATE_RELATIVE_PATH,
            max_bytes=MAX_ROUTE_TEMPLATE_BYTES,
        )
        robots_payload, robots_head = reader(
            REPOSITORY_ROOT,
            ROBOTS_RELATIVE_PATH,
            max_bytes=MAX_ROBOTS_BYTES,
        )
        if (
            not isinstance(ops_payload, bytes)
            or not isinstance(template_payload, bytes)
            or not isinstance(robots_payload, bytes)
            or {
                verifier_head,
                ops_head,
                template_head,
                robots_head,
                args.commit,
            }
            != {args.commit}
        ):
            raise DeployFailure(
                "Reviewed robots release inputs do not share one Git HEAD."
            )
        if (
            len(robots_payload) != args.robots_size
            or hashlib.sha256(robots_payload).hexdigest()
            != args.robots_sha256
        ):
            raise DeployFailure(
                "Indexed robots bytes do not match the reviewed artifact."
            )
        if (
            hashlib.sha256(template_payload).hexdigest()
            != ROUTE_TEMPLATE_SHA256
        ):
            raise DeployFailure(
                "Robots route template does not match the reviewed release."
            )
        try:
            route_template = template_payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise DeployFailure(
                "Robots route template is not valid UTF-8."
            ) from error

        scan_report = scanner(REPOSITORY_ROOT)
        public_snapshot_sha256 = getattr(
            scan_report,
            "public_snapshot_payload_sha256",
            None,
        )
        if (
            getattr(scan_report, "git_head", None) != args.commit
            or not isinstance(public_snapshot_sha256, str)
            or re.fullmatch(
                r"[0-9a-f]{64}",
                public_snapshot_sha256,
            )
            is None
        ):
            raise DeployFailure(
                "Current public-boundary scan did not retain the frozen release."
            )
        result = validator(
            args.boundary_receipt,
            version="robots",
            slug="hosting",
            zip_sha256=args.robots_sha256,
            record_hash=public_snapshot_sha256,
            artifact_path=ROBOTS_RELATIVE_PATH,
            repository_root=REPOSITORY_ROOT,
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
            "Robots public-boundary verification failed with "
            f"{type(error).__name__}."
        ) from error

    if (
        not isinstance(result, dict)
        or set(result)
        != {"artifact_path", "git_head", "receipt_body_sha256"}
        or result.get("artifact_path") != ROBOTS_RELATIVE_PATH
        or result.get("git_head") != args.commit
        or re.fullmatch(
            r"[0-9a-f]{64}",
            str(result.get("receipt_body_sha256", "")),
        )
        is None
    ):
        raise DeployFailure(
            "Robots public-boundary verifier returned an invalid proof."
        )

    ops = execute_index_module(
        ops_payload,
        OPS_RELATIVE_PATH,
        OPS_MODULE_NAME,
    )
    required_ops = (
        "DeployFailure",
        "cleanup_temporary_snippets",
        "make_auth",
        "make_route_token",
        "normalize_base_url",
        "request",
        "require_snippet_capacity",
        "require_snippet_name_absent",
        "required_env",
    )
    if any(not hasattr(ops, name) for name in required_ops):
        raise DeployFailure(
            "Reviewed shared WordPress operations are incomplete."
        )
    return ReleaseContext(
        git_head=args.commit,
        ops=ops,
        ops_payload_sha256=hashlib.sha256(ops_payload).hexdigest(),
        receipt_body_sha256=result["receipt_body_sha256"],
        robots_payload=robots_payload,
        route_template=route_template,
    )


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
    raise ValueError("unsupported JSON constant")


def _parse_json_float(value: str) -> float:
    if len(value) > 100:
        raise ValueError("JSON float is too large")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("JSON float is not finite")
    return parsed


def _parse_json_integer(value: str) -> int:
    if len(value) > 20 or re.fullmatch(r"-?(?:0|[1-9][0-9]*)", value) is None:
        raise ValueError("invalid JSON integer")
    return int(value)


def strict_json_loads(body: str) -> object:
    return json.loads(
        body,
        object_pairs_hook=_json_object_without_duplicate_keys,
        parse_constant=_reject_json_constant,
        parse_float=_parse_json_float,
        parse_int=_parse_json_integer,
    )


def is_json_content_type(content_type: str) -> bool:
    media_type = content_type.split(";", 1)[0].strip().lower()
    return media_type == "application/json" or media_type.endswith("+json")


def strict_json_object_response(
    status: int,
    content_type: str,
    body: str,
    context: str,
) -> dict[str, object]:
    if status < 200 or status >= 300:
        raise DeployFailure(f"{context} failed with HTTP {status}.")
    if not is_json_content_type(content_type):
        raise DeployFailure(f"{context} did not return WordPress JSON.")
    try:
        value = strict_json_loads(body)
    except (
        json.JSONDecodeError,
        RecursionError,
        UnicodeError,
        ValueError,
    ) as error:
        raise DeployFailure(f"{context} returned invalid JSON.") from error
    if not isinstance(value, dict):
        raise DeployFailure(
            f"{context} returned an unexpected JSON shape."
        )
    return value


def request_public_bytes(
    url: str,
    *,
    max_bytes: int = MAX_PUBLIC_RESPONSE_BYTES,
    timeout: int = 60,
) -> tuple[int, str, bytes]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/plain",
            "User-Agent": USER_AGENT,
        },
        method="GET",
    )
    try:
        with NO_REDIRECT_OPENER.open(request, timeout=timeout) as response:
            payload = response.read(max_bytes + 1)
            if len(payload) > max_bytes:
                raise DeployFailure(
                    "A public robots response exceeded the safe size limit."
                )
            return (
                response.status,
                response.headers.get("Content-Type", ""),
                payload,
            )
    except urllib.error.HTTPError as error:
        payload = error.read(max_bytes + 1)
        if len(payload) > max_bytes:
            raise DeployFailure(
                "A public robots error exceeded the safe size limit."
            )
        return (
            error.code,
            error.headers.get("Content-Type", ""),
            payload,
        )
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise DeployFailure(
            "A public robots request failed."
        ) from error


def _is_text_plain(content_type: str) -> bool:
    return (
        content_type.split(";", 1)[0].strip().lower()
        == "text/plain"
    )


def is_proxy_ambiguous_callback_response(
    status: int,
    content_type: str,
) -> bool:
    """Recognize narrow non-JSON responses that can obscure a completed write."""

    if type(status) is not int or not isinstance(content_type, str):
        return False
    media_type = content_type.split(";", 1)[0].strip().lower()
    return (
        status in {502, 503, 504, 520, 521, 522, 523, 524}
        and not is_json_content_type(content_type)
    ) or (
        status == 404
        and media_type == "text/html"
    )


def verify_raw_source(
    args: argparse.Namespace,
    frozen_payload: bytes,
) -> None:
    status, content_type, payload = request_public_bytes(
        args.robots_url,
        max_bytes=args.robots_size,
    )
    if (
        status != 200
        or not _is_text_plain(content_type)
        or len(payload) != args.robots_size
        or hashlib.sha256(payload).hexdigest() != args.robots_sha256
        or not secrets.compare_digest(payload, frozen_payload)
    ):
        raise DeployFailure(
            "The immutable public robots source did not match the release."
        )


def cache_busted_robots_url(base_url: str) -> str:
    nonce = f"{time.time_ns()}-{secrets.token_hex(8)}"
    return f"{base_url}/robots.txt?rbtxcb={nonce}"


def read_public_robots_state(
    base_url: str,
    args: argparse.Namespace,
    frozen_payload: bytes,
    *,
    allow_absent: bool,
) -> tuple[str, int, str]:
    status, content_type, payload = request_public_bytes(
        cache_busted_robots_url(base_url),
    )
    if allow_absent and status == 404:
        return "absent", status, content_type
    if (
        status == 200
        and _is_text_plain(content_type)
        and len(payload) == args.robots_size
        and hashlib.sha256(payload).hexdigest()
        == args.robots_sha256
        and secrets.compare_digest(payload, frozen_payload)
    ):
        return "exact", status, content_type
    raise DeployFailure(
        "The public root robots response did not match the reviewed bytes."
    )


def verify_authority(ops: types.ModuleType, base_url: str, auth: str) -> None:
    status, content_type, body = ops.request(
        (
            f"{base_url}/wp-json/wp/v2/users/me"
            "?context=edit&_fields=roles,capabilities"
        ),
        auth=auth,
        timeout=60,
    )
    identity = strict_json_object_response(
        status,
        content_type,
        body,
        "Application Password verification",
    )
    if set(identity) != {"roles", "capabilities"}:
        raise DeployFailure(
            "Authenticated WordPress identity had an unexpected shape."
        )
    roles = identity["roles"]
    capabilities = identity["capabilities"]
    if (
        not isinstance(roles, list)
        or any(not isinstance(role, str) for role in roles)
        or "administrator" not in roles
        or not isinstance(capabilities, dict)
        or capabilities.get("update_plugins") is not True
        or capabilities.get("manage_options") is not True
    ):
        raise DeployFailure(
            "Authenticated WordPress user lacks robots deployment authority."
        )


def read_route_inventory(
    ops: types.ModuleType,
    base_url: str,
) -> dict[str, object]:
    status, content_type, body = ops.request(
        f"{base_url}/wp-json/?rbtxcb={int(time.time())}",
        timeout=30,
    )
    index = strict_json_object_response(
        status,
        content_type,
        body,
        "WordPress REST route inventory",
    )
    routes = index.get("routes")
    if (
        not isinstance(routes, dict)
        or any(not isinstance(key, str) for key in routes)
    ):
        raise DeployFailure(
            "WordPress REST route inventory had an unexpected shape."
        )
    return routes


def require_robots_namespace_absent(
    ops: types.ModuleType,
    base_url: str,
) -> None:
    routes = read_route_inventory(ops, base_url)
    if any(
        route == ROUTE_NAMESPACE_PREFIX
        or route.startswith(f"{ROUTE_NAMESPACE_PREFIX}/")
        for route in routes
    ):
        raise DeployFailure(
            "The temporary robots REST namespace is already registered."
        )


def prove_robots_namespace_absent(
    ops: types.ModuleType,
    base_url: str,
) -> tuple[bool, list[str]]:
    try:
        require_robots_namespace_absent(ops, base_url)
        return True, []
    except Exception as error:
        return False, [
            "robots namespace proof raised "
            f"{type(error).__name__}"
        ]


def prove_route_absent(
    ops: types.ModuleType,
    base_url: str,
    auth: str,
    route_path: str,
    *,
    attempts: int = 3,
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    for attempt in range(1, attempts + 1):
        try:
            status, content_type, body = ops.request(
                f"{base_url}{route_path}",
                method="POST",
                auth=auth,
                payload={},
                timeout=30,
            )
            if not is_json_content_type(content_type):
                raise ValueError("route proof was not JSON")
            value = strict_json_loads(body)
            if (
                status == 404
                and isinstance(value, dict)
                and set(value) == {"code", "data", "message"}
                and value.get("code") == "rest_no_route"
                and isinstance(value.get("message"), str)
                and isinstance(value.get("data"), dict)
                and value["data"] == {"status": 404}
            ):
                return True, failures
            failures.append(
                f"route absence attempt {attempt} lacked exact rest_no_route"
            )
        except Exception as error:
            failures.append(
                f"route absence attempt {attempt} raised "
                f"{type(error).__name__}"
            )
        if attempt < attempts:
            time.sleep(attempt)
    return False, failures


def require_route_absent(
    ops: types.ModuleType,
    base_url: str,
    auth: str,
    route_path: str,
) -> None:
    absent, failures = prove_route_absent(
        ops,
        base_url,
        auth,
        route_path,
    )
    if not absent:
        raise DeployFailure(
            "Temporary robots route absence was not proven. "
            + "; ".join(failures)
        )


def build_route_code(
    *,
    route_template: str,
    route_token: str,
    robots_url: str,
    robots_size: int,
    robots_sha256: str,
) -> str:
    if (
        not isinstance(route_template, str)
        or hashlib.sha256(route_template.encode("utf-8")).hexdigest()
        != ROUTE_TEMPLATE_SHA256
    ):
        raise DeployFailure(
            "Robots route template does not match the frozen release."
        )
    if (
        re.fullmatch(
            r"robots-[1-9][0-9]{9,}-[0-9a-f]{32}",
            route_token,
        )
        is None
    ):
        raise DeployFailure(
            "Robots route token has an invalid release-bound shape."
        )
    route_code = route_template
    replacements = {
        "{{RAW_ROBOTS_URL_B64}}": base64.b64encode(
            robots_url.encode("utf-8")
        ).decode("ascii"),
        "{{ROBOTS_SHA256}}": robots_sha256,
        "{{ROBOTS_SIZE}}": str(robots_size),
        "{{ROUTE_TOKEN}}": route_token,
    }
    for placeholder, value in replacements.items():
        route_code = route_code.replace(placeholder, value)
    if "{{" in route_code or "}}" in route_code:
        raise DeployFailure(
            "Robots route template has unresolved placeholders."
        )
    required_fragments = (
        "current_user_can( 'update_plugins' )",
        "current_user_can( 'manage_options' )",
        "$target          = ABSPATH . 'robots.txt';",
        "@fopen( $temp, 'x+b' )",
        "@link( $temp, $target )",
        "'methods'             => 'GET'",
        "'methods'             => 'POST'",
    )
    forbidden_fragments = (
        "rename( $temp, $target",
        "unlink( $target",
        "file_put_contents( $target",
        "fopen( $target",
    )
    if any(fragment not in route_code for fragment in required_fragments):
        raise DeployFailure(
            "Robots route template lost a required safety control."
        )
    if any(fragment in route_code for fragment in forbidden_fragments):
        raise DeployFailure(
            "Robots route template contains an unsafe overwrite operation."
        )
    if robots_url in route_code:
        raise DeployFailure(
            "Robots route exposed the raw source URL instead of encoding it."
        )
    return route_code


def parse_created_snippet_id(
    status: int,
    content_type: str,
    body: str,
) -> int:
    created = strict_json_object_response(
        status,
        content_type,
        body,
        "Temporary robots route creation",
    )
    snippet_id = created.get("id")
    if (
        type(snippet_id) is not int
        or snippet_id <= 0
        or snippet_id > 2**63 - 1
    ):
        raise DeployFailure(
            "Temporary robots route creation returned no usable snippet ID."
        )
    return snippet_id


def confirm_exact_callback(
    status: int,
    content_type: str,
    body: str,
    args: argparse.Namespace,
) -> tuple[bool, bool]:
    callback = strict_json_object_response(
        status,
        content_type,
        body,
        "Robots deployment callback",
    )
    if (
        set(callback)
        != {
            "artifact_verified",
            "bytes",
            "cache_flush_sent",
            "created",
            "existing_exact",
            "result",
            "sha256",
            "temporary_files_absent",
        }
        or callback["result"] is not True
        or callback["artifact_verified"] is not True
        or callback["cache_flush_sent"] is not True
        or callback["temporary_files_absent"] is not True
        or type(callback["created"]) is not bool
        or type(callback["existing_exact"]) is not bool
        or callback["created"] is callback["existing_exact"]
        or type(callback["bytes"]) is not int
        or callback["bytes"] != args.robots_size
        or callback["sha256"] != args.robots_sha256
    ):
        raise DeployFailure(
            "Robots deployment callback did not confirm the exact artifact."
        )
    return callback["created"], callback["existing_exact"]


def confirm_exact_authenticated_state(
    status: int,
    content_type: str,
    body: str,
    args: argparse.Namespace,
) -> None:
    state = strict_json_object_response(
        status,
        content_type,
        body,
        "Authenticated robots state",
    )
    if (
        set(state)
        != {
            "bytes",
            "exists",
            "matches",
            "regular_file",
            "sha256",
            "temporary_files_absent",
        }
        or state["exists"] is not True
        or state["regular_file"] is not True
        or state["matches"] is not True
        or state["temporary_files_absent"] is not True
        or type(state["bytes"]) is not int
        or state["bytes"] != args.robots_size
        or state["sha256"] != args.robots_sha256
    ):
        raise DeployFailure(
            "Authenticated root robots state was not exact."
        )


def prepare_output_path(value: Path | str) -> Path:
    output_path = Path(value).expanduser().resolve()
    if output_path.exists() or output_path.is_symlink():
        raise DeployFailure("--output already exists; refusing to overwrite it.")
    if not output_path.parent.is_dir():
        raise DeployFailure("--output parent directory does not exist.")
    return output_path


def require_allowlisted_evidence(
    payload: dict[str, Any],
    schema: dict[str, Any] = EVIDENCE_SCHEMA,
    *,
    context: str = "evidence",
) -> None:
    if not isinstance(payload, dict) or set(payload).difference(schema):
        raise DeployFailure(
            f"Robots {context} contains a non-allowlisted field."
        )
    for key, value in payload.items():
        child_schema = schema[key]
        if isinstance(child_schema, dict):
            if not isinstance(value, dict):
                raise DeployFailure(
                    f"Robots {context} has an invalid nested shape."
                )
            require_allowlisted_evidence(
                value,
                child_schema,
                context=f"{context}.{key}",
            )
        elif isinstance(value, (dict, list, set, tuple)):
            raise DeployFailure(
                f"Robots {context} has an invalid field value."
            )


def write_new_evidence(output_path: Path, payload: dict[str, Any]) -> None:
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
            "Durable robots evidence could not be written."
        ) from error
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def release_context_matches(
    left: ReleaseContext,
    right: ReleaseContext,
) -> bool:
    return (
        left.git_head == right.git_head
        and left.ops_payload_sha256 == right.ops_payload_sha256
        and left.receipt_body_sha256 == right.receipt_body_sha256
        and secrets.compare_digest(
            left.robots_payload,
            right.robots_payload,
        )
        and secrets.compare_digest(
            left.route_template.encode("utf-8"),
            right.route_template.encode("utf-8"),
        )
    )


def _run_deployment(
    args: argparse.Namespace,
    evidence: dict[str, Any],
) -> None:
    evidence["failure_stage"] = "public_boundary"
    release = prepare_release_boundary(args)
    ops = release.ops
    evidence.update(
        {
            "artifact": {
                "bytes": args.robots_size,
                "path": ROBOTS_RELATIVE_PATH,
                "sha256": args.robots_sha256,
            },
            "git_commit": args.commit,
        }
    )

    evidence["failure_stage"] = "artifact_preflight"
    verify_raw_source(args, release.robots_payload)

    evidence["failure_stage"] = "runtime_authority"
    base_url = ops.normalize_base_url(ops.required_env("WP_BASE_URL"))
    user = ops.required_env("WP_USER")
    password = ops.required_env("WP_APP_PASSWORD")
    auth = ops.make_auth(user, password)
    verify_authority(ops, base_url, auth)
    evidence["authority_verified"] = True

    route_token = ops.make_route_token("robots")
    route_path = f"/wp-json/agentrobots/v1/run-{route_token}"
    snippet_name = f"tmp-robbottx-robots-deploy-{route_token}"

    evidence["failure_stage"] = "temporary_surface_preflight"
    require_robots_namespace_absent(ops, base_url)
    require_route_absent(
        ops,
        base_url,
        auth,
        route_path,
    )
    ops.require_snippet_name_absent(base_url, snippet_name, auth)
    snippet_count = ops.require_snippet_capacity(base_url, auth)
    evidence["temporary_surface"] = {
        "namespace_absent": True,
        "snippet_count": snippet_count,
        "snippet_limit": MAX_CODE_SNIPPETS_RECORDS,
        "snippet_name_absent": True,
    }

    evidence["failure_stage"] = "before_state"
    before_state, _, _ = read_public_robots_state(
        base_url,
        args,
        release.robots_payload,
        allow_absent=True,
    )
    evidence["before"] = {"public_state": before_state}

    if not args.execute:
        evidence.pop("failure_stage", None)
        evidence["cleanup"] = {
            "attempted": False,
            "namespace_absent": True,
            "proven": True,
            "route_absent": True,
            "snippet_absent": True,
        }
        evidence["status"] = "preflight_ok"
        return

    route_code = build_route_code(
        route_template=release.route_template,
        route_token=route_token,
        robots_url=args.robots_url,
        robots_size=args.robots_size,
        robots_sha256=args.robots_sha256,
    )
    snippet_id: int | None = None
    callback_confirmed = False
    callback_created: bool | None = None
    callback_existing: bool | None = None
    failure: Exception | None = None
    failure_stage = "action_boundary"

    try:
        evidence["failure_stage"] = failure_stage
        action_release = prepare_release_boundary(args)
        if not release_context_matches(release, action_release):
            raise DeployFailure(
                "Robots release boundary changed before the mutation."
            )

        failure_stage = "temporary_route_creation"
        evidence["failure_stage"] = failure_stage
        status, content_type, body = ops.request(
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
        snippet_id = parse_created_snippet_id(
            status,
            content_type,
            body,
        )

        failure_stage = "deployment_callback"
        evidence["failure_stage"] = failure_stage
        evidence["callback"] = {
            "confirmed": False,
            "created": None,
            "existing_exact": None,
        }
        try:
            status, content_type, body = ops.request(
                f"{base_url}{route_path}",
                method="POST",
                auth=auth,
                payload={},
                timeout=120,
            )
        except Exception:
            # A transport failure can discard the callback response after the
            # server has acted. Only the independent exact GET proofs below
            # may recover this otherwise ambiguous outcome.
            callback_confirmed = False
        else:
            if not is_proxy_ambiguous_callback_response(
                status,
                content_type,
            ):
                (
                    callback_created,
                    callback_existing,
                ) = confirm_exact_callback(
                    status,
                    content_type,
                    body,
                    args,
                )
                callback_confirmed = True
        evidence["callback"] = {
            "confirmed": callback_confirmed,
            "created": callback_created,
            "existing_exact": callback_existing,
        }

        failure_stage = "authenticated_state"
        evidence["failure_stage"] = failure_stage
        status, content_type, body = ops.request(
            f"{base_url}{route_path}",
            method="GET",
            auth=auth,
            timeout=60,
        )
        confirm_exact_authenticated_state(
            status,
            content_type,
            body,
            args,
        )

        failure_stage = "public_verification"
        evidence["failure_stage"] = failure_stage
        _, public_status, public_content_type = read_public_robots_state(
            base_url,
            args,
            release.robots_payload,
            allow_absent=False,
        )
        evidence["public"] = {
            "content_type": (
                public_content_type.split(";", 1)[0].strip().lower()
            ),
            "exact_bytes": True,
            "status": public_status,
        }
    except Exception as error:
        failure = error
        evidence["failure_stage"] = failure_stage
    finally:
        cleanup_failures: list[str] = []
        snippet_absent = False
        route_absent = False
        namespace_absent = False
        try:
            snippet_absent, snippet_failures = (
                ops.cleanup_temporary_snippets(
                    base_url,
                    auth,
                    snippet_name,
                    snippet_id,
                )
            )
            cleanup_failures.extend(snippet_failures)
        except Exception as error:
            cleanup_failures.append(
                "snippet cleanup raised "
                f"{type(error).__name__}"
            )

        try:
            route_absent, route_failures = prove_route_absent(
                ops,
                base_url,
                auth,
                route_path,
            )
            cleanup_failures.extend(route_failures)
        except Exception as error:
            cleanup_failures.append(
                "route cleanup proof raised "
                f"{type(error).__name__}"
            )

        try:
            namespace_absent, namespace_failures = (
                prove_robots_namespace_absent(ops, base_url)
            )
            cleanup_failures.extend(namespace_failures)
        except Exception as error:
            cleanup_failures.append(
                "namespace cleanup proof raised "
                f"{type(error).__name__}"
            )

        cleanup_proven = (
            snippet_absent
            and route_absent
            and namespace_absent
        )
        evidence["cleanup"] = {
            "attempted": True,
            "namespace_absent": namespace_absent,
            "proven": cleanup_proven,
            "route_absent": route_absent,
            "snippet_absent": snippet_absent,
        }
        if not cleanup_proven:
            message = "Temporary robots route cleanup was not proven."
            if cleanup_failures:
                message += " " + "; ".join(cleanup_failures) + "."
            if failure is None:
                failure = DeployFailure(message)
                evidence["failure_stage"] = "cleanup"
            else:
                failure = DeployFailure(
                    "Robots deployment failed with "
                    f"{type(failure).__name__}. {message}"
                )

    if failure is not None:
        if isinstance(failure, DeployFailure):
            raise failure
        raise DeployFailure(
            "Robots deployment failed with "
            f"{type(failure).__name__}."
        ) from failure

    evidence.pop("failure_stage", None)
    evidence["status"] = "deployed"


def main() -> int:
    args = parse_args()
    output_path = prepare_output_path(args.output)
    evidence: dict[str, Any] = {
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
        evidence.setdefault(
            "cleanup",
            {
                "attempted": False,
                "namespace_absent": evidence.get(
                    "temporary_surface",
                    {},
                ).get("namespace_absent"),
                "proven": False,
                "route_absent": None,
                "snippet_absent": None,
            },
        )
        require_allowlisted_evidence(evidence)
        write_new_evidence(output_path, evidence)
        emit(evidence)
        if isinstance(error, DeployFailure):
            raise
        raise DeployFailure(
            "Robots deployment failed with "
            f"{type(error).__name__}."
        ) from error

    require_allowlisted_evidence(evidence)
    write_new_evidence(output_path, evidence)
    emit(evidence)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except DeployFailure as error:
        print(f"Robots deployment failed: {error}", file=sys.stderr)
        sys.exit(1)
