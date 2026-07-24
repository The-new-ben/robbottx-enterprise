#!/usr/bin/env python3
"""Build a deterministic WordPress theme ZIP for the one-time chrome install."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ALLOWED_THEME_FILES = {
    "ASSET-LICENSES.json",
    "assets/favicon.svg",
    "functions.php",
    "parts/footer.html",
    "parts/header.html",
    "patterns/home-methodology.php",
    "patterns/home-precision-atlas.php",
    "readme.txt",
    "style.css",
    "templates/404.html",
    "templates/front-page.html",
    "templates/index.html",
    "templates/page.html",
    "templates/search.html",
    "templates/single-rbtx_config.html",
    "templates/single-rbtx_entity.html",
    "templates/single.html",
    "theme.json",
}


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
        (path for path in theme_dir.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(theme_dir).as_posix(),
    )
    actual_files = {
        path.relative_to(theme_dir).as_posix()
        for path in files
    }
    unexpected = sorted(actual_files - ALLOWED_THEME_FILES)
    missing = sorted(ALLOWED_THEME_FILES - actual_files)
    if unexpected:
        fail(
            "Unexpected theme package files:\n- "
            + "\n- ".join(unexpected)
        )
    if missing:
        fail(
            "Required theme package files are missing:\n- "
            + "\n- ".join(missing)
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
    inventory = {
        "artifact": output.name,
        "version": args.version,
        "zip_bytes": output.stat().st_size,
        "zip_sha256": digest,
        "files": [
            {
                "path": (
                    PurePosixPath(args.slug)
                    / PurePosixPath(file_path.relative_to(theme_dir).as_posix())
                ).as_posix(),
                "bytes": file_path.stat().st_size,
                "sha256": hashlib.sha256(file_path.read_bytes()).hexdigest(),
            }
            for file_path in files
        ],
    }
    inventory_path = args.output_dir / f"{args.slug}-{args.version}.inventory.json"
    inventory_path.write_bytes(
        (
            json.dumps(inventory, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
    )
    print(f"{output}\t{output.stat().st_size}\t{digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
