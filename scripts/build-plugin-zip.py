#!/usr/bin/env python3
"""Build a deterministic, inspected WordPress plugin ZIP."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ALLOWED_APPLICATION_FILES = {
    "blocks/golden-slice/block.json",
    "blocks/golden-slice/render.php",
    "readme.txt",
    "resources/publication/golden-slice.v0.php",
    "robbottx-core.php",
    "src/Discovery/PublicDiscovery.php",
    "src/Lifecycle.php",
    "src/Plugin.php",
    "src/Presentation/Assets.php",
    "src/Presentation/Blocks.php",
    "src/Presentation/GoldenSliceRenderer.php",
    "src/Presentation/Seo.php",
    "src/Projection/MetaFields.php",
    "src/Projection/PostTypes.php",
    "src/Projection/PublicationGate.php",
    "src/Publication/SnapshotRepository.php",
    "src/Rest/HealthController.php",
    "src/Updates/UpdateChecker.php",
    "uninstall.php",
    "views/golden-slice.php",
}
VENDORED_PREFIX = "lib/plugin-update-checker/"
VENDORED_FILE_COUNT = 117
VENDORED_TREE_SHA256 = (
    "5eee344091bc55556d5872d82dcd0531f597d0c5cbe029c1b5cdcef45c5ded18"
)


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


def tree_digest(root: Path, files: list[Path]) -> str:
    digest = hashlib.sha256()
    for file_path in sorted(
        files,
        key=lambda path: path.relative_to(root).as_posix(),
    ):
        relative = file_path.relative_to(root).as_posix()
        file_digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_digest.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def collect_allowed_files(plugin_dir: Path) -> list[Path]:
    files = sorted(
        (path for path in plugin_dir.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(plugin_dir).as_posix(),
    )
    application_files: set[str] = set()
    vendored_files: list[Path] = []
    unexpected: list[str] = []

    for file_path in files:
        relative = file_path.relative_to(plugin_dir).as_posix()
        if relative.startswith(VENDORED_PREFIX):
            vendored_files.append(file_path)
        elif relative in ALLOWED_APPLICATION_FILES:
            application_files.add(relative)
        else:
            unexpected.append(relative)

    missing = sorted(ALLOWED_APPLICATION_FILES - application_files)
    if unexpected:
        fail(
            "Unexpected plugin package files:\n- "
            + "\n- ".join(unexpected)
        )
    if missing:
        fail(
            "Required plugin package files are missing:\n- "
            + "\n- ".join(missing)
        )
    if len(vendored_files) != VENDORED_FILE_COUNT:
        fail("Vendored dependency file count does not match its pinned inventory.")

    vendor_root = plugin_dir / VENDORED_PREFIX.rstrip("/")
    if tree_digest(vendor_root, vendored_files) != VENDORED_TREE_SHA256:
        fail("Vendored dependency inventory or checksums changed.")

    return files


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

    files = collect_allowed_files(plugin_dir)
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

    inventory = {
        "artifact": output.name,
        "version": args.version,
        "zip_bytes": output.stat().st_size,
        "zip_sha256": digest,
        "files": [
            {
                "path": (
                    PurePosixPath(args.slug)
                    / PurePosixPath(file_path.relative_to(plugin_dir).as_posix())
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
