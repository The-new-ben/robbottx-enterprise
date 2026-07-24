#!/usr/bin/env python3
"""Fail closed when private engineering material reaches the public repository."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import re
import stat
import struct
import subprocess
import sys
import unicodedata
import zipfile
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


REQUIRED_DIRECTORIES = (
    "governance",
    "packages/publication",
    "plugin-dist",
    "scripts",
    "tests",
    "wp-content",
)

REQUIRED_FILES = (
    ".gitignore",
    "AGENTS.md",
    "package.json",
    "governance/PUBLIC-ASSET-DISCLOSURE.json",
    "packages/publication/golden-slice.v0.json",
)

ASSET_MANIFEST_PATH = "governance/PUBLIC-ASSET-DISCLOSURE.json"
PUBLIC_SNAPSHOT_PATH = "packages/publication/golden-slice.v0.json"
ROOT_RELEASE_ARTIFACT_PATHS = frozenset({"hosting/robots.txt"})

FALLBACK_EXCLUDED_PARTS = {
    ".artifacts",
    ".cache",
    ".git",
    ".playwright-cli",
    ".wp-env",
    "__pycache__",
    "dist",
    "node_modules",
    "vendor",
    "work",
}

NATIVE_ENGINEERING_EXTENSIONS = {
    ".3dm",
    ".bag",
    ".blend",
    ".cad",
    ".db",
    ".dump",
    ".dwg",
    ".dxf",
    ".fcstd",
    ".iges",
    ".igs",
    ".mat",
    ".mcap",
    ".npy",
    ".npz",
    ".onnx",
    ".parquet",
    ".pth",
    ".safetensors",
    ".sdf",
    ".sldasm",
    ".sldprt",
    ".sql",
    ".sqlite",
    ".step",
    ".stl",
    ".stp",
    ".tar",
    ".urdf",
    ".usd",
    ".usda",
    ".usdc",
    ".xacro",
}

PUBLIC_3D_DERIVATIVE_EXTENSIONS = {
    ".glb",
}

DISALLOWED_STRUCTURED_EXTENSIONS = {
    ".yaml",
    ".yml",
}

NESTED_ARCHIVE_EXTENSIONS = {
    ".7z",
    ".bz2",
    ".gz",
    ".rar",
    ".tar",
    ".tgz",
    ".xz",
    ".zip",
}

TEXT_EXTENSIONS = {
    "",
    ".css",
    ".csv",
    ".html",
    ".htm",
    ".ini",
    ".js",
    ".json",
    ".lock",
    ".md",
    ".mjs",
    ".php",
    ".po",
    ".pot",
    ".py",
    ".svg",
    ".toml",
    ".txt",
    ".xml",
}

PUBLIC_BINARY_EXTENSIONS = {
    ".gif",
    ".jpeg",
    ".jpg",
    ".mo",
    ".png",
    ".webp",
    ".woff",
    ".woff2",
}

PRIVATE_CLASSIFICATIONS = {
    "confidential" + "_" + "proprietary",
    "private" + "_" + "working",
}

FORBIDDEN_FIELD_KEYS = {
    "automatic" + "_" + "export" + "_" + "allowed",
    "human" + "_" + "testing" + "_" + "authorized",
    "motion" + "_" + "authorized",
    "private" + "_" + "object" + "_" + "path",
}

FORBIDDEN_RECORD_TYPES = {
    "calculation",
    "ebom",
    "hazards",
    "raw_test",
    "simulation",
    "supplier_cost",
    "test_result",
    "threat_model",
    "verification_plan",
}

PRIVATE_PATH_MARKERS = {
    "private" + "-objects",
    "private" + "_objects",
    "proprietary" + "-engineering",
    "proprietary" + "_engineering",
    "raw" + "-tests",
    "raw" + "_tests",
}

PRIVATE_SYSTEM_ID_PATTERN = re.compile(
    r"\bRBTX-(?:RS|RP)-[0-9]{3}(?:-[A-Z0-9]+)?\b",
    re.IGNORECASE,
)

PRIVATE_RECORD_ID_PATTERN = re.compile(
    r"\bRBTX:[A-Z0-9]+:RS[0-9]+[A-Z0-9._:-]*\b",
    re.IGNORECASE,
)

PRIVATE_SYSTEM_ID_BINARY_PATTERN = re.compile(
    r"RBTX-(?:RS|RP)-[0-9]{3}",
    re.IGNORECASE,
)

PRIVATE_RECORD_ID_BINARY_PATTERN = re.compile(
    r"RBTX:[A-Z0-9]+:RS[0-9]+",
    re.IGNORECASE,
)

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
GIT_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
MAX_TEXT_BYTES = 4 * 1024 * 1024
MAX_BINARY_BYTES = 32 * 1024 * 1024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_REPOSITORY_FILE_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 5_000
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_COMPRESSION_RATIO = 500
MAX_ASSET_MANIFEST_BYTES = MAX_TEXT_BYTES
MAX_PUBLIC_SNAPSHOT_BYTES = MAX_TEXT_BYTES
MAX_TRUSTED_GIT_EXECUTABLE_BYTES = 128 * 1024 * 1024
MAX_TRUSTED_GIT_OUTPUT_BYTES = 128 * 1024 * 1024
TRUSTED_GIT_TIMEOUT_SECONDS = 60
TRUSTED_GIT_SUBCOMMANDS = {
    "cat-file",
    "check-ignore",
    "ls-files",
    "rev-parse",
    "status",
}


@dataclass(frozen=True)
class Finding:
    location: str
    reason: str


@dataclass(frozen=True)
class AssetApproval:
    path: str
    paired_asset_path: str
    sha256: str
    bytes: int
    asset_class: str
    rights_status: str
    disclosure_status: str
    approval_id: str
    public_revision: str


@dataclass(frozen=True)
class ScanReport:
    findings: tuple[Finding, ...]
    files_scanned: int
    archives_scanned: int
    repository_content_sha256: str
    git_index_content_sha256: str | None
    worktree_content_sha256: str
    release_artifacts: tuple[tuple[str, str], ...]
    asset_manifest_sha256: str | None
    public_snapshot_payload_sha256: str | None
    git_head: str | None
    git_dirty: bool | None


@dataclass(frozen=True)
class PublicObject:
    location: str
    receipt_path: str
    payload: bytes
    layer: str


class DuplicateJsonKeyError(ValueError):
    """Raised when a JSON object repeats a decoded key."""


class NonFiniteJsonNumberError(ValueError):
    """Raised when JSON contains NaN or either infinity token."""


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
    raise OSError("no protected absolute Git executable is available")


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


def run_git(
    root: Path,
    arguments: list[str],
    *,
    text: bool = False,
) -> subprocess.CompletedProcess:
    if (
        not arguments
        or len(arguments) > 13
        or arguments[0] not in TRUSTED_GIT_SUBCOMMANDS
        or any(
            not isinstance(argument, str)
            or "\x00" in argument
            or len(argument) > 32_768
            for argument in arguments
        )
    ):
        raise OSError("unreviewed Git invocation")
    resolved_root = Path(root).resolve(strict=True)
    git_executable = resolve_trusted_git_executable()
    result = subprocess.run(
        [
            str(git_executable),
            "-C",
            str(resolved_root),
            *arguments,
        ],
        check=False,
        capture_output=True,
        text=text,
        timeout=TRUSTED_GIT_TIMEOUT_SECONDS,
        env=_trusted_git_environment(git_executable),
    )
    for stream in (result.stdout, result.stderr):
        if (
            isinstance(stream, (bytes, str))
            and len(stream) > MAX_TRUSTED_GIT_OUTPUT_BYTES
        ):
            raise OSError("Git output exceeded the boundary verification limit")
    return result


def reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise DuplicateJsonKeyError(f"duplicate JSON object key: {key}")
        value[key] = child
    return value


def reject_nonfinite_json_number(value: str) -> Any:
    raise NonFiniteJsonNumberError(f"non-finite JSON number: {value}")


def parse_finite_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise NonFiniteJsonNumberError(f"non-finite JSON number: {value}")
    return parsed


def strict_json_loads(value: str) -> Any:
    return json.loads(
        value,
        object_pairs_hook=reject_duplicate_json_keys,
        parse_constant=reject_nonfinite_json_number,
        parse_float=parse_finite_json_float,
    )


def json_parse_finding(location: str, subject: str, error: ValueError) -> Finding:
    if isinstance(error, DuplicateJsonKeyError):
        return Finding(location, f"{subject} has a duplicate object key")
    if isinstance(error, NonFiniteJsonNumberError):
        return Finding(location, f"{subject} contains a non-finite number")
    return Finding(location, f"{subject} is invalid JSON")


def read_bounded_regular_file(
    path: Path,
    location: str,
    *,
    limit: int,
    subject: str,
) -> tuple[bytes | None, list[Finding]]:
    try:
        metadata = path.lstat()
    except OSError:
        return None, [Finding(location, f"{subject} could not be inspected")]
    if stat.S_ISLNK(metadata.st_mode):
        return None, [Finding(location, f"{subject} must not be a symlink")]
    if not stat.S_ISREG(metadata.st_mode):
        return None, [Finding(location, f"{subject} is not a regular file")]
    if metadata.st_size > limit:
        return None, [Finding(location, f"{subject} exceeds bounded read limit")]
    try:
        with path.open("rb") as handle:
            payload = handle.read(limit + 1)
    except OSError:
        return None, [Finding(location, f"{subject} could not be read")]
    if len(payload) > limit:
        return None, [Finding(location, f"{subject} exceeds bounded read limit")]
    return payload, []


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def normalized_zip_member(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/")
    member = PurePosixPath(normalized)
    if (
        not normalized
        or normalized.startswith("/")
        or re.match(r"^[A-Za-z]:", normalized)
        or ".." in member.parts
        or "." in member.parts
    ):
        raise ValueError(f"unsafe archive member path: {name}")
    return member


def normalize_public_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    member = PurePosixPath(normalized)
    if (
        not normalized
        or normalized.startswith("/")
        or re.match(r"^[A-Za-z]:", normalized)
        or ".." in member.parts
        or "." in member.parts
    ):
        raise ValueError(f"unsafe public path: {value}")
    return member.as_posix()


def normalize_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def decode_text(payload: bytes) -> str | None:
    if payload.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        try:
            return payload.decode("utf-32")
        except UnicodeDecodeError:
            return None
    if payload.startswith(b"\xef\xbb\xbf"):
        try:
            return payload.decode("utf-8-sig")
        except UnicodeDecodeError:
            return None
    if payload.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return payload.decode("utf-16")
        except UnicodeDecodeError:
            return None

    if b"\x00" in payload:
        if len(payload) % 4 == 0 and payload:
            lanes = [
                payload[index::4].count(0) / max(1, len(payload[index::4]))
                for index in range(4)
            ]
            if min(lanes[1:]) > 0.55:
                try:
                    return payload.decode("utf-32-le")
                except UnicodeDecodeError:
                    return None
            if min(lanes[:3]) > 0.55:
                try:
                    return payload.decode("utf-32-be")
                except UnicodeDecodeError:
                    return None
        if len(payload) % 2 == 0 and payload:
            even_zero = payload[0::2].count(0) / max(1, len(payload[0::2]))
            odd_zero = payload[1::2].count(0) / max(1, len(payload[1::2]))
            encoding = None
            if odd_zero > 0.30 and odd_zero > (even_zero * 2):
                encoding = "utf-16-le"
            elif even_zero > 0.30 and even_zero > (odd_zero * 2):
                encoding = "utf-16-be"
            if encoding:
                try:
                    return payload.decode(encoding)
                except UnicodeDecodeError:
                    return None
        return None

    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return None


def scan_binary_payload(payload: bytes, location: str) -> list[Finding]:
    projections = [
        payload.decode("latin-1", errors="ignore"),
        payload[0::2].decode("latin-1", errors="ignore"),
        payload[1::2].decode("latin-1", errors="ignore"),
        payload[0::4].decode("latin-1", errors="ignore"),
        payload[1::4].decode("latin-1", errors="ignore"),
        payload[2::4].decode("latin-1", errors="ignore"),
        payload[3::4].decode("latin-1", errors="ignore"),
    ]
    findings: list[Finding] = []
    for projection in projections:
        findings.extend(scan_text(projection, location, structured=False))
        if PRIVATE_SYSTEM_ID_BINARY_PATTERN.search(projection):
            findings.append(
                Finding(location, "private reference-system identifier")
            )
        if PRIVATE_RECORD_ID_BINARY_PATTERN.search(projection):
            findings.append(
                Finding(location, "private engineering-record identifier")
            )
    return deduplicate_findings(findings)


def walk_json(value: Any, location: str, findings: list[Finding]) -> None:
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = re.sub(r"[-\s]+", "_", normalize_text(str(raw_key)))
            if key in FORBIDDEN_FIELD_KEYS:
                findings.append(Finding(location, f"private field {key}"))
            if key in {"classification", "publication_state", "review_state"}:
                child_state = (
                    re.sub(r"[-\s]+", "_", normalize_text(child))
                    if isinstance(child, str)
                    else ""
                )
                if child_state in PRIVATE_CLASSIFICATIONS:
                    findings.append(Finding(location, "private classification or state"))
            if key == "record_type" and isinstance(child, str):
                record_type = re.sub(r"[-\s]+", "_", normalize_text(child))
                if record_type in FORBIDDEN_RECORD_TYPES:
                    findings.append(
                        Finding(location, f"private record type {record_type}")
                    )
            walk_json(child, location, findings)
    elif isinstance(value, list):
        for child in value:
            walk_json(child, location, findings)
    elif isinstance(value, str):
        findings.extend(scan_text(value, location, structured=False))


def scan_text(
    text: str,
    location: str,
    *,
    structured: bool = True,
) -> list[Finding]:
    normalized = normalize_text(text)
    separator_normalized = re.sub(r"[-\s]+", "_", normalized)
    identifier_text = unicodedata.normalize("NFKC", text)
    findings: list[Finding] = []

    for classification in PRIVATE_CLASSIFICATIONS:
        if classification in separator_normalized:
            findings.append(Finding(location, "private classification or state"))

    if PRIVATE_SYSTEM_ID_PATTERN.search(identifier_text):
        findings.append(Finding(location, "private reference-system identifier"))
    if PRIVATE_RECORD_ID_PATTERN.search(identifier_text):
        findings.append(Finding(location, "private engineering-record identifier"))

    for marker in PRIVATE_PATH_MARKERS:
        if marker in separator_normalized:
            findings.append(Finding(location, "private object or evidence path"))

    if structured:
        for key in FORBIDDEN_FIELD_KEYS:
            flexible_key = r"[-_\s]+".join(
                re.escape(part) for part in key.split("_")
            )
            if re.search(
                rf"(?im)(?:^|[\s{{,])['\"]?{flexible_key}['\"]?\s*:",
                normalized,
            ):
                findings.append(Finding(location, f"private field {key}"))

        record_types = "|".join(
            r"[-_\s]+".join(re.escape(part) for part in value.split("_"))
            for value in sorted(FORBIDDEN_RECORD_TYPES)
        )
        if re.search(
            rf"(?im)(?:^|[\s{{,])['\"]?record[-_\s]+type['\"]?\s*:\s*"
            rf"['\"]?(?:{record_types})\b",
            normalized,
        ):
            findings.append(Finding(location, "private engineering record"))

    return findings


def deduplicate_findings(findings: list[Finding]) -> list[Finding]:
    return sorted(
        set(findings),
        key=lambda item: (item.location, item.reason),
    )


def scan_payload(
    payload: bytes,
    location: str,
    *,
    suffix: str = "",
) -> list[Finding]:
    findings: list[Finding] = []
    text = decode_text(payload)
    if text is not None:
        findings.extend(scan_text(text, location))
        if suffix in {".json", ".gltf"}:
            try:
                document = strict_json_loads(text)
            except (
                DuplicateJsonKeyError,
                NonFiniteJsonNumberError,
                json.JSONDecodeError,
            ) as exc:
                findings.append(
                    json_parse_finding(
                        location,
                        f"{suffix[1:].upper()} document",
                        exc,
                    )
                )
            else:
                walk_json(document, location, findings)
    else:
        ascii_projection = payload.replace(b"\x00", b"").decode(
            "latin-1",
            errors="ignore",
        )
        findings.extend(scan_text(ascii_projection, location, structured=False))
    return deduplicate_findings(findings)


def scan_location(location: str) -> list[Finding]:
    return scan_text(location, location, structured=False)


def validate_png(payload: bytes) -> str | None:
    signature = b"\x89PNG\r\n\x1a\n"
    if not payload.startswith(signature):
        return "PNG signature is invalid"
    offset = len(signature)
    saw_header = False
    saw_end = False
    while offset + 12 <= len(payload):
        length = struct.unpack(">I", payload[offset : offset + 4])[0]
        chunk_type = payload[offset + 4 : offset + 8]
        chunk_end = offset + 12 + length
        if chunk_end > len(payload):
            return "PNG chunk exceeds file bounds"
        chunk_data = payload[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", payload[offset + 8 + length : chunk_end])[0]
        actual_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        if expected_crc != actual_crc:
            return "PNG chunk checksum is invalid"
        if not saw_header:
            if chunk_type != b"IHDR":
                return "PNG first chunk is not IHDR"
            saw_header = True
        if chunk_type == b"IEND":
            saw_end = True
            if chunk_end != len(payload):
                return "PNG contains trailing data"
            break
        offset = chunk_end
    if not saw_header or not saw_end:
        return "PNG is incomplete"
    return None


def validate_public_binary(payload: bytes, suffix: str) -> str | None:
    if suffix == ".png":
        return validate_png(payload)
    if suffix in {".jpg", ".jpeg"}:
        if not (payload.startswith(b"\xff\xd8") and payload.endswith(b"\xff\xd9")):
            return "JPEG structure is invalid"
    elif suffix == ".gif":
        if not payload.startswith((b"GIF87a", b"GIF89a")):
            return "GIF signature is invalid"
    elif suffix == ".webp":
        if not (
            len(payload) >= 12
            and payload.startswith(b"RIFF")
            and payload[8:12] == b"WEBP"
        ):
            return "WebP signature is invalid"
    elif suffix == ".mo":
        if payload[:4] not in {b"\xde\x12\x04\x95", b"\x95\x04\x12\xde"}:
            return "GNU MO signature is invalid"
    elif suffix == ".woff":
        if not payload.startswith(b"wOFF"):
            return "WOFF signature is invalid"
    elif suffix == ".woff2":
        if not payload.startswith(b"wOF2"):
            return "WOFF2 signature is invalid"
    return None


def find_json_key(value: Any, key: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        for child_key, child in value.items():
            if child_key == key:
                found.append(child)
            found.extend(find_json_key(child, key))
    elif isinstance(value, list):
        for child in value:
            found.extend(find_json_key(child, key))
    return found


def validate_glb(payload: bytes, location: str) -> list[Finding]:
    findings: list[Finding] = []
    if len(payload) < 12 or payload[:4] != b"glTF":
        return [Finding(location, "GLB signature is invalid")]
    version, declared_length = struct.unpack("<II", payload[4:12])
    if version != 2:
        findings.append(Finding(location, "GLB version must be 2"))
    if declared_length != len(payload):
        findings.append(
            Finding(location, "GLB declared length does not match file size")
        )
        return findings

    offset = 12
    chunks: list[tuple[int, bytes]] = []
    while offset < len(payload):
        if offset + 8 > len(payload):
            findings.append(Finding(location, "GLB chunk header is truncated"))
            return findings
        chunk_length, chunk_type = struct.unpack("<II", payload[offset : offset + 8])
        chunk_end = offset + 8 + chunk_length
        if chunk_length % 4 != 0 or chunk_end > len(payload):
            findings.append(Finding(location, "GLB chunk bounds or alignment are invalid"))
            return findings
        chunks.append((chunk_type, payload[offset + 8 : chunk_end]))
        offset = chunk_end

    json_type = 0x4E4F534A
    bin_type = 0x004E4942
    if not chunks or chunks[0][0] != json_type:
        findings.append(Finding(location, "GLB first chunk must be JSON"))
        return findings
    if len(chunks) > 2 or any(
        chunk_type not in {json_type, bin_type}
        for chunk_type, _ in chunks
    ):
        findings.append(Finding(location, "GLB contains unsupported chunks"))
    if len(chunks) == 2 and chunks[1][0] != bin_type:
        findings.append(Finding(location, "GLB second chunk must be BIN"))

    for chunk_index, (chunk_type, chunk_payload) in enumerate(chunks):
        if chunk_type == bin_type:
            findings.extend(
                scan_binary_payload(
                    chunk_payload,
                    f"{location}!/BIN[{chunk_index}]",
                )
            )

    json_bytes = chunks[0][1].rstrip(b" \t\r\n\x00")
    try:
        json_text = json_bytes.decode("utf-8")
    except UnicodeDecodeError:
        findings.append(Finding(location, "GLB JSON chunk is invalid"))
        return deduplicate_findings(findings)
    try:
        document = strict_json_loads(json_text)
    except (
        DuplicateJsonKeyError,
        NonFiniteJsonNumberError,
        json.JSONDecodeError,
    ) as exc:
        findings.append(json_parse_finding(location, "GLB JSON chunk", exc))
        return deduplicate_findings(findings)

    findings.extend(scan_text(json_text, location))
    walk_json(document, location, findings)
    if (
        not isinstance(document, dict)
        or not isinstance(document.get("asset"), dict)
        or document["asset"].get("version") != "2.0"
    ):
        findings.append(Finding(location, "GLB asset version is not 2.0"))
    if find_json_key(document, "uri"):
        findings.append(
            Finding(location, "GLB must be self-contained and cannot reference URIs")
        )
    return deduplicate_findings(findings)


def asset_approval_findings(
    payload: bytes,
    location: str,
    approval: AssetApproval | None,
    expected_class: str,
    consumed_approvals: set[str],
) -> list[Finding]:
    if approval is None:
        return [Finding(location, f"{expected_class} lacks disclosure approval")]
    consumed_approvals.add(approval.path)
    findings: list[Finding] = []
    if approval.asset_class != expected_class:
        findings.append(Finding(location, "asset approval class does not match use"))
    if approval.bytes != len(payload):
        findings.append(Finding(location, "asset byte size differs from approval"))
    if approval.sha256 != sha256_bytes(payload):
        findings.append(Finding(location, "asset hash differs from approval"))
    return findings


def parse_asset_manifest_payload(
    payload: bytes,
    location: str,
) -> tuple[dict[str, AssetApproval], list[Finding], str | None]:
    if len(payload) > MAX_ASSET_MANIFEST_BYTES:
        return (
            {},
            [Finding(location, "asset disclosure manifest exceeds bounded read limit")],
            None,
        )
    digest = sha256_bytes(payload)
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return (
            {},
            [Finding(location, "asset disclosure manifest is invalid JSON")],
            digest,
        )
    try:
        document = strict_json_loads(text)
    except (
        DuplicateJsonKeyError,
        NonFiniteJsonNumberError,
        json.JSONDecodeError,
    ) as exc:
        return {}, [json_parse_finding(location, "asset disclosure manifest", exc)], digest

    findings: list[Finding] = []
    approvals: dict[str, AssetApproval] = {}
    if not isinstance(document, dict) or set(document) != {"schema_version", "assets"}:
        findings.append(
            Finding(location, "asset manifest root fields are invalid")
        )
        return approvals, findings, digest
    if document.get("schema_version") != 2 or not isinstance(document.get("assets"), list):
        findings.append(
            Finding(location, "asset manifest version or assets are invalid")
        )
        return approvals, findings, digest

    expected_fields = {
        "approval_id",
        "asset_class",
        "bytes",
        "disclosure_status",
        "paired_asset_path",
        "path",
        "public_revision",
        "rights_status",
        "sha256",
    }
    item_locations: dict[str, str] = {}
    for index, item in enumerate(document["assets"]):
        item_location = f"{location}#/assets/{index}"
        if not isinstance(item, dict) or set(item) != expected_fields:
            findings.append(Finding(item_location, "asset approval fields are invalid"))
            continue
        if not isinstance(item["path"], str) or not isinstance(
            item["paired_asset_path"],
            str,
        ):
            findings.append(Finding(item_location, "asset relationship paths are invalid"))
            continue
        try:
            public_path = normalize_public_path(item["path"])
            paired_asset_path = normalize_public_path(item["paired_asset_path"])
        except ValueError as exc:
            findings.append(Finding(item_location, str(exc)))
            continue
        approval = AssetApproval(
            path=public_path,
            paired_asset_path=paired_asset_path,
            sha256=str(item["sha256"]).lower(),
            bytes=(
                item["bytes"]
                if isinstance(item["bytes"], int) and not isinstance(item["bytes"], bool)
                else -1
            ),
            asset_class=str(item["asset_class"]),
            rights_status=str(item["rights_status"]),
            disclosure_status=str(item["disclosure_status"]),
            approval_id=str(item["approval_id"]),
            public_revision=str(item["public_revision"]),
        )
        if public_path in approvals:
            findings.append(Finding(item_location, "duplicate approved asset path"))
            continue
        if paired_asset_path == public_path:
            findings.append(Finding(item_location, "asset cannot be paired with itself"))
        if not SHA256_PATTERN.fullmatch(approval.sha256):
            findings.append(Finding(item_location, "asset SHA-256 is invalid"))
        if approval.bytes < 0:
            findings.append(Finding(item_location, "asset byte size is invalid"))
        if approval.asset_class not in {
            "public_3d_derivative",
            "public_3d_fallback",
        }:
            findings.append(Finding(item_location, "asset class is not approved"))
        suffix = PurePosixPath(public_path.split("!/", 1)[-1]).suffix.lower()
        if (
            approval.asset_class == "public_3d_derivative"
            and suffix != ".glb"
        ):
            findings.append(
                Finding(item_location, "3D derivative approval must reference GLB")
            )
        if (
            approval.asset_class == "public_3d_fallback"
            and suffix not in {".png", ".jpg", ".jpeg", ".webp"}
        ):
            findings.append(
                Finding(item_location, "3D fallback approval must reference a static image")
            )
        if approval.rights_status != "approved":
            findings.append(Finding(item_location, "asset rights are not approved"))
        if approval.disclosure_status != "approved_for_public_release":
            findings.append(Finding(item_location, "asset disclosure is not approved"))
        if not approval.approval_id.strip() or not approval.public_revision.strip():
            findings.append(Finding(item_location, "asset approval identity is incomplete"))
        approvals[public_path] = approval
        item_locations[public_path] = item_location

    for public_path, approval in approvals.items():
        item_location = item_locations[public_path]
        paired = approvals.get(approval.paired_asset_path)
        if paired is None:
            findings.append(
                Finding(item_location, "paired public asset approval is missing")
            )
            continue
        expected_pair_class = (
            "public_3d_fallback"
            if approval.asset_class == "public_3d_derivative"
            else "public_3d_derivative"
        )
        if paired.asset_class != expected_pair_class:
            findings.append(
                Finding(item_location, "paired public asset class is invalid")
            )
        if paired.paired_asset_path != public_path:
            findings.append(
                Finding(item_location, "public asset relationship is not reciprocal")
            )
        if paired.public_revision != approval.public_revision:
            findings.append(
                Finding(item_location, "paired public assets have different revisions")
            )

    return approvals, deduplicate_findings(findings), digest


def validate_asset_manifest(
    root: Path,
) -> tuple[dict[str, AssetApproval], list[Finding], str | None]:
    path = root / ASSET_MANIFEST_PATH
    if not path.exists() and not path.is_symlink():
        return (
            {},
            [Finding(ASSET_MANIFEST_PATH, "public asset disclosure manifest is missing")],
            None,
        )
    payload, read_findings = read_bounded_regular_file(
        path,
        ASSET_MANIFEST_PATH,
        limit=MAX_ASSET_MANIFEST_BYTES,
        subject="asset disclosure manifest",
    )
    if payload is None:
        return {}, read_findings, None
    approvals, findings, digest = parse_asset_manifest_payload(
        payload,
        ASSET_MANIFEST_PATH,
    )
    return approvals, deduplicate_findings([*read_findings, *findings]), digest


def member_is_special(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    kind = stat.S_IFMT(mode)
    return kind not in {0, stat.S_IFREG, stat.S_IFDIR}


def validate_zip_member_compressed_range(
    payload: bytes,
    info: zipfile.ZipInfo,
    location: str,
) -> list[Finding]:
    offset = info.header_offset
    if offset + 30 > len(payload):
        return [Finding(location, "ZIP member local header is truncated")]
    try:
        (
            signature,
            _version,
            local_flags,
            local_compression,
            _modified_time,
            _modified_date,
            local_crc,
            local_compressed_size,
            local_file_size,
            name_length,
            extra_length,
        ) = struct.unpack_from("<4s5H3I2H", payload, offset)
    except struct.error:
        return [Finding(location, "ZIP member local header is invalid")]
    if signature != b"PK\x03\x04":
        return [Finding(location, "ZIP member local header is invalid")]
    if (
        local_flags != info.flag_bits
        or local_compression != info.compress_type
        or local_crc != info.CRC
        or local_compressed_size != info.compress_size
        or local_file_size != info.file_size
    ):
        return [
            Finding(
                location,
                "ZIP member local metadata differs from central directory",
            )
        ]

    data_start = offset + 30 + name_length + extra_length
    data_end = data_start + info.compress_size
    if data_end > len(payload):
        return [Finding(location, "ZIP member compressed range exceeds archive bounds")]
    compressed_payload = payload[data_start:data_end]

    if info.compress_type == zipfile.ZIP_STORED:
        if info.compress_size != info.file_size:
            return [
                Finding(
                    location,
                    "ZIP stored member compressed range has unconsumed bytes",
                )
            ]
        if (zlib.crc32(compressed_payload) & 0xFFFFFFFF) != info.CRC:
            return [Finding(location, "ZIP stored member checksum is invalid")]
        return []

    if info.compress_type != zipfile.ZIP_DEFLATED:
        return [Finding(location, "ZIP member compression method is not approved")]

    decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
    try:
        uncompressed = decompressor.decompress(
            compressed_payload,
            info.file_size + 1,
        )
    except zlib.error:
        return [Finding(location, "ZIP deflate member stream is invalid")]
    if decompressor.unused_data or decompressor.unconsumed_tail:
        return [
            Finding(
                location,
                "ZIP deflate member compressed range has unconsumed bytes",
            )
        ]
    if not decompressor.eof:
        return [Finding(location, "ZIP deflate member stream is incomplete")]
    if len(uncompressed) != info.file_size:
        return [Finding(location, "ZIP deflate member size is invalid")]
    if (zlib.crc32(uncompressed) & 0xFFFFFFFF) != info.CRC:
        return [Finding(location, "ZIP deflate member checksum is invalid")]
    return []


def validate_canonical_zip_structure(
    payload: bytes,
    archive: zipfile.ZipFile,
    relative: str,
) -> list[Finding]:
    findings: list[Finding] = []
    infos = archive.infolist()
    if not payload.startswith(b"PK\x03\x04"):
        findings.append(Finding(relative, "ZIP has prefixed or noncanonical data"))
    if archive.comment:
        findings.append(Finding(relative, "ZIP archive comment is not permitted"))

    eocd_offset = payload.rfind(b"PK\x05\x06")
    if eocd_offset < 0 or eocd_offset + 22 > len(payload):
        findings.append(Finding(relative, "ZIP end-of-central-directory is invalid"))
        return findings
    (
        disk_number,
        central_disk,
        entries_on_disk,
        total_entries,
        central_size,
        central_offset,
        comment_length,
    ) = struct.unpack("<4H2LH", payload[eocd_offset + 4 : eocd_offset + 22])
    if (
        disk_number != 0
        or central_disk != 0
        or entries_on_disk != total_entries
        or total_entries != len(infos)
    ):
        findings.append(Finding(relative, "ZIP multi-disk or entry metadata is invalid"))
    if eocd_offset + 22 + comment_length != len(payload):
        findings.append(Finding(relative, "ZIP has trailing or commented data"))
    if (
        central_offset != archive.start_dir
        or central_offset + central_size != eocd_offset
    ):
        findings.append(Finding(relative, "ZIP central-directory bounds are noncanonical"))

    expected_offset = 0
    for info in sorted(infos, key=lambda item: item.header_offset):
        if info.header_offset != expected_offset:
            findings.append(Finding(relative, "ZIP has gaps or prefixed member data"))
            break
        if info.comment:
            findings.append(Finding(relative, "ZIP member comments are not permitted"))
        if info.extra:
            findings.append(Finding(relative, "ZIP member extra fields are not permitted"))
        if info.flag_bits & 0x08:
            findings.append(Finding(relative, "ZIP data descriptors are not permitted"))
        offset = info.header_offset
        if offset + 30 > len(payload) or payload[offset : offset + 4] != b"PK\x03\x04":
            findings.append(Finding(relative, "ZIP local header is invalid"))
            break
        name_length, extra_length = struct.unpack(
            "<HH",
            payload[offset + 26 : offset + 30],
        )
        if extra_length != 0:
            findings.append(Finding(relative, "ZIP local extra fields are not permitted"))
        data_start = offset + 30 + name_length + extra_length
        expected_offset = data_start + info.compress_size
        if expected_offset > len(payload):
            findings.append(Finding(relative, "ZIP member data exceeds archive bounds"))
            break
    if expected_offset != archive.start_dir:
        findings.append(Finding(relative, "ZIP member layout is noncanonical"))
    return deduplicate_findings(findings)


def scan_typed_payload(
    payload: bytes,
    suffix: str,
    location: str,
    approvals: dict[str, AssetApproval],
    consumed_approvals: set[str],
    *,
    approval_path: str | None = None,
) -> list[Finding]:
    findings = scan_location(location)
    approved_location = approval_path or location

    if suffix in NATIVE_ENGINEERING_EXTENSIONS:
        findings.append(
            Finding(location, f"private engineering file type {suffix or '<none>'}")
        )
        return deduplicate_findings(findings)

    if suffix in DISALLOWED_STRUCTURED_EXTENSIONS:
        findings.append(
            Finding(
                location,
                "YAML is not permitted because private record semantics require a real parser",
            )
        )
        return deduplicate_findings(findings)

    if suffix in PUBLIC_3D_DERIVATIVE_EXTENSIONS:
        findings.extend(
            asset_approval_findings(
                payload,
                location,
                approvals.get(approved_location),
                "public_3d_derivative",
                consumed_approvals,
            )
        )
        if len(payload) > MAX_BINARY_BYTES:
            findings.append(Finding(location, "GLB exceeds scan limit"))
        else:
            findings.extend(validate_glb(payload, location))
        return deduplicate_findings(findings)

    if suffix in TEXT_EXTENSIONS:
        if len(payload) > MAX_TEXT_BYTES:
            findings.append(Finding(location, "text file exceeds scan limit"))
            return deduplicate_findings(findings)
        text = decode_text(payload)
        if text is None:
            findings.append(Finding(location, "declared text file is not decodable"))
            return deduplicate_findings(findings)
        findings.extend(scan_payload(payload, location, suffix=suffix))
        return deduplicate_findings(findings)

    if suffix in PUBLIC_BINARY_EXTENSIONS:
        if len(payload) > MAX_BINARY_BYTES:
            findings.append(Finding(location, "public binary exceeds scan limit"))
            return deduplicate_findings(findings)
        error = validate_public_binary(payload, suffix)
        if error:
            findings.append(Finding(location, error))
        approval = approvals.get(approved_location)
        if (
            approval is not None
            and approval.asset_class == "public_3d_fallback"
        ):
            findings.extend(
                asset_approval_findings(
                    payload,
                    location,
                    approval,
                    "public_3d_fallback",
                    consumed_approvals,
                )
            )
        findings.extend(scan_binary_payload(payload, location))
        return deduplicate_findings(findings)

    findings.append(Finding(location, f"unapproved public file type {suffix or '<none>'}"))
    return deduplicate_findings(findings)


def scan_zip_bytes(
    payload: bytes,
    relative: str,
    approvals: dict[str, AssetApproval],
    consumed_approvals: set[str],
    *,
    approval_relative: str | None = None,
) -> list[Finding]:
    findings = scan_location(relative)
    approved_archive_path = approval_relative or relative
    if len(payload) > MAX_ARCHIVE_BYTES:
        findings.append(Finding(relative, "ZIP archive exceeds size limit"))
        return deduplicate_findings(findings)
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError):
        findings.append(Finding(relative, "invalid ZIP archive"))
        return deduplicate_findings(findings)

    with archive:
        findings.extend(validate_canonical_zip_structure(payload, archive, relative))
        infos = archive.infolist()
        if len(infos) > MAX_ARCHIVE_MEMBERS:
            findings.append(Finding(relative, "ZIP archive exceeds member-count limit"))
            return deduplicate_findings(findings)

        total_uncompressed = sum(info.file_size for info in infos)
        if total_uncompressed > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            findings.append(Finding(relative, "ZIP archive exceeds expansion limit"))
            return deduplicate_findings(findings)

        seen_members: set[str] = set()
        for info in infos:
            try:
                member = normalized_zip_member(info.filename)
            except ValueError as exc:
                findings.append(Finding(relative, str(exc)))
                continue

            normalized_key = member.as_posix().casefold()
            if normalized_key in seen_members:
                findings.append(Finding(relative, "ZIP archive has duplicate member path"))
                continue
            seen_members.add(normalized_key)

            if info.flag_bits & 0x1:
                findings.append(Finding(relative, "ZIP archive has encrypted member"))
                continue
            if member_is_special(info):
                findings.append(Finding(relative, "ZIP archive has symlink or special member"))
                continue

            location = f"{relative}!/{member.as_posix()}"
            approval_location = f"{approved_archive_path}!/{member.as_posix()}"
            suffix = member.suffix.lower()
            findings.extend(scan_location(location))
            if info.is_dir():
                if info.file_size != 0 or info.compress_size != 0:
                    findings.append(Finding(location, "ZIP directory member contains data"))
                else:
                    findings.extend(
                        validate_zip_member_compressed_range(
                            payload,
                            info,
                            location,
                        )
                    )
                continue
            if suffix in NESTED_ARCHIVE_EXTENSIONS:
                findings.append(Finding(location, "nested archive is not permitted"))
                continue
            if info.file_size > MAX_BINARY_BYTES:
                findings.append(Finding(location, "ZIP member exceeds file-size limit"))
                continue
            if (
                info.compress_size > 0
                and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO
            ):
                findings.append(Finding(location, "ZIP member exceeds compression-ratio limit"))
                continue
            compressed_range_findings = validate_zip_member_compressed_range(
                payload,
                info,
                location,
            )
            findings.extend(compressed_range_findings)
            if compressed_range_findings:
                continue
            try:
                member_payload = archive.read(info)
            except (
                BadZipfileError,
                EOFError,
                OSError,
                RuntimeError,
                zipfile.BadZipFile,
            ):
                findings.append(Finding(location, "ZIP member could not be inspected"))
                continue
            findings.extend(
                scan_typed_payload(
                    member_payload,
                    suffix,
                    location,
                    approvals,
                    consumed_approvals,
                    approval_path=approval_location,
                )
            )

    return deduplicate_findings(findings)


BadZipfileError = getattr(zipfile, "BadZipfile", zipfile.BadZipFile)


def read_worktree_payload(
    path: Path,
    location: str,
    *,
    limit: int = MAX_REPOSITORY_FILE_BYTES,
) -> tuple[bytes | None, list[Finding]]:
    findings: list[Finding] = []
    try:
        metadata = path.lstat()
    except OSError:
        return None, [Finding(location, "public worktree file could not be inspected")]
    if stat.S_ISLNK(metadata.st_mode):
        return None, [Finding(location, "repository symlink is not permitted")]
    if not stat.S_ISREG(metadata.st_mode):
        return None, [Finding(location, "repository entry is not a regular file")]
    if metadata.st_size > limit:
        return None, [Finding(location, "repository file exceeds bounded read limit")]
    try:
        with path.open("rb") as handle:
            payload = handle.read(limit + 1)
    except OSError:
        return None, [Finding(location, "public worktree file could not be read")]
    if len(payload) > limit:
        return None, [Finding(location, "repository file exceeds bounded read limit")]
    return payload, findings


def read_git_blob(
    root: Path,
    object_id: str,
    location: str,
    *,
    limit: int = MAX_REPOSITORY_FILE_BYTES,
) -> tuple[bytes | None, list[Finding]]:
    try:
        size_result = run_git(
            root,
            ["cat-file", "-s", object_id],
            text=True,
        )
    except OSError:
        return None, [Finding(location, "Git object size could not be read")]
    if size_result.returncode != 0:
        return None, [Finding(location, "Git object is unavailable")]
    try:
        object_size = int(size_result.stdout.strip())
    except ValueError:
        return None, [Finding(location, "Git object size is invalid")]
    if object_size > limit:
        return None, [Finding(location, "Git object exceeds bounded read limit")]
    try:
        result = run_git(
            root,
            ["cat-file", "blob", object_id],
        )
    except OSError:
        return None, [Finding(location, "Git object could not be read exactly")]
    if result.returncode != 0 or len(result.stdout) != object_size:
        return None, [Finding(location, "Git object could not be read exactly")]
    return result.stdout, []


def repository_object_read_limit(relative: str) -> int:
    if relative == ASSET_MANIFEST_PATH:
        return MAX_ASSET_MANIFEST_BYTES
    if relative == PUBLIC_SNAPSHOT_PATH:
        return MAX_PUBLIC_SNAPSHOT_BYTES
    return MAX_REPOSITORY_FILE_BYTES


def collect_public_objects(
    root: Path,
) -> tuple[list[PublicObject], list[Finding]]:
    findings: list[Finding] = []
    git_directory = root / ".git"
    if git_directory.exists():
        try:
            staged_result = run_git(
                root,
                [
                    "ls-files",
                    "-z",
                    "--cached",
                    "--stage",
                ],
            )
            untracked_result = run_git(
                root,
                [
                    "ls-files",
                    "-z",
                    "--others",
                    "--exclude-standard",
                ],
            )
        except OSError:
            return [], [Finding(".git", "Git inventory could not be executed")]
        if staged_result.returncode != 0 or untracked_result.returncode != 0:
            return [], [Finding(".git", "Git inventory failed")]

        index_entries: dict[str, tuple[str, str]] = {}
        for raw_entry in staged_result.stdout.split(b"\x00"):
            if not raw_entry:
                continue
            try:
                metadata, raw_path = raw_entry.split(b"\t", 1)
                mode, object_id, stage = metadata.decode("ascii").split()
                relative = raw_path.decode("utf-8", errors="surrogateescape")
            except (ValueError, UnicodeDecodeError):
                findings.append(Finding(".git", "Git index entry is malformed"))
                continue
            normalized = relative.replace("\\", "/")
            if stage != "0":
                findings.append(Finding(normalized, "Git index has an unmerged entry"))
                continue
            if mode not in {"100644", "100755"}:
                findings.append(
                    Finding(
                        normalized,
                        f"Git index mode {mode} is not a regular public file",
                    )
                )
                continue
            index_entries[normalized] = (mode, object_id)

        untracked = [
            item.decode("utf-8", errors="surrogateescape")
            for item in untracked_result.stdout.split(b"\x00")
            if item
        ]
        objects: list[PublicObject] = []
        for relative, (_, object_id) in sorted(index_entries.items()):
            index_location = f"git-index:/{relative}"
            object_limit = repository_object_read_limit(relative)
            index_payload, index_findings = read_git_blob(
                root,
                object_id,
                index_location,
                limit=object_limit,
            )
            findings.extend(index_findings)
            worktree_path = root / relative
            worktree_payload = None
            if worktree_path.exists() or worktree_path.is_symlink():
                worktree_payload, worktree_findings = read_worktree_payload(
                    worktree_path,
                    f"worktree:/{relative}",
                    limit=object_limit,
                )
                findings.extend(worktree_findings)

            if index_payload is None:
                if worktree_payload is not None:
                    objects.append(
                        PublicObject(
                            location=relative,
                            receipt_path=relative,
                            payload=worktree_payload,
                            layer="worktree",
                        )
                    )
                continue
            if (
                worktree_payload is not None
                and sha256_bytes(worktree_payload) == sha256_bytes(index_payload)
            ):
                objects.append(
                    PublicObject(
                        location=relative,
                        receipt_path=relative,
                        payload=worktree_payload,
                        layer="index_and_worktree",
                    )
                )
            else:
                objects.append(
                    PublicObject(
                        location=index_location,
                        receipt_path=relative,
                        payload=index_payload,
                        layer="index",
                    )
                )
                if worktree_payload is not None:
                    objects.append(
                        PublicObject(
                            location=f"worktree:/{relative}",
                            receipt_path=relative,
                            payload=worktree_payload,
                            layer="worktree",
                        )
                    )

        for value in sorted(set(untracked)):
            relative = value.replace("\\", "/")
            payload, object_findings = read_worktree_payload(
                root / value,
                relative,
                limit=repository_object_read_limit(relative),
            )
            findings.extend(object_findings)
            if payload is not None:
                objects.append(
                    PublicObject(
                        location=relative,
                        receipt_path=relative,
                        payload=payload,
                        layer="worktree",
                    )
                )
        return objects, findings

    objects = []
    for path in root.rglob("*"):
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if any(part in FALLBACK_EXCLUDED_PARTS for part in relative.parts):
            continue
        if path.is_symlink():
            findings.append(
                Finding(relative.as_posix(), "repository symlink is not permitted")
            )
        elif path.is_file():
            payload, object_findings = read_worktree_payload(
                path,
                relative.as_posix(),
                limit=repository_object_read_limit(relative.as_posix()),
            )
            findings.extend(object_findings)
            if payload is not None:
                objects.append(
                    PublicObject(
                        location=relative.as_posix(),
                        receipt_path=relative.as_posix(),
                        payload=payload,
                        layer="worktree",
                    )
                )
    return sorted(objects, key=lambda item: item.location), findings


def git_state(root: Path) -> tuple[str | None, bool | None]:
    if not (root / ".git").exists():
        return None, None
    try:
        head = run_git(
            root,
            ["rev-parse", "HEAD"],
            text=True,
        )
        status = run_git(
            root,
            ["status", "--porcelain=v1"],
            text=True,
        )
    except OSError:
        return None, None
    git_head = head.stdout.strip() if head.returncode == 0 else None
    git_dirty = bool(status.stdout) if status.returncode == 0 else None
    return git_head, git_dirty


def stable_json_value(value: Any) -> Any:
    if isinstance(value, list):
        return [stable_json_value(child) for child in value]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("canonical JSON object keys must be strings")
        return {
            key: stable_json_value(value[key])
            for key in sorted(value)
        }
    if isinstance(value, float) and not math.isfinite(value):
        raise NonFiniteJsonNumberError("canonical JSON contains a non-finite number")
    return value


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        stable_json_value(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def parse_public_snapshot_payload(
    payload: bytes,
    location: str,
) -> tuple[str | None, list[Finding]]:
    if len(payload) > MAX_PUBLIC_SNAPSHOT_BYTES:
        return None, [
            Finding(location, "public snapshot exceeds bounded read limit")
        ]
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return None, [
            Finding(location, "public snapshot is invalid JSON")
        ]
    try:
        document = strict_json_loads(text)
    except (
        DuplicateJsonKeyError,
        NonFiniteJsonNumberError,
        json.JSONDecodeError,
    ) as exc:
        return None, [json_parse_finding(location, "public snapshot", exc)]
    if not isinstance(document, dict) or "payload" not in document:
        return None, [
            Finding(location, "public snapshot payload is missing")
        ]
    stored = document.get("payload_sha256")
    try:
        canonical_payload = canonical_json_bytes(document["payload"])
    except (NonFiniteJsonNumberError, TypeError, ValueError):
        return None, [
            Finding(location, "public snapshot payload cannot be canonicalized")
        ]
    recomputed = sha256_bytes(canonical_payload)
    if (
        not isinstance(stored, str)
        or not SHA256_PATTERN.fullmatch(stored)
        or stored != recomputed
    ):
        return recomputed, [
            Finding(location, "public snapshot payload hash is invalid")
        ]
    return stored, []


def validate_public_snapshot(
    root: Path,
) -> tuple[str | None, list[Finding]]:
    location = PUBLIC_SNAPSHOT_PATH
    path = root / location
    if not path.exists() and not path.is_symlink():
        return None, [
            Finding(location, "required public snapshot is missing")
        ]
    payload, findings = read_bounded_regular_file(
        path,
        location,
        limit=MAX_PUBLIC_SNAPSHOT_BYTES,
        subject="public snapshot",
    )
    if payload is None:
        return None, findings
    payload_hash, payload_findings = parse_public_snapshot_payload(
        payload,
        location,
    )
    return payload_hash, deduplicate_findings([*findings, *payload_findings])


def scan_repository_report(root: Path) -> ScanReport:
    root = root.resolve()
    findings: list[Finding] = []

    for required in REQUIRED_DIRECTORIES:
        if not (root / required).is_dir():
            findings.append(Finding(required, "required public repository directory is missing"))
    for required in REQUIRED_FILES:
        if not (root / required).is_file():
            findings.append(Finding(required, "required public repository file is missing"))

    approvals, manifest_findings, manifest_hash = validate_asset_manifest(root)
    findings.extend(manifest_findings)
    objects, inventory_findings = collect_public_objects(root)
    findings.extend(inventory_findings)
    snapshot_hash, snapshot_findings = validate_public_snapshot(root)
    findings.extend(snapshot_findings)

    index_approvals = approvals
    distinct_index_manifest = False
    for public_object in objects:
        if (
            public_object.receipt_path == ASSET_MANIFEST_PATH
            and public_object.layer == "index"
        ):
            distinct_index_manifest = True
            (
                index_approvals,
                index_manifest_findings,
                _index_manifest_hash,
            ) = parse_asset_manifest_payload(
                public_object.payload,
                public_object.location,
            )
            findings.extend(index_manifest_findings)
            break

    for public_object in objects:
        if (
            public_object.receipt_path == PUBLIC_SNAPSHOT_PATH
            and public_object.layer == "index"
        ):
            _, index_snapshot_findings = parse_public_snapshot_payload(
                public_object.payload,
                public_object.location,
            )
            findings.extend(index_snapshot_findings)
            break

    index_hashes: list[tuple[str, str]] = []
    worktree_hashes: list[tuple[str, str]] = []
    release_artifacts: list[tuple[str, str]] = []
    consumed_worktree_approvals: set[str] = set()
    consumed_index_approvals: set[str] = (
        set() if distinct_index_manifest else consumed_worktree_approvals
    )
    files_scanned = 0
    archives_scanned = 0

    def scan_object_view(
        public_object: PublicObject,
        *,
        location: str,
        view_approvals: dict[str, AssetApproval],
        consumed_view_approvals: set[str],
    ) -> None:
        payload = public_object.payload
        relative = public_object.receipt_path
        suffix = PurePosixPath(relative).suffix.lower()
        if suffix == ".zip":
            findings.extend(
                scan_zip_bytes(
                    payload,
                    location,
                    view_approvals,
                    consumed_view_approvals,
                    approval_relative=relative,
                )
            )
        else:
            findings.extend(
                scan_typed_payload(
                    payload,
                    suffix,
                    location,
                    view_approvals,
                    consumed_view_approvals,
                    approval_path=relative,
                )
            )

    for public_object in objects:
        relative = public_object.receipt_path
        location = public_object.location
        payload = public_object.payload
        files_scanned += 1
        digest = sha256_bytes(payload)
        if public_object.layer in {"index", "index_and_worktree"}:
            index_hashes.append((relative, digest))
        if public_object.layer in {"worktree", "index_and_worktree"}:
            worktree_hashes.append((relative, digest))
        suffix = PurePosixPath(relative).suffix.lower()
        if suffix == ".zip":
            archives_scanned += 1
        if (
            public_object.layer in {"worktree", "index_and_worktree"}
            and (
                (
                    suffix == ".zip"
                    and relative.startswith("plugin-dist/")
                )
                or relative in ROOT_RELEASE_ARTIFACT_PATHS
            )
        ):
            release_artifacts.append((relative, digest))
        if public_object.layer == "index":
            scan_object_view(
                public_object,
                location=location,
                view_approvals=index_approvals,
                consumed_view_approvals=consumed_index_approvals,
            )
            continue
        scan_object_view(
            public_object,
            location=location,
            view_approvals=approvals,
            consumed_view_approvals=consumed_worktree_approvals,
        )
        if public_object.layer == "index_and_worktree" and distinct_index_manifest:
            scan_object_view(
                public_object,
                location=f"git-index:/{relative}",
                view_approvals=index_approvals,
                consumed_view_approvals=consumed_index_approvals,
            )

    for approved_path in sorted(set(approvals) - consumed_worktree_approvals):
        findings.append(
            Finding(
                approved_path,
                "asset approval does not match an inspected public asset",
            )
        )
    if distinct_index_manifest:
        for approved_path in sorted(
            set(index_approvals) - consumed_index_approvals
        ):
            findings.append(
                Finding(
                    f"git-index:/{approved_path}",
                    "asset approval does not match an inspected public asset",
                )
            )

    if files_scanned == 0:
        findings.append(Finding(".", "public repository inventory is empty"))

    def digest_inventory(values: list[tuple[str, str]]) -> str:
        hasher = hashlib.sha256()
        for relative, digest in sorted(values):
            hasher.update(relative.encode("utf-8", errors="surrogateescape"))
            hasher.update(b"\x00")
            hasher.update(digest.encode("ascii"))
            hasher.update(b"\n")
        return hasher.hexdigest()

    git_head, git_dirty = git_state(root)
    worktree_digest = digest_inventory(worktree_hashes)
    index_digest = digest_inventory(index_hashes) if index_hashes else None
    return ScanReport(
        findings=tuple(deduplicate_findings(findings)),
        files_scanned=files_scanned,
        archives_scanned=archives_scanned,
        repository_content_sha256=worktree_digest,
        git_index_content_sha256=index_digest,
        worktree_content_sha256=worktree_digest,
        release_artifacts=tuple(sorted(set(release_artifacts))),
        asset_manifest_sha256=manifest_hash,
        public_snapshot_payload_sha256=snapshot_hash,
        git_head=git_head,
        git_dirty=git_dirty,
    )


def scan_repository(root: Path) -> tuple[list[Finding], int, int]:
    report = scan_repository_report(root)
    return list(report.findings), report.files_scanned, report.archives_scanned


def release_receipt_path(root: Path, value: Path) -> tuple[Path | None, list[Finding]]:
    candidate = value if value.is_absolute() else root / value
    try:
        resolved = candidate.resolve()
    except OSError:
        return None, [Finding(str(value), "release receipt path cannot be resolved")]

    try:
        relative = resolved.relative_to(root)
    except ValueError:
        relative = None
    if relative is not None and (
        not relative.parts
        or relative.parts[0] != "work"
    ):
        return None, [
            Finding(
                str(value),
                "release receipt inside the repository must be under ignored work/",
            )
        ]
    if relative is not None and (root / ".git").exists():
        try:
            ignored = run_git(
                root,
                [
                    "check-ignore",
                    "--quiet",
                    "--no-index",
                    relative.as_posix(),
                ],
            )
        except OSError:
            return None, [
                Finding(str(value), "release receipt ignore status could not be checked")
            ]
        if ignored.returncode != 0:
            return None, [
                Finding(
                    str(value),
                    "release receipt path must be ignored by Git",
                )
            ]
    if resolved.suffix.lower() != ".json":
        return None, [Finding(str(value), "release receipt must be a JSON file")]
    if resolved.exists() or resolved.is_symlink():
        return None, [Finding(str(value), "release receipt already exists")]
    return resolved, []


def validate_release_request(
    root: Path,
    report: ScanReport,
    args: argparse.Namespace,
) -> tuple[dict[str, Any] | None, Path | None, list[Finding]]:
    findings: list[Finding] = []
    expected_commit = str(args.expected_commit or "").lower()
    if GIT_COMMIT_PATTERN.fullmatch(expected_commit) is None:
        findings.append(
            Finding("--expected-commit", "expected commit must be 40 lowercase hexadecimal characters")
        )
    if report.git_head is None or report.git_dirty is None:
        findings.append(Finding(".git", "release mode requires a Git repository"))
    else:
        if report.git_dirty:
            findings.append(Finding(".git", "release mode requires a clean Git worktree and index"))
        if report.git_head != expected_commit:
            findings.append(Finding(".git", "release HEAD does not match expected commit"))
    if (
        report.git_index_content_sha256 is None
        or report.git_index_content_sha256 != report.worktree_content_sha256
    ):
        findings.append(
            Finding(".git", "release index and worktree inventories do not match")
        )

    try:
        artifact_path = normalize_public_path(str(args.artifact_path or ""))
    except ValueError as exc:
        artifact_path = ""
        findings.append(Finding("--artifact-path", str(exc)))
    if not artifact_path:
        findings.append(
            Finding(
                "--artifact-path",
                "release mode requires an inspected artifact path",
            )
        )
    if (
        artifact_path
        and (
            artifact_path not in ROOT_RELEASE_ARTIFACT_PATHS
            and (
                not artifact_path.startswith("plugin-dist/")
                or PurePosixPath(artifact_path).suffix.lower() != ".zip"
            )
        )
    ):
        findings.append(
            Finding(
                "--artifact-path",
                "release artifact must be a ZIP under plugin-dist/ "
                "or the approved root robots source",
            )
        )

    expected_artifact_sha = str(args.artifact_sha256 or "").lower()
    if SHA256_PATTERN.fullmatch(expected_artifact_sha) is None:
        findings.append(
            Finding("--artifact-sha256", "artifact SHA-256 is invalid")
        )
    elif artifact_path:
        release_artifacts = dict(report.release_artifacts)
        actual = release_artifacts.get(artifact_path)
        if actual is None:
            findings.append(
                Finding(artifact_path, "release artifact was not inspected")
            )
        elif actual != expected_artifact_sha:
            findings.append(
                Finding(artifact_path, "release artifact hash does not match")
            )

    if report.public_snapshot_payload_sha256 is None:
        findings.append(
            Finding(
                "packages/publication/golden-slice.v0.json",
                "release has no valid public snapshot hash",
            )
        )
    if report.asset_manifest_sha256 is None:
        findings.append(
            Finding(ASSET_MANIFEST_PATH, "release has no valid asset manifest hash")
        )

    receipt_path, receipt_findings = release_receipt_path(root, args.receipt)
    findings.extend(receipt_findings)
    findings.extend(report.findings)
    findings = deduplicate_findings(findings)
    if findings or receipt_path is None:
        return None, receipt_path, findings

    receipt: dict[str, Any] = {
        "schema_version": 1,
        "receipt_type": "robbottx_public_boundary_release",
        "release_mode": True,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00",
            "Z",
        ),
        "repository": {
            "git_head": report.git_head,
            "git_dirty": False,
            "git_index_content_sha256": report.git_index_content_sha256,
            "worktree_content_sha256": report.worktree_content_sha256,
        },
        "public_boundary": {
            "repository_content_sha256": report.repository_content_sha256,
            "asset_manifest_sha256": report.asset_manifest_sha256,
            "public_snapshot_payload_sha256": report.public_snapshot_payload_sha256,
            "finding_count": 0,
        },
        "artifact": {
            "path": artifact_path,
            "sha256": expected_artifact_sha,
        },
    }
    receipt["receipt_body_sha256"] = sha256_bytes(canonical_json_bytes(receipt))
    return receipt, receipt_path, []


def write_release_receipt(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = (
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.rename(temporary, path)
    except FileExistsError as exc:
        raise RuntimeError("release receipt path already exists") from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Public repository root",
    )
    parser.add_argument("--release", action="store_true")
    parser.add_argument("--expected-commit", default="")
    parser.add_argument("--artifact-path", default="")
    parser.add_argument("--artifact-sha256", default="")
    parser.add_argument("--receipt", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    root = args.root.resolve()
    report = scan_repository_report(root)
    release_receipt = None
    release_receipt_path_value = None
    release_findings: list[Finding] = []
    if args.release:
        if args.receipt is None:
            release_findings.append(
                Finding("--receipt", "release mode requires a receipt path")
            )
        else:
            (
                release_receipt,
                release_receipt_path_value,
                release_findings,
            ) = validate_release_request(root, report, args)
    elif any(
        (
            args.expected_commit,
            args.artifact_path,
            args.artifact_sha256,
            args.receipt is not None,
        )
    ):
        release_findings.append(
            Finding("--release", "release-only arguments require --release")
        )
    effective_findings = tuple(
        deduplicate_findings([*report.findings, *release_findings])
    )
    result = {
        "schema_version": 3,
        "repository": str(root),
        "git": {
            "head": report.git_head,
            "dirty": report.git_dirty,
        },
        "files_scanned": report.files_scanned,
        "archives_scanned": report.archives_scanned,
        "repository_content_sha256": report.repository_content_sha256,
        "git_index_content_sha256": report.git_index_content_sha256,
        "worktree_content_sha256": report.worktree_content_sha256,
        "asset_manifest_sha256": report.asset_manifest_sha256,
        "public_snapshot_payload_sha256": report.public_snapshot_payload_sha256,
        "release_artifacts": [
            {"path": path, "sha256": digest}
            for path, digest in report.release_artifacts
        ],
        "release_mode": bool(args.release),
        "release_receipt": (
            str(release_receipt_path_value)
            if release_receipt_path_value is not None and not effective_findings
            else None
        ),
        "finding_count": len(effective_findings),
        "findings": [
            {"location": finding.location, "reason": finding.reason}
            for finding in effective_findings
        ],
    }
    if not effective_findings and release_receipt is not None:
        if release_receipt_path_value is None:
            raise RuntimeError("release receipt path was not resolved")
        write_release_receipt(release_receipt_path_value, release_receipt)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if effective_findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
