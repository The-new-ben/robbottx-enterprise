#!/usr/bin/env python3
"""Build a deterministic, inspected WordPress plugin ZIP."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


EXCLUDED_PARTS = {
    ".git",
    ".github",
    ".idea",
    ".vscode",
    "node_modules",
    "tests",
    "vendor-bin",
}
EXCLUDED_SUFFIXES = {".map", ".log", ".sql", ".sqlite", ".pem", ".key", ".p12"}
SECRET_NAMES = {".env", "credentials.json", "cookies.txt"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin-dir", required=True, type=Path)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--main-file", required=True)
    parser.add_argument("--version-constant", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--require-marker")
    return parser.parse_args()


def fail(message: str) -> None:
    raise SystemExit(message)


def allowed(relative: Path) -> bool:
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return False
    if relative.name.lower() in SECRET_NAMES:
        return False
    if relative.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    return True


def assert_version(main_text: str, version: str, constant: str) -> None:
    header = re.search(r"^\s*\*\s*Version:\s*([^\s]+)", main_text, re.MULTILINE)
    if not header or header.group(1) != version:
        fail("Plugin header version does not match requested version.")

    constant_pattern = re.compile(
        rf"(?:define\s*\(\s*['\"]{re.escape(constant)}['\"]\s*,\s*['\"]{re.escape(version)}['\"]|"
        rf"const\s+{re.escape(constant)}\s*=\s*['\"]{re.escape(version)}['\"])"
    )
    if not constant_pattern.search(main_text):
        fail("Plugin version constant does not match requested version.")


def zip_info(name: str, executable: bool) -> ZipInfo:
    info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = ((0o755 if executable else 0o644) & 0xFFFF) << 16
    return info


def main() -> int:
    args = parse_args()
    plugin_dir = args.plugin_dir.resolve()
    main_file = plugin_dir / args.main_file

    if not plugin_dir.is_dir() or not main_file.is_file():
        fail("Plugin directory or main file is missing.")
    if not re.fullmatch(r"[a-z0-9-]+", args.slug):
        fail("Slug must contain lowercase letters, digits, and hyphens only.")
    if plugin_dir.name != args.slug:
        fail("Plugin directory name must equal the stable plugin slug.")

    main_text = main_file.read_text(encoding="utf-8")
    assert_version(main_text, args.version, args.version_constant)

    files = sorted(
        (
            path
            for path in plugin_dir.rglob("*")
            if path.is_file() and allowed(path.relative_to(plugin_dir))
        ),
        key=lambda path: path.relative_to(plugin_dir).as_posix(),
    )
    if not files:
        fail("No package files found.")

    combined_text = ""
    for file_path in files:
        relative = file_path.relative_to(plugin_dir)
        lower = relative.as_posix().lower()
        if "\\" in lower or "legacy-catalog" in lower or "catalog-images" in lower:
            fail(f"Forbidden path in package: {relative}")
        if file_path.suffix.lower() in {".php", ".json", ".js", ".css", ".txt", ".md"}:
            combined_text += file_path.read_text(encoding="utf-8", errors="strict")

    if args.require_marker and args.require_marker not in combined_text:
        fail("Required release marker is absent from package source.")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / f"{args.slug}-{args.version}.zip"

    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for file_path in files:
            relative = PurePosixPath(args.slug) / PurePosixPath(
                file_path.relative_to(plugin_dir).as_posix()
            )
            data = file_path.read_bytes()
            executable = file_path.suffix.lower() in {".sh", ".py"}
            archive.writestr(zip_info(str(relative), executable), data)

    digest = hashlib.sha256(output.read_bytes()).hexdigest()

    with ZipFile(output, "r") as archive:
        names = archive.namelist()
        if any("\\" in name for name in names):
            fail("ZIP contains Windows path separators.")
        if any(not name.startswith(f"{args.slug}/") for name in names):
            fail("ZIP contains an unexpected root.")
        if archive.testzip() is not None:
            fail("ZIP integrity test failed.")
        packaged_main = archive.read(f"{args.slug}/{args.main_file}").decode("utf-8")
        assert_version(packaged_main, args.version, args.version_constant)

    print(f"{output}\t{output.stat().st_size}\t{digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
