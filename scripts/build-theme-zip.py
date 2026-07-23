#!/usr/bin/env python3
"""Build a deterministic WordPress theme ZIP for the one-time chrome install."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


def fail(message: str) -> None:
    raise SystemExit(message)


def zip_info(name: str) -> ZipInfo:
    info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o644 << 16
    return info


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme-dir", required=True, type=Path)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    theme_dir = args.theme_dir.resolve()
    style = theme_dir / "style.css"
    required = [
        style,
        theme_dir / "theme.json",
        theme_dir / "templates" / "index.html",
    ]

    if theme_dir.name != args.slug or not all(path.is_file() for path in required):
        fail("Theme root or required block-theme files are invalid.")

    style_text = style.read_text(encoding="utf-8")
    header = re.search(r"^Version:\s*([^\s]+)", style_text, re.MULTILINE)
    if not header or header.group(1) != args.version:
        fail("Theme header version does not match requested version.")

    files = sorted(
        (
            path
            for path in theme_dir.rglob("*")
            if path.is_file()
            and ".git" not in path.parts
            and path.suffix.lower() not in {".map", ".log", ".sql", ".env"}
        ),
        key=lambda path: path.relative_to(theme_dir).as_posix(),
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / f"{args.slug}-{args.version}.zip"

    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for file_path in files:
            relative = PurePosixPath(args.slug) / PurePosixPath(
                file_path.relative_to(theme_dir).as_posix()
            )
            archive.writestr(zip_info(str(relative)), file_path.read_bytes())

    with ZipFile(output, "r") as archive:
        if archive.testzip() is not None:
            fail("Theme ZIP integrity test failed.")
        if any("\\" in name for name in archive.namelist()):
            fail("Theme ZIP contains Windows path separators.")
        packaged_style = archive.read(f"{args.slug}/style.css").decode("utf-8")
        if f"Version: {args.version}" not in packaged_style:
            fail("Packaged theme version is wrong.")

    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    print(f"{output}\t{output.stat().st_size}\t{digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
