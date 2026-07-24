from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import stat
import struct
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "validate-proprietary-boundary.py"
)
SPEC = importlib.util.spec_from_file_location(
    "validate_proprietary_boundary",
    SCRIPT_PATH,
)
assert SPEC and SPEC.loader
boundary = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = boundary
SPEC.loader.exec_module(boundary)

PRIVATE_CLASSIFICATION = "_".join(("confidential", "proprietary"))
PRIVATE_SYSTEM_ID = "-".join(("RBTX", "RS", "001"))
PRIVATE_HAZARD_ID = ":".join(("RBTX", "HAZ", "RS001-0001"))
PRIVATE_VERIFICATION_TYPE = "_".join(("verification", "plan"))
PRIVATE_HAZARD_TYPE = "haz" + "ards"


class ProprietaryBoundaryTests(unittest.TestCase):
    def make_root(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for relative in boundary.REQUIRED_DIRECTORIES:
            (root / relative).mkdir(parents=True, exist_ok=True)
        (root / ".gitignore").write_text("*.log\nwork/\n", encoding="utf-8")
        (root / "AGENTS.md").write_text("# Public repository\n", encoding="utf-8")
        (root / "package.json").write_text(
            '{"name":"public-test","private":true}',
            encoding="utf-8",
        )
        self.write_asset_manifest(root, [])
        self.write_public_snapshot(root)
        return root

    def write_public_snapshot(self, root: Path, payload: dict | None = None) -> None:
        public_payload = payload or {"entities": []}
        path = root / "packages" / "publication" / "golden-slice.v0.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "format_version": "0.1.0",
                    "payload": public_payload,
                    "payload_sha256": hashlib.sha256(
                        boundary.canonical_json_bytes(public_payload)
                    ).hexdigest(),
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    def valid_glb(
        self,
        document: dict | None = None,
        *,
        json_text: str | None = None,
        bin_payload: bytes | None = None,
    ) -> bytes:
        gltf = document or {"asset": {"version": "2.0"}}
        json_chunk = (
            json_text.encode("utf-8")
            if json_text is not None
            else json.dumps(gltf, separators=(",", ":")).encode("utf-8")
        )
        json_chunk += b" " * ((-len(json_chunk)) % 4)
        chunks = (
            struct.pack("<II", len(json_chunk), 0x4E4F534A)
            + json_chunk
        )
        if bin_payload is not None:
            padded_bin = bin_payload + b"\x00" * ((-len(bin_payload)) % 4)
            chunks += (
                struct.pack("<II", len(padded_bin), 0x004E4942)
                + padded_bin
            )
        total = 12 + len(chunks)
        return (
            b"glTF"
            + struct.pack("<II", 2, total)
            + chunks
        )

    def asset_approval(
        self,
        relative: str,
        payload: bytes,
        asset_class: str,
        paired_asset_path: str,
        approval_number: int,
    ) -> dict:
        return {
            "approval_id": f"PUBLIC-ASSET-APPROVAL-{approval_number:04d}",
            "asset_class": asset_class,
            "bytes": len(payload),
            "disclosure_status": "approved_for_public_release",
            "paired_asset_path": paired_asset_path,
            "path": relative,
            "public_revision": "PUBLIC-VISUAL-0.1",
            "rights_status": "approved",
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

    def zip_with_hidden_member_bytes(self, compression: int) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
            archive.writestr("plugin/index.php", "<?php")
        payload = bytearray(buffer.getvalue())
        local_offset = payload.find(b"PK\x03\x04")
        central_offset = payload.find(b"PK\x01\x02")
        eocd_offset = payload.rfind(b"PK\x05\x06")
        self.assertGreaterEqual(local_offset, 0)
        self.assertGreater(central_offset, local_offset)
        self.assertGreater(eocd_offset, central_offset)
        compressed_size = struct.unpack_from("<I", payload, local_offset + 18)[0]
        name_length, extra_length = struct.unpack_from(
            "<HH",
            payload,
            local_offset + 26,
        )
        data_start = local_offset + 30 + name_length + extra_length
        self.assertEqual(data_start + compressed_size, central_offset)
        hidden = b"HIDDEN-BYTES"
        payload[central_offset:central_offset] = hidden
        shifted_central = central_offset + len(hidden)
        shifted_eocd = eocd_offset + len(hidden)
        struct.pack_into(
            "<I",
            payload,
            local_offset + 18,
            compressed_size + len(hidden),
        )
        struct.pack_into(
            "<I",
            payload,
            shifted_central + 20,
            compressed_size + len(hidden),
        )
        struct.pack_into("<I", payload, shifted_eocd + 16, shifted_central)
        return bytes(payload)

    def initialize_git(self, root: Path) -> str:
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(
            ["git", "config", "core.autocrlf", "false"],
            cwd=root,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "boundary@example.invalid"],
            cwd=root,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Boundary Test"],
            cwd=root,
            check=True,
        )
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "test fixture"],
            cwd=root,
            check=True,
        )
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def write_asset_manifest(self, root: Path, assets: list[dict]) -> None:
        path = root / boundary.ASSET_MANIFEST_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"schema_version": 2, "assets": assets}, indent=2),
            encoding="utf-8",
        )

    def test_clean_public_repository_passes(self) -> None:
        root = self.make_root()
        (root / "wp-content" / "index.html").write_text(
            "<main>Robotics components and systems</main>",
            encoding="utf-8",
        )
        report = boundary.scan_repository_report(root)
        self.assertEqual(report.findings, ())
        self.assertGreaterEqual(report.files_scanned, 5)
        self.assertEqual(report.archives_scanned, 0)
        self.assertRegex(report.repository_content_sha256, r"^[0-9a-f]{64}$")

    def test_standalone_scanner_uses_protected_credential_free_git(self) -> None:
        root = self.make_root()
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = command
            captured["environment"] = kwargs["env"]
            return SimpleNamespace(
                returncode=0,
                stdout="",
                stderr="",
            )

        fake_git = (root / "trusted" / "git.exe").resolve()
        with (
            patch.object(
                boundary,
                "resolve_trusted_git_executable",
                return_value=fake_git,
            ),
            patch.object(boundary.subprocess, "run", side_effect=fake_run),
            patch.dict(
                os.environ,
                {"WP_APP_PASSWORD": "must-not-reach-git"},
            ),
        ):
            boundary.run_git(
                root,
                ["status", "--porcelain=v1"],
                text=True,
            )

        self.assertEqual(captured["command"][0], str(fake_git))
        self.assertNotIn(
            "WP_APP_PASSWORD",
            captured["environment"],
        )

    def test_private_marker_and_identifier_are_rejected(self) -> None:
        root = self.make_root()
        (root / "packages" / "publication" / "record.json").write_text(
            json.dumps(
                {
                    "classification": PRIVATE_CLASSIFICATION,
                    "system_id": PRIVATE_SYSTEM_ID,
                },
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        findings, _, _ = boundary.scan_repository(root)
        reasons = {finding.reason for finding in findings}
        self.assertIn("private classification or state", reasons)
        self.assertIn("private reference-system identifier", reasons)

    def test_sensitive_cad_type_is_rejected(self) -> None:
        root = self.make_root()
        (root / "wp-content" / "model.step").write_bytes(b"STEP")
        findings, _, _ = boundary.scan_repository(root)
        self.assertIn(
            boundary.Finding(
                "wp-content/model.step",
                "private engineering file type .step",
            ),
            findings,
        )

    def test_private_record_inside_zip_is_rejected(self) -> None:
        root = self.make_root()
        archive_path = root / "plugin-dist" / "release.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr(
                "plugin/data.json",
                json.dumps({"record_type": PRIVATE_VERIFICATION_TYPE}),
            )
        findings, _, archives = boundary.scan_repository(root)
        self.assertEqual(archives, 1)
        self.assertTrue(
            any(
                finding.location
                == "plugin-dist/release.zip!/plugin/data.json"
                and "private" in finding.reason
                for finding in findings
            )
        )

    def test_unsafe_zip_member_path_is_rejected(self) -> None:
        root = self.make_root()
        archive_path = root / "plugin-dist" / "release.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("../private.json", "{}")
        findings, _, _ = boundary.scan_repository(root)
        self.assertTrue(
            any("unsafe archive member path" in finding.reason for finding in findings)
        )

    def test_every_public_repository_area_is_scanned(self) -> None:
        root = self.make_root()
        (root / "docs").mkdir()
        (root / "docs" / "leak.json").write_text(
            json.dumps({"record_type": PRIVATE_HAZARD_TYPE}),
            encoding="utf-8",
        )
        findings, _, _ = boundary.scan_repository(root)
        self.assertTrue(
            any(
                finding.location == "docs/leak.json"
                and "private" in finding.reason
                for finding in findings
            )
        )

    def test_serialization_and_encoding_variants_are_rejected(self) -> None:
        variants = {
            "compact.json": json.dumps(
                {"record_type": PRIVATE_HAZARD_TYPE},
                separators=(",", ":"),
            ).encode(),
            "spaced.yaml": (
                "_".join(("record", "type")) + ": " + PRIVATE_HAZARD_TYPE
            ).encode(),
            "utf16.json": json.dumps(
                {"record_type": PRIVATE_HAZARD_TYPE}
            ).encode("utf-16"),
            "utf16le.json": json.dumps(
                {"record_type": PRIVATE_HAZARD_TYPE}
            ).encode("utf-16-le"),
            "utf32le.json": json.dumps(
                {"record_type": PRIVATE_HAZARD_TYPE}
            ).encode("utf-32-le"),
            "hyphenated.json": json.dumps(
                {
                    "-".join(("record", "type")):
                    "-".join(("verification", "plan"))
                }
            ).encode(),
            "escaped.json": (
                '{"system_id":"'
                + "".join(f"\\u{ord(character):04x}" for character in PRIVATE_SYSTEM_ID)
                + '"}'
            ).encode(),
        }
        for name, payload in variants.items():
            with self.subTest(name=name):
                root = self.make_root()
                (root / "packages" / "publication" / name).write_bytes(payload)
                findings, _, _ = boundary.scan_repository(root)
                self.assertTrue(
                    any("private" in finding.reason for finding in findings),
                    findings,
                )

    def test_json_documents_and_canonicalization_reject_ambiguous_numbers(self) -> None:
        root = self.make_root()
        publication = root / "packages" / "publication"
        (publication / "duplicate.json").write_text(
            '{"safe":true,"safe":false}',
            encoding="utf-8",
        )
        (publication / "nan.json").write_text(
            '{"measurement":NaN}',
            encoding="utf-8",
        )
        (publication / "overflow.json").write_text(
            '{"upper":1e9999,"lower":-1e9999}',
            encoding="utf-8",
        )
        report = boundary.scan_repository_report(root)
        reasons = {finding.reason for finding in report.findings}
        self.assertIn("JSON document has a duplicate object key", reasons)
        self.assertIn("JSON document contains a non-finite number", reasons)
        for token in ("1e9999", "-1e9999"):
            with self.subTest(token=token):
                with self.assertRaises(boundary.NonFiniteJsonNumberError):
                    boundary.strict_json_loads(
                        '{"measurement":' + token + "}"
                    )
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                with self.assertRaises(boundary.NonFiniteJsonNumberError):
                    boundary.canonical_json_bytes({"measurement": value})

    def test_manifest_snapshot_and_glb_use_strict_json_parsing(self) -> None:
        manifest_cases = {
            "duplicate": (
                '{"schema_version":2,"schema_version":2,"assets":[]}',
                "asset disclosure manifest has a duplicate object key",
            ),
            "nonfinite": (
                '{"schema_version":2,"assets":[],"limit":Infinity}',
                "asset disclosure manifest contains a non-finite number",
            ),
            "overflow": (
                '{"schema_version":2,"assets":[],"limit":1e9999}',
                "asset disclosure manifest contains a non-finite number",
            ),
        }
        for name, (raw, expected) in manifest_cases.items():
            with self.subTest(surface="manifest", case=name):
                root = self.make_root()
                (root / boundary.ASSET_MANIFEST_PATH).write_text(
                    raw,
                    encoding="utf-8",
                )
                report = boundary.scan_repository_report(root)
                self.assertIn(
                    expected,
                    {finding.reason for finding in report.findings},
                )

        snapshot_path = "packages/publication/golden-slice.v0.json"
        snapshot_cases = {
            "duplicate": (
                '{"payload":{},"payload":{},"payload_sha256":"'
                + ("0" * 64)
                + '"}',
                "public snapshot has a duplicate object key",
            ),
            "nonfinite": (
                '{"payload":{"measurement":-Infinity},"payload_sha256":"'
                + ("0" * 64)
                + '"}',
                "public snapshot contains a non-finite number",
            ),
            "overflow": (
                '{"payload":{"measurement":-1e9999},"payload_sha256":"'
                + ("0" * 64)
                + '"}',
                "public snapshot contains a non-finite number",
            ),
        }
        for name, (raw, expected) in snapshot_cases.items():
            with self.subTest(surface="snapshot", case=name):
                root = self.make_root()
                (root / snapshot_path).write_text(raw, encoding="utf-8")
                report = boundary.scan_repository_report(root)
                self.assertIn(
                    expected,
                    {finding.reason for finding in report.findings},
                )

        glb_cases = {
            "duplicate": (
                '{"asset":{"version":"2.0","version":"1.0"}}',
                "GLB JSON chunk has a duplicate object key",
            ),
            "nonfinite": (
                '{"asset":{"version":"2.0"},"measurement":NaN}',
                "GLB JSON chunk contains a non-finite number",
            ),
            "overflow": (
                '{"asset":{"version":"2.0"},"measurement":1e9999}',
                "GLB JSON chunk contains a non-finite number",
            ),
        }
        for name, (raw, expected) in glb_cases.items():
            with self.subTest(surface="glb", case=name):
                reasons = {
                    finding.reason
                    for finding in boundary.validate_glb(
                        self.valid_glb(json_text=raw),
                        "model.glb",
                    )
                }
                self.assertIn(expected, reasons)

    def test_manifest_and_snapshot_reads_are_bounded(self) -> None:
        cases = (
            (
                boundary.ASSET_MANIFEST_PATH,
                boundary.MAX_ASSET_MANIFEST_BYTES,
                "asset disclosure manifest exceeds bounded read limit",
            ),
            (
                "packages/publication/golden-slice.v0.json",
                boundary.MAX_PUBLIC_SNAPSHOT_BYTES,
                "public snapshot exceeds bounded read limit",
            ),
        )
        for relative, limit, expected in cases:
            with self.subTest(relative=relative):
                root = self.make_root()
                with (root / relative).open("wb") as handle:
                    handle.truncate(limit + 1)
                report = boundary.scan_repository_report(root)
                self.assertIn(
                    expected,
                    {finding.reason for finding in report.findings},
                )

    def test_private_engineering_namespace_is_rejected(self) -> None:
        root = self.make_root()
        (root / "docs").mkdir()
        (root / "docs" / "claim.txt").write_text(
            PRIVATE_HAZARD_ID,
            encoding="utf-8",
        )
        findings, _, _ = boundary.scan_repository(root)
        self.assertTrue(
            any(
                finding.reason == "private engineering-record identifier"
                for finding in findings
            )
        )

    def test_private_identifier_in_filename_is_rejected(self) -> None:
        root = self.make_root()
        (root / "docs").mkdir()
        (root / "docs" / f"{PRIVATE_SYSTEM_ID}.json").write_text(
            "{}",
            encoding="utf-8",
        )
        findings, _, _ = boundary.scan_repository(root)
        self.assertTrue(
            any(
                finding.location == f"docs/{PRIVATE_SYSTEM_ID}.json"
                and finding.reason == "private reference-system identifier"
                for finding in findings
            )
        )

    def test_unknown_and_oversized_files_fail_closed(self) -> None:
        root = self.make_root()
        (root / "docs").mkdir()
        (root / "docs" / "unknown.log").write_text("ordinary", encoding="utf-8")
        (root / "docs" / "large.json").write_bytes(
            b" " * (boundary.MAX_TEXT_BYTES + 1)
        )
        findings, _, _ = boundary.scan_repository(root)
        reasons = {finding.reason for finding in findings}
        self.assertIn("unapproved public file type .log", reasons)
        self.assertIn("text file exceeds scan limit", reasons)

    def test_nested_archive_is_rejected(self) -> None:
        root = self.make_root()
        inner_buffer = io.BytesIO()
        with zipfile.ZipFile(inner_buffer, "w") as inner:
            inner.writestr("data.json", "{}")
        inner_buffer.seek(0)
        with zipfile.ZipFile(root / "plugin-dist" / "release.zip", "w") as outer:
            outer.writestr("plugin/nested.zip", inner_buffer.read())
        findings, _, _ = boundary.scan_repository(root)
        self.assertTrue(
            any(finding.reason == "nested archive is not permitted" for finding in findings)
        )

    def test_zip_symlink_and_duplicate_member_are_rejected(self) -> None:
        root = self.make_root()
        archive_path = root / "plugin-dist" / "release.zip"
        symlink = zipfile.ZipInfo("plugin/link.php")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr(symlink, "target.php")
            archive.writestr("plugin/A.json", "{}")
            archive.writestr("plugin/a.json", "{}")
        findings, _, _ = boundary.scan_repository(root)
        reasons = {finding.reason for finding in findings}
        self.assertIn("ZIP archive has symlink or special member", reasons)
        self.assertIn("ZIP archive has duplicate member path", reasons)

    def test_zip_member_count_and_compression_ratio_are_bounded(self) -> None:
        root = self.make_root()
        member_archive = root / "plugin-dist" / "members.zip"
        with zipfile.ZipFile(member_archive, "w") as archive:
            for index in range(boundary.MAX_ARCHIVE_MEMBERS + 1):
                archive.writestr(f"plugin/{index}.txt", "")
        ratio_archive = root / "plugin-dist" / "ratio.zip"
        with zipfile.ZipFile(
            ratio_archive,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            archive.writestr("plugin/data.txt", b"0" * (1024 * 1024))
        findings, _, _ = boundary.scan_repository(root)
        reasons = {finding.reason for finding in findings}
        self.assertIn("ZIP archive exceeds member-count limit", reasons)
        self.assertIn("ZIP member exceeds compression-ratio limit", reasons)

    def test_missing_repository_sentinels_and_empty_inventory_fail(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        report = boundary.scan_repository_report(Path(temporary.name))
        self.assertGreater(len(report.findings), 0)
        self.assertIn(
            "public repository inventory is empty",
            {finding.reason for finding in report.findings},
        )

    def test_unapproved_3d_derivative_is_rejected(self) -> None:
        root = self.make_root()
        model_path = root / "wp-content" / "assets" / "model.glb"
        model_path.parent.mkdir(parents=True)
        model_path.write_bytes(self.valid_glb())
        findings, _, _ = boundary.scan_repository(root)
        self.assertTrue(
            any(
                finding.reason == "public_3d_derivative lacks disclosure approval"
                for finding in findings
            )
        )

    def test_hash_bound_approved_3d_derivative_passes(self) -> None:
        root = self.make_root()
        relative = "wp-content/assets/model.glb"
        fallback_relative = "wp-content/assets/preview.jpg"
        payload = self.valid_glb()
        fallback_payload = b"\xff\xd8public preview\xff\xd9"
        model_path = root / relative
        model_path.parent.mkdir(parents=True)
        model_path.write_bytes(payload)
        (root / fallback_relative).write_bytes(fallback_payload)
        self.write_asset_manifest(
            root,
            [
                self.asset_approval(
                    relative,
                    payload,
                    "public_3d_derivative",
                    fallback_relative,
                    1,
                ),
                self.asset_approval(
                    fallback_relative,
                    fallback_payload,
                    "public_3d_fallback",
                    relative,
                    2,
                ),
            ],
        )
        report = boundary.scan_repository_report(root)
        self.assertEqual(report.findings, ())
        changed = payload + b"x"
        model_path.write_bytes(changed)
        changed_report = boundary.scan_repository_report(root)
        self.assertTrue(
            any("differs from approval" in finding.reason for finding in changed_report.findings)
        )

    def test_repository_receipt_changes_with_public_bytes(self) -> None:
        root = self.make_root()
        path = root / "wp-content" / "index.html"
        path.write_text("first", encoding="utf-8")
        first = boundary.scan_repository_report(root)
        path.write_text("second", encoding="utf-8")
        second = boundary.scan_repository_report(root)
        self.assertNotEqual(
            first.repository_content_sha256,
            second.repository_content_sha256,
        )

    def test_git_index_private_bytes_cannot_hide_behind_safe_worktree(self) -> None:
        root = self.make_root()
        self.initialize_git(root)
        leak = root / "docs" / "record.json"
        leak.parent.mkdir()
        leak.write_text(
            json.dumps({"record_type": PRIVATE_VERIFICATION_TYPE}),
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "docs/record.json"], cwd=root, check=True)
        leak.write_text('{"title":"safe public record"}', encoding="utf-8")

        report = boundary.scan_repository_report(root)
        self.assertTrue(
            any(
                finding.location == "git-index:/docs/record.json"
                and "private" in finding.reason
                for finding in report.findings
            ),
            report.findings,
        )
        self.assertNotEqual(
            report.git_index_content_sha256,
            report.worktree_content_sha256,
        )

    def test_differing_git_index_objects_receive_complete_type_validation(self) -> None:
        cases = (
            (
                "wp-content/assets/staged-model.glb",
                self.valid_glb(),
                "public_3d_derivative lacks disclosure approval",
            ),
            (
                "wp-content/assets/staged-image.png",
                b"not a PNG",
                "PNG signature is invalid",
            ),
        )
        for relative, payload, expected in cases:
            with self.subTest(relative=relative):
                root = self.make_root()
                self.initialize_git(root)
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
                subprocess.run(["git", "add", relative], cwd=root, check=True)
                path.unlink()

                report = boundary.scan_repository_report(root)
                self.assertIn(
                    boundary.Finding(f"git-index:/{relative}", expected),
                    report.findings,
                )

    def test_staged_manifest_is_applied_to_unchanged_index_assets(self) -> None:
        root = self.make_root()
        relative = "wp-content/assets/model.glb"
        fallback_relative = "wp-content/assets/still.jpg"
        payload = self.valid_glb()
        fallback_payload = b"\xff\xd8public still\xff\xd9"
        path = root / relative
        path.parent.mkdir(parents=True)
        path.write_bytes(payload)
        (root / fallback_relative).write_bytes(fallback_payload)
        self.write_asset_manifest(
            root,
            [
                self.asset_approval(
                    relative,
                    payload,
                    "public_3d_derivative",
                    fallback_relative,
                    1,
                ),
                self.asset_approval(
                    fallback_relative,
                    fallback_payload,
                    "public_3d_fallback",
                    relative,
                    2,
                ),
            ],
        )
        self.initialize_git(root)
        manifest_path = root / boundary.ASSET_MANIFEST_PATH
        worktree_manifest = manifest_path.read_bytes()
        self.write_asset_manifest(root, [])
        subprocess.run(
            ["git", "add", boundary.ASSET_MANIFEST_PATH],
            cwd=root,
            check=True,
        )
        manifest_path.write_bytes(worktree_manifest)

        report = boundary.scan_repository_report(root)
        self.assertIn(
            boundary.Finding(
                f"git-index:/{relative}",
                "public_3d_derivative lacks disclosure approval",
            ),
            report.findings,
        )

    def test_fullwidth_private_identifier_is_normalized_and_rejected(self) -> None:
        root = self.make_root()
        fullwidth = "".join(
            chr(ord(character) + 0xFEE0)
            if "!" <= character <= "~"
            else character
            for character in PRIVATE_SYSTEM_ID
        )
        path = root / "packages" / "publication" / "fullwidth.txt"
        path.write_text(fullwidth, encoding="utf-8")
        findings, _, _ = boundary.scan_repository(root)
        self.assertTrue(
            any(
                finding.reason == "private reference-system identifier"
                for finding in findings
            )
        )

    def test_noncanonical_zip_metadata_and_hidden_bytes_are_rejected(self) -> None:
        root = self.make_root()

        commented = root / "plugin-dist" / "commented.zip"
        with zipfile.ZipFile(commented, "w") as archive:
            archive.comment = b"private archive comment"
            archive.writestr("plugin/index.php", "<?php")

        extra = root / "plugin-dist" / "extra.zip"
        info = zipfile.ZipInfo("plugin/index.php")
        info.extra = b"\x01\x00\x00\x00"
        with zipfile.ZipFile(extra, "w") as archive:
            archive.writestr(info, "<?php")

        prefixed = root / "plugin-dist" / "prefixed.zip"
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("plugin/index.php", "<?php")
        prefixed.write_bytes(b"PREFIX" + buffer.getvalue())

        trailing = root / "plugin-dist" / "trailing.zip"
        trailing.write_bytes(buffer.getvalue() + b"TRAILING")

        findings, _, _ = boundary.scan_repository(root)
        reasons = {finding.reason for finding in findings}
        self.assertIn("ZIP archive comment is not permitted", reasons)
        self.assertIn("ZIP member extra fields are not permitted", reasons)
        self.assertIn("ZIP has prefixed or noncanonical data", reasons)
        self.assertIn("ZIP has trailing or commented data", reasons)

    def test_zip_member_compressed_ranges_cannot_hide_unconsumed_bytes(self) -> None:
        cases = (
            ("stored.zip", zipfile.ZIP_STORED),
            ("deflated.zip", zipfile.ZIP_DEFLATED),
        )
        for name, compression in cases:
            with self.subTest(name=name):
                root = self.make_root()
                (root / "plugin-dist" / name).write_bytes(
                    self.zip_with_hidden_member_bytes(compression)
                )
                report = boundary.scan_repository_report(root)
                self.assertTrue(
                    any(
                        "compressed range has unconsumed bytes" in finding.reason
                        for finding in report.findings
                    ),
                    report.findings,
                )

    def test_glb_bin_chunk_is_scanned_for_private_material(self) -> None:
        payloads = [("ascii", PRIVATE_HAZARD_ID.encode("ascii"))]
        for encoding in ("utf-32-le", "utf-32-be"):
            encoded = PRIVATE_HAZARD_ID.encode(encoding)
            for prefix_bytes in range(8):
                payloads.append(
                    (
                        f"{encoding}-word-prefix-{prefix_bytes}",
                        (b"XYXYXYXY"[:prefix_bytes]) + encoded,
                    )
                )

        for case, bin_payload in payloads:
            with self.subTest(case=case):
                findings = boundary.validate_glb(
                    self.valid_glb(bin_payload=bin_payload),
                    "model.glb",
                )
                self.assertIn(
                    boundary.Finding(
                        "model.glb!/BIN[1]",
                        "private engineering-record identifier",
                    ),
                    findings,
                )

    def test_glb_external_uri_is_rejected(self) -> None:
        root = self.make_root()
        relative = "wp-content/assets/model.glb"
        fallback_relative = "wp-content/assets/preview.jpg"
        payload = self.valid_glb(
            {
                "asset": {"version": "2.0"},
                "buffers": [{"byteLength": 4, "uri": "private.bin"}],
            }
        )
        fallback_payload = b"\xff\xd8public preview\xff\xd9"
        path = root / relative
        path.parent.mkdir(parents=True)
        path.write_bytes(payload)
        (root / fallback_relative).write_bytes(fallback_payload)
        self.write_asset_manifest(
            root,
            [
                self.asset_approval(
                    relative,
                    payload,
                    "public_3d_derivative",
                    fallback_relative,
                    1,
                ),
                self.asset_approval(
                    fallback_relative,
                    fallback_payload,
                    "public_3d_fallback",
                    relative,
                    2,
                ),
            ],
        )
        report = boundary.scan_repository_report(root)
        self.assertIn(
            "GLB must be self-contained and cannot reference URIs",
            {finding.reason for finding in report.findings},
        )

    def test_unused_asset_approval_fails_closed(self) -> None:
        root = self.make_root()
        self.write_asset_manifest(
            root,
            [
                {
                    "approval_id": "PUBLIC-ASSET-APPROVAL-0001",
                    "asset_class": "public_3d_derivative",
                    "bytes": 1,
                    "disclosure_status": "approved_for_public_release",
                    "paired_asset_path": "wp-content/assets/missing-preview.jpg",
                    "path": "wp-content/assets/missing.glb",
                    "public_revision": "PUBLIC-VISUAL-0.1",
                    "rights_status": "approved",
                    "sha256": "a" * 64,
                }
            ],
        )
        report = boundary.scan_repository_report(root)
        self.assertIn(
            "asset approval does not match an inspected public asset",
            {finding.reason for finding in report.findings},
        )

    def test_3d_asset_approvals_require_an_explicit_reciprocal_pair(self) -> None:
        root = self.make_root()
        relative = "wp-content/assets/model.glb"
        fallback_relative = "wp-content/assets/still.jpg"
        payload = self.valid_glb()
        fallback_payload = b"\xff\xd8public still\xff\xd9"
        path = root / relative
        path.parent.mkdir(parents=True)
        path.write_bytes(payload)
        (root / fallback_relative).write_bytes(fallback_payload)
        derivative_approval = self.asset_approval(
            relative,
            payload,
            "public_3d_derivative",
            fallback_relative,
            1,
        )
        fallback_approval = self.asset_approval(
            fallback_relative,
            fallback_payload,
            "public_3d_fallback",
            "wp-content/assets/different.glb",
            2,
        )
        self.write_asset_manifest(
            root,
            [derivative_approval, fallback_approval],
        )
        report = boundary.scan_repository_report(root)
        reasons = {finding.reason for finding in report.findings}
        self.assertIn("public asset relationship is not reciprocal", reasons)
        self.assertIn("paired public asset approval is missing", reasons)

    def test_repository_file_read_is_bounded_before_loading(self) -> None:
        root = self.make_root()
        path = root / "docs" / "oversized.bin"
        path.parent.mkdir()
        with path.open("wb") as handle:
            handle.truncate(boundary.MAX_REPOSITORY_FILE_BYTES + 1)
        report = boundary.scan_repository_report(root)
        self.assertIn(
            "repository file exceeds bounded read limit",
            {finding.reason for finding in report.findings},
        )

    def test_release_mode_writes_hash_bound_receipt_only_for_clean_commit(self) -> None:
        root = self.make_root()
        artifact = root / "plugin-dist" / "public-test-1.0.0.zip"
        with zipfile.ZipFile(artifact, "w") as archive:
            archive.writestr("public-test/index.php", "<?php")
        commit = self.initialize_git(root)
        artifact_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
        receipt = root / "work" / "receipts" / "public-test-1.0.0.json"

        output = io.StringIO()
        with redirect_stdout(output):
            result = boundary.main(
                [
                    "--root",
                    str(root),
                    "--release",
                    "--expected-commit",
                    commit,
                    "--artifact-path",
                    "plugin-dist/public-test-1.0.0.zip",
                    "--artifact-sha256",
                    artifact_hash,
                    "--receipt",
                    str(receipt),
                ]
            )
        self.assertEqual(result, 0, output.getvalue())
        document = json.loads(receipt.read_text(encoding="utf-8"))
        receipt_hash = document.pop("receipt_body_sha256")
        self.assertEqual(
            receipt_hash,
            hashlib.sha256(boundary.canonical_json_bytes(document)).hexdigest(),
        )
        self.assertEqual(document["repository"]["git_head"], commit)
        self.assertEqual(document["artifact"]["sha256"], artifact_hash)

    def test_release_mode_accepts_only_the_approved_root_robots_artifact(self):
        root = self.make_root()
        robots_path = root / "hosting" / "robots.txt"
        robots_path.parent.mkdir()
        robots_path.write_text(
            "User-agent: *\nDisallow:\n",
            encoding="utf-8",
            newline="\n",
        )
        other = root / "hosting" / "security.txt"
        other.write_text(
            "Contact: security@example.invalid\n",
            encoding="utf-8",
        )
        commit = self.initialize_git(root)
        robots_hash = hashlib.sha256(
            robots_path.read_bytes()
        ).hexdigest()
        receipt = root / "work" / "receipts" / "robots.json"

        with redirect_stdout(io.StringIO()):
            result = boundary.main(
                [
                    "--root",
                    str(root),
                    "--release",
                    "--expected-commit",
                    commit,
                    "--artifact-path",
                    "hosting/robots.txt",
                    "--artifact-sha256",
                    robots_hash,
                    "--receipt",
                    str(receipt),
                ]
            )

        self.assertEqual(result, 0)
        document = json.loads(receipt.read_text(encoding="utf-8"))
        self.assertEqual(
            document["artifact"],
            {
                "path": "hosting/robots.txt",
                "sha256": robots_hash,
            },
        )

        with redirect_stdout(io.StringIO()):
            rejected = boundary.main(
                [
                    "--root",
                    str(root),
                    "--release",
                    "--expected-commit",
                    commit,
                    "--artifact-path",
                    "hosting/security.txt",
                    "--artifact-sha256",
                    hashlib.sha256(other.read_bytes()).hexdigest(),
                    "--receipt",
                    str(root / "work" / "receipts" / "security.json"),
                ]
            )
        self.assertEqual(rejected, 1)

    def test_release_mode_rejects_missing_artifact_path(self) -> None:
        root = self.make_root()
        commit = self.initialize_git(root)
        receipt = root / "work" / "receipts" / "unbound.json"
        output = io.StringIO()

        with redirect_stdout(output):
            result = boundary.main(
                [
                    "--root",
                    str(root),
                    "--release",
                    "--expected-commit",
                    commit,
                    "--artifact-sha256",
                    "a" * 64,
                    "--receipt",
                    str(receipt),
                ]
            )

        self.assertEqual(result, 1)
        self.assertFalse(receipt.exists())
        document = json.loads(output.getvalue())
        self.assertIn(
            {
                "location": "--artifact-path",
                "reason": "release mode requires an inspected artifact path",
            },
            document["findings"],
        )

    def test_release_mode_rejects_dirty_repository_and_writes_no_receipt(self) -> None:
        root = self.make_root()
        artifact = root / "plugin-dist" / "public-test-1.0.0.zip"
        with zipfile.ZipFile(artifact, "w") as archive:
            archive.writestr("public-test/index.php", "<?php")
        commit = self.initialize_git(root)
        (root / "AGENTS.md").write_text("dirty", encoding="utf-8")
        receipt = root / "work" / "receipts" / "public-test-1.0.0.json"

        with redirect_stdout(io.StringIO()):
            result = boundary.main(
                [
                    "--root",
                    str(root),
                    "--release",
                    "--expected-commit",
                    commit,
                    "--artifact-path",
                    "plugin-dist/public-test-1.0.0.zip",
                    "--artifact-sha256",
                    hashlib.sha256(artifact.read_bytes()).hexdigest(),
                    "--receipt",
                    str(receipt),
                ]
            )
        self.assertEqual(result, 1)
        self.assertFalse(receipt.exists())


if __name__ == "__main__":
    unittest.main()
