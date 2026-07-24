import hashlib
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPOSITORY_ROOT / "scripts" / "deploy-wordpress.py"
SPEC = importlib.util.spec_from_file_location("deploy_wordpress", MODULE_PATH)
deploy = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(deploy)
ROUTE_TEMPLATE_PAYLOAD = (
    REPOSITORY_ROOT
    / "scripts"
    / "templates"
    / "deploy-route.php.txt"
).read_bytes()


class DeployWordPressTests(unittest.TestCase):
    BOUNDARY_NOW = datetime(
        2026,
        7,
        24,
        10,
        35,
        tzinfo=timezone.utc,
    )

    def make_boundary_receipt(self) -> dict:
        receipt = {
            "schema_version": 1,
            "receipt_type": deploy.BOUNDARY_RECEIPT_TYPE,
            "release_mode": True,
            "created_at": "2026-07-24T10:30:00Z",
            "repository": {
                "git_head": "d" * 40,
                "git_dirty": False,
                "git_index_content_sha256": "f" * 64,
                "worktree_content_sha256": "f" * 64,
            },
            "public_boundary": {
                "repository_content_sha256": "f" * 64,
                "asset_manifest_sha256": "b" * 64,
                "public_snapshot_payload_sha256": "c" * 64,
                "finding_count": 0,
            },
            "artifact": {
                "path": "plugin-dist/robbottx-core-0.1.3.zip",
                "sha256": "a" * 64,
            },
        }
        receipt["receipt_body_sha256"] = self.boundary_receipt_body_sha256(
            receipt
        )
        return receipt

    def make_boundary_scan_report(self, **overrides) -> SimpleNamespace:
        values = {
            "findings": (),
            "git_head": "d" * 40,
            "git_dirty": False,
            "git_index_content_sha256": "f" * 64,
            "worktree_content_sha256": "f" * 64,
            "repository_content_sha256": "f" * 64,
            "asset_manifest_sha256": "b" * 64,
            "public_snapshot_payload_sha256": "c" * 64,
            "release_artifacts": (
                (
                    "plugin-dist/robbottx-core-0.1.3.zip",
                    "a" * 64,
                ),
            ),
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def validate_boundary_receipt(
        self,
        receipt: dict,
        *,
        scan_report: object | None = None,
    ) -> dict[str, str]:
        return deploy.validate_boundary_receipt(
            self.write_boundary_receipt(receipt),
            version="0.1.3",
            slug="robbottx-core",
            zip_sha256="a" * 64,
            record_hash="c" * 64,
            current_time=self.BOUNDARY_NOW,
            scan_report=scan_report or self.make_boundary_scan_report(),
        )

    def boundary_receipt_body_sha256(self, receipt: dict) -> str:
        body = {
            key: value
            for key, value in receipt.items()
            if key != "receipt_body_sha256"
        }
        encoded = json.dumps(
            body,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def write_boundary_receipt(self, receipt: dict) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "boundary-release-receipt.json"
        path.write_text(
            json.dumps(receipt, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return path

    def test_boundary_receipt_accepts_valid_release(self):
        receipt = self.make_boundary_receipt()
        result = self.validate_boundary_receipt(receipt)

        self.assertEqual(
            result["receipt_body_sha256"],
            receipt["receipt_body_sha256"],
        )
        self.assertEqual(result["git_head"], "d" * 40)
        self.assertEqual(
            result["artifact_path"],
            "plugin-dist/robbottx-core-0.1.3.zip",
        )

    def test_boundary_receipt_accepts_only_the_approved_root_robots_path(self):
        receipt = self.make_boundary_receipt()
        receipt["artifact"]["path"] = "hosting/robots.txt"
        receipt["receipt_body_sha256"] = (
            self.boundary_receipt_body_sha256(receipt)
        )
        scan_report = self.make_boundary_scan_report(
            release_artifacts=(("hosting/robots.txt", "a" * 64),)
        )

        result = deploy.validate_boundary_receipt(
            self.write_boundary_receipt(receipt),
            version="robots",
            slug="hosting",
            zip_sha256="a" * 64,
            record_hash="c" * 64,
            artifact_path="hosting/robots.txt",
            current_time=self.BOUNDARY_NOW,
            scan_report=scan_report,
        )

        self.assertEqual(result["artifact_path"], "hosting/robots.txt")
        with self.assertRaises(deploy.DeployFailure):
            deploy.validate_boundary_receipt(
                self.write_boundary_receipt(receipt),
                version="robots",
                slug="hosting",
                zip_sha256="a" * 64,
                record_hash="c" * 64,
                artifact_path="hosting/security.txt",
                current_time=self.BOUNDARY_NOW,
                scan_report=scan_report,
            )

    def test_boundary_receipt_rejects_tampered_body(self):
        receipt = self.make_boundary_receipt()
        receipt["artifact"]["sha256"] = "b" * 64

        with self.assertRaises(deploy.DeployFailure) as raised:
            self.validate_boundary_receipt(receipt)

        self.assertIn("body hash does not match", str(raised.exception))

    def test_boundary_receipt_rejects_release_mismatches(self):
        mutations = {
            "artifact path": lambda receipt: receipt["artifact"].update(
                {"path": "plugin-dist/other-0.1.3.zip"}
            ),
            "artifact hash": lambda receipt: receipt["artifact"].update(
                {"sha256": "b" * 64}
            ),
            "public snapshot hash": lambda receipt: receipt[
                "public_boundary"
            ].update({"public_snapshot_payload_sha256": "b" * 64}),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                receipt = self.make_boundary_receipt()
                mutate(receipt)
                receipt["receipt_body_sha256"] = (
                    self.boundary_receipt_body_sha256(receipt)
                )
                with self.assertRaises(deploy.DeployFailure) as raised:
                    self.validate_boundary_receipt(receipt)
                self.assertIn(
                    "does not match the reviewed release",
                    str(raised.exception),
                )

    def test_boundary_receipt_rejects_divergent_repository_inventories(self):
        receipt = self.make_boundary_receipt()
        receipt["repository"]["git_index_content_sha256"] = "e" * 64
        receipt["receipt_body_sha256"] = self.boundary_receipt_body_sha256(
            receipt
        )

        with self.assertRaises(deploy.DeployFailure) as raised:
            self.validate_boundary_receipt(receipt)

        self.assertIn("did not pass the release gate", str(raised.exception))

    def test_boundary_receipt_rejects_year_2000_timestamp(self):
        receipt = self.make_boundary_receipt()
        receipt["created_at"] = "2000-01-01T00:00:00Z"
        receipt["receipt_body_sha256"] = self.boundary_receipt_body_sha256(
            receipt
        )

        with self.assertRaises(deploy.DeployFailure) as raised:
            self.validate_boundary_receipt(receipt)

        self.assertIn("outside the release window", str(raised.exception))

    def test_boundary_receipt_rejects_future_timestamp(self):
        receipt = self.make_boundary_receipt()
        receipt["created_at"] = "2026-07-24T10:35:01Z"
        receipt["receipt_body_sha256"] = self.boundary_receipt_body_sha256(
            receipt
        )

        with self.assertRaises(deploy.DeployFailure) as raised:
            self.validate_boundary_receipt(receipt)

        self.assertIn("outside the release window", str(raised.exception))

    def test_fabricated_self_consistent_receipt_cannot_replace_current_scan(self):
        receipt = self.make_boundary_receipt()
        fabricated_current_report = self.make_boundary_scan_report(
            git_head="e" * 40,
            git_index_content_sha256="9" * 64,
            worktree_content_sha256="9" * 64,
            repository_content_sha256="9" * 64,
            asset_manifest_sha256="8" * 64,
        )

        with self.assertRaises(deploy.DeployFailure) as raised:
            self.validate_boundary_receipt(
                receipt,
                scan_report=fabricated_current_report,
            )

        self.assertIn(
            "does not match the current reviewed repository",
            str(raised.exception),
        )

    def test_boundary_receipt_rejects_dirty_or_different_current_head(self):
        cases = {
            "dirty": self.make_boundary_scan_report(git_dirty=True),
            "different head": self.make_boundary_scan_report(
                git_head="e" * 40
            ),
        }
        for label, scan_report in cases.items():
            with self.subTest(label=label):
                receipt = self.make_boundary_receipt()
                with self.assertRaises(deploy.DeployFailure):
                    self.validate_boundary_receipt(
                        receipt,
                        scan_report=scan_report,
                    )

    def test_created_snippet_id_requires_a_positive_plain_integer(self):
        self.assertEqual(deploy.parse_created_snippet_id({"id": 73}), 73)

        invalid_responses = [
            {},
            {"id": "sentinel-private-id"},
            {"id": True},
            {"id": False},
            {"id": 0},
            {"id": -1},
            {"id": 73.0},
            {"id": None},
        ]
        expected = "Temporary route creation returned no usable snippet ID."
        for response in invalid_responses:
            with self.subTest(response=response):
                with self.assertRaises(deploy.DeployFailure) as raised:
                    deploy.parse_created_snippet_id(response)
                self.assertEqual(str(raised.exception), expected)
                self.assertNotIn(
                    "sentinel-private-id",
                    str(raised.exception),
                )

    def test_callback_requires_one_exact_unambiguous_confirmation(self):
        exact = json.dumps(
            {
                "result": True,
                "active": True,
                "version": "0.1.3",
                "artifact_verified": True,
            }
        )
        parsed = deploy.verify_deploy_callback(
            200,
            "application/json; charset=UTF-8",
            exact,
            expected_version="0.1.3",
        )
        self.assertTrue(parsed["artifact_verified"])

        ambiguous_responses = {
            "artifact not confirmed": json.dumps(
                {
                    "result": True,
                    "active": True,
                    "version": "0.1.3",
                    "artifact_verified": False,
                }
            ),
            "extra result field": json.dumps(
                {
                    "result": True,
                    "active": True,
                    "version": "0.1.3",
                    "artifact_verified": True,
                    "status": "ok",
                }
            ),
            "duplicate result": (
                '{"result":true,"result":true,"active":true,'
                '"version":"0.1.3","artifact_verified":true}'
            ),
        }
        for label, response in ambiguous_responses.items():
            with self.subTest(label=label):
                with self.assertRaises(deploy.DeployFailure):
                    deploy.verify_deploy_callback(
                        200,
                        "application/json",
                        response,
                        expected_version="0.1.3",
                    )

    def test_cli_redacts_unexpected_exception_details_and_emits_no_evidence(self):
        stderr = io.StringIO()
        stdout = io.StringIO()
        with (
            patch.object(
                deploy,
                "main",
                side_effect=RuntimeError("sentinel-private-response"),
            ),
            redirect_stderr(stderr),
            redirect_stdout(stdout),
        ):
            result = deploy.run_cli()

        self.assertEqual(result, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(
            stderr.getvalue(),
            "Deployment failed: "
            "Plugin deployment failed with RuntimeError.\n",
        )
        self.assertNotIn("sentinel-private-response", stderr.getvalue())

    def test_boundary_gate_runs_before_wordpress_environment_or_network(self):
        args = Namespace(
            version="0.1.3",
            plugin_slug="robbottx-core",
            zip_sha256="a" * 64,
            record_hash="c" * 64,
            boundary_receipt=Path("boundary-release-receipt.json"),
        )
        with (
            patch.object(deploy, "parse_args", return_value=args),
            patch.object(
                deploy,
                "validate_boundary_receipt",
                side_effect=deploy.DeployFailure("boundary rejected"),
            ),
            patch.object(deploy, "required_env") as env_mock,
            patch.object(deploy, "request") as request_mock,
            self.assertRaises(deploy.DeployFailure),
        ):
            deploy.main()

        env_mock.assert_not_called()
        request_mock.assert_not_called()

    def test_reviewed_route_template_loads_before_wordpress_environment(self):
        args = Namespace(
            version="0.1.3",
            plugin_slug="robbottx-core",
            zip_sha256="a" * 64,
            record_hash="c" * 64,
            boundary_receipt=Path("boundary-release-receipt.json"),
        )
        order = []

        def validate_receipt(*_args, **_kwargs):
            order.append("boundary")
            return {"git_head": "d" * 40}

        def read_reviewed(*_args, **_kwargs):
            order.append("template")
            return ROUTE_TEMPLATE_PAYLOAD, "d" * 40

        def read_environment(_name):
            order.append("environment")
            raise deploy.DeployFailure("stop after ordering proof")

        with (
            patch.object(deploy, "parse_args", return_value=args),
            patch.object(
                deploy,
                "validate_boundary_receipt",
                side_effect=validate_receipt,
            ),
            patch.object(
                deploy,
                "read_clean_index_file",
                side_effect=read_reviewed,
            ),
            patch.object(
                deploy,
                "required_env",
                side_effect=read_environment,
            ),
            patch.object(deploy, "request") as request_mock,
            self.assertRaises(deploy.DeployFailure),
        ):
            deploy.main()

        self.assertEqual(order, ["boundary", "template", "environment"])
        request_mock.assert_not_called()

    def test_expired_boundary_is_rejected_again_at_mutation_time(self):
        args = Namespace(
            version="0.1.3",
            plugin_slug="robbottx-core",
            zip_sha256="a" * 64,
            record_hash="c" * 64,
            boundary_receipt=Path("boundary-release-receipt.json"),
        )
        initial_identity = {
            "receipt_body_sha256": "e" * 64,
            "git_head": "d" * 40,
            "artifact_path": "plugin-dist/robbottx-core-0.1.3.zip",
        }
        with (
            patch.object(
                deploy,
                "validate_boundary_receipt",
                side_effect=deploy.DeployFailure(
                    "Public boundary release receipt has expired."
                ),
            ),
            patch.object(deploy, "request") as request_mock,
            self.assertRaises(deploy.DeployFailure) as raised,
        ):
            deploy.require_current_boundary_for_mutation(
                args,
                initial_identity,
                "d" * 40,
            )

        self.assertIn("expired", str(raised.exception))
        request_mock.assert_not_called()

    def test_clean_index_loader_rejects_a_dirty_executable_replacement(self):
        git_executable = deploy.resolve_trusted_git_executable()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "scripts" / "reviewed.py"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"REVIEWED = True\n")
            (root / ".gitattributes").write_text(
                "* text=auto eol=lf\n",
                encoding="utf-8",
            )
            subprocess.run(
                [str(git_executable), "-C", str(root), "init", "-q"],
                check=True,
            )
            subprocess.run(
                [str(git_executable), "-C", str(root), "add", "."],
                check=True,
            )
            subprocess.run(
                [
                    str(git_executable),
                    "-C",
                    str(root),
                    "-c",
                    "user.name=RobbottX Test",
                    "-c",
                    "user.email=test@invalid.example",
                    "commit",
                    "-q",
                    "-m",
                    "fixture",
                ],
                check=True,
            )

            payload, head = deploy.read_clean_index_file(
                root,
                "scripts/reviewed.py",
                max_bytes=1024,
            )
            self.assertEqual(payload, b"REVIEWED = True\n")
            self.assertRegex(head, r"^[0-9a-f]{40}$")

            target.write_bytes(
                b"raise RuntimeError('must never execute')\n"
            )
            with self.assertRaises(deploy.DeployFailure) as raised:
                deploy.read_clean_index_file(
                    root,
                    "scripts/reviewed.py",
                    max_bytes=1024,
                )
            self.assertIn(
                "must be clean",
                str(raised.exception),
            )

    def test_boundary_scanner_git_calls_use_absolute_allowlisted_execution(self):
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs
            return SimpleNamespace(
                returncode=0,
                stdout="d" * 40,
                stderr="",
            )

        git_executable = Path("C:/Program Files/Git/cmd/git.exe")
        proxy = deploy._TrustedGitSubprocess(
            fake_run,
            git_executable,
            REPOSITORY_ROOT.resolve(),
        )
        proxy.run(
            [
                "git",
                "-C",
                str(REPOSITORY_ROOT),
                "rev-parse",
                "HEAD",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(captured["command"][0], str(git_executable))
        child_environment = captured["kwargs"]["env"]
        self.assertNotIn("WP_APP_PASSWORD", child_environment)
        self.assertNotIn("GIT_DIR", child_environment)
        self.assertEqual(
            captured["kwargs"]["timeout"],
            deploy.TRUSTED_GIT_TIMEOUT_SECONDS,
        )
        with self.assertRaises(OSError):
            proxy.run(
                ["git", "-C", str(REPOSITORY_ROOT), "push"],
                capture_output=True,
            )

    def test_main_redacts_unexpected_create_failure_after_cleanup(self):
        args = Namespace(
            version="0.1.3",
            zip_url=(
                f"{deploy.EXPECTED_RAW_ROOT}/"
                "robbottx-core-0.1.3.zip"
            ),
            manifest_url=(
                f"{deploy.EXPECTED_RAW_ROOT}/robbottx-core.json"
            ),
            inventory_url="",
            zip_sha256="a" * 64,
            zip_size=1,
            record_hash="c" * 64,
            boundary_receipt=Path("boundary-release-receipt.json"),
            package_marker="release-marker-0.1.3",
            plugin_slug="robbottx-core",
            plugin_main_file="robbottx-core.php",
            version_constant="ROBBOTTX_CORE_VERSION",
            health_path="/wp-json/robbottx/v1/healthcheck",
            render_path="/",
            new_body_marker="",
            old_body_marker="<!-- robbottx-core:0.1.2 -->",
            execute=True,
        )
        environment = {
            "WP_BASE_URL": "https://robbottx.com",
            "WP_USER": "release-operator",
            "WP_APP_PASSWORD": "sentinel-private-password",
        }

        def request_side_effect(url, **kwargs):
            if "/wp/v2/users/me?" in url:
                return (
                    200,
                    "application/json",
                    json.dumps(
                        {
                            "id": 7,
                            "roles": ["administrator"],
                            "capabilities": {"update_plugins": True},
                        }
                    ),
                )
            if (
                url.endswith("/wp-json/code-snippets/v1/snippets")
                and kwargs.get("method") == "POST"
            ):
                raise RuntimeError("sentinel-private-create-response")
            raise AssertionError(f"Unexpected mocked request: {url}")

        with (
            patch.object(deploy, "parse_args", return_value=args),
            patch.object(
                deploy,
                "required_env",
                side_effect=lambda name: environment[name],
            ),
            patch.object(
                deploy,
                "validate_boundary_receipt",
                return_value={"git_head": "d" * 40},
            ),
            patch.object(
                deploy,
                "read_clean_index_file",
                return_value=(ROUTE_TEMPLATE_PAYLOAD, "d" * 40),
            ),
            patch.object(deploy, "request", side_effect=request_side_effect),
            patch.object(deploy, "load_public_json", return_value={}),
            patch.object(
                deploy,
                "verify_manifest",
                return_value={"manifest_version": "0.1.3"},
            ),
            patch.object(
                deploy,
                "request_bytes",
                return_value=(
                    200,
                    "application/zip",
                    b"x",
                    args.zip_url,
                ),
            ),
            patch.object(deploy, "verify_public_download_location"),
            patch.object(
                deploy,
                "verify_plugin_zip",
                return_value={
                    "files": [],
                    "zip_bytes": 1,
                    "zip_sha256": "a" * 64,
                    "zip_files": 0,
                },
            ),
            patch.object(
                deploy,
                "verify_inventory",
                return_value={"inventory_files": 0},
            ),
            patch.object(
                deploy,
                "require_snippet_capacity",
                return_value=7,
            ),
            patch.object(deploy, "require_route_not_registered"),
            patch.object(deploy, "require_deploy_route_absent"),
            patch.object(
                deploy,
                "find_snippet_ids_by_name",
                return_value=([], []),
            ),
            patch.object(
                deploy,
                "cleanup_temporary_snippets",
                return_value=(True, []),
            ),
            patch.object(
                deploy,
                "prove_deploy_route_absent",
                return_value=(True, []),
            ),
            patch.object(deploy.time, "time", return_value=1700000000),
            patch.object(
                deploy.secrets,
                "token_hex",
                return_value="aabbccddeeff0011",
            ),
        ):
            with self.assertRaises(deploy.DeployFailure) as raised:
                deploy.main()

        self.assertEqual(
            str(raised.exception),
            "Plugin deployment failed with RuntimeError.",
        )
        self.assertNotIn(
            "sentinel-private-create-response",
            str(raised.exception),
        )
        self.assertNotIn(
            "sentinel-private-password",
            str(raised.exception),
        )

    def test_health_marker_cannot_override_ambiguous_callback(self):
        args = Namespace(
            version="0.1.3",
            zip_url=(
                f"{deploy.EXPECTED_RAW_ROOT}/"
                "robbottx-core-0.1.3.zip"
            ),
            manifest_url=(
                f"{deploy.EXPECTED_RAW_ROOT}/robbottx-core.json"
            ),
            inventory_url="",
            zip_sha256="a" * 64,
            zip_size=1,
            record_hash="c" * 64,
            boundary_receipt=Path("boundary-release-receipt.json"),
            package_marker="release-marker-0.1.3",
            plugin_slug="robbottx-core",
            plugin_main_file="robbottx-core.php",
            version_constant="ROBBOTTX_CORE_VERSION",
            health_path="/wp-json/robbottx/v1/healthcheck",
            render_path="/",
            new_body_marker="",
            old_body_marker="<!-- robbottx-core:0.1.2 -->",
            execute=True,
        )
        environment = {
            "WP_BASE_URL": "https://robbottx.com",
            "WP_USER": "release-operator",
            "WP_APP_PASSWORD": "sentinel-private-password",
        }
        health_requested = False

        def request_side_effect(url, **kwargs):
            nonlocal health_requested
            if "/wp/v2/users/me?" in url:
                return (
                    200,
                    "application/json",
                    json.dumps(
                        {
                            "id": 7,
                            "roles": ["administrator"],
                            "capabilities": {"update_plugins": True},
                        }
                    ),
                )
            if (
                url.endswith("/wp-json/code-snippets/v1/snippets")
                and kwargs.get("method") == "POST"
            ):
                return (201, "application/json", '{"id":73}')
            if "/wp-json/agentdeploy/v1/run-" in url:
                return (
                    200,
                    "application/json",
                    json.dumps(
                        {
                            "result": True,
                            "active": True,
                            "version": "0.1.3",
                            "artifact_verified": False,
                        }
                    ),
                )
            if "/wp-json/robbottx/v1/healthcheck" in url:
                health_requested = True
                return (
                    200,
                    "application/json",
                    json.dumps(
                        {
                            "status": "ok",
                            "version": "0.1.3",
                            "record_hash": "c" * 64,
                        }
                    ),
                )
            raise AssertionError(f"Unexpected mocked request: {url}")

        with (
            patch.object(deploy, "parse_args", return_value=args),
            patch.object(
                deploy,
                "required_env",
                side_effect=lambda name: environment[name],
            ),
            patch.object(
                deploy,
                "validate_boundary_receipt",
                return_value={"git_head": "d" * 40},
            ),
            patch.object(
                deploy,
                "read_clean_index_file",
                return_value=(ROUTE_TEMPLATE_PAYLOAD, "d" * 40),
            ),
            patch.object(deploy, "request", side_effect=request_side_effect),
            patch.object(deploy, "load_public_json", return_value={}),
            patch.object(
                deploy,
                "verify_manifest",
                return_value={"manifest_version": "0.1.3"},
            ),
            patch.object(
                deploy,
                "request_bytes",
                return_value=(
                    200,
                    "application/zip",
                    b"x",
                    args.zip_url,
                ),
            ),
            patch.object(deploy, "verify_public_download_location"),
            patch.object(
                deploy,
                "verify_plugin_zip",
                return_value={
                    "files": [],
                    "zip_bytes": 1,
                    "zip_sha256": "a" * 64,
                    "zip_files": 0,
                },
            ),
            patch.object(
                deploy,
                "verify_inventory",
                return_value={"inventory_files": 0},
            ),
            patch.object(
                deploy,
                "require_snippet_capacity",
                return_value=7,
            ),
            patch.object(deploy, "require_route_not_registered"),
            patch.object(deploy, "require_deploy_route_absent"),
            patch.object(
                deploy,
                "find_snippet_ids_by_name",
                return_value=([], []),
            ),
            patch.object(
                deploy,
                "cleanup_temporary_snippets",
                return_value=(True, []),
            ) as cleanup_mock,
            patch.object(
                deploy,
                "prove_deploy_route_absent",
                return_value=(True, []),
            ),
            patch.object(deploy.time, "time", return_value=1700000000),
            patch.object(
                deploy.secrets,
                "token_hex",
                return_value="aabbccddeeff0011",
            ),
        ):
            with self.assertRaises(deploy.DeployFailure) as raised:
                deploy.main()

        self.assertIn(
            "did not exactly confirm the bound release",
            str(raised.exception),
        )
        self.assertFalse(health_requested)
        cleanup_mock.assert_called_once()

    def test_snippet_capacity_allows_98_and_rejects_99(self):
        with patch.object(
            deploy,
            "request",
            return_value=(
                200,
                "application/json; charset=UTF-8",
                json.dumps([{"id": index + 1} for index in range(98)]),
            ),
        ):
            self.assertEqual(
                deploy.require_snippet_capacity(
                    "https://robbottx.com",
                    "Basic redacted",
                ),
                98,
            )

        with patch.object(
            deploy,
            "request",
            return_value=(
                200,
                "application/json",
                json.dumps([{"id": index + 1} for index in range(99)]),
            ),
        ):
            with self.assertRaises(deploy.DeployFailure):
                deploy.require_snippet_capacity(
                    "https://robbottx.com",
                    "Basic redacted",
                )

    def test_stale_route_refuses_precreate(self):
        with patch.object(
            deploy,
            "prove_deploy_route_absent",
            return_value=(False, ["absence attempt 1 returned HTTP 200"]),
        ):
            with self.assertRaises(deploy.DeployFailure) as raised:
                deploy.require_deploy_route_absent(
                    "https://example.test",
                    "Basic redacted",
                    "/wp-json/agentdeploy/v1/run-unique",
                    "Pre-create verification",
                )

        self.assertIn("Pre-create verification", str(raised.exception))

    def test_cleanup_recovers_created_snippet_by_unique_name(self):
        with (
            patch.object(
                deploy,
                "find_snippet_ids_by_name",
                side_effect=[([91], []), ([], [])],
            ),
            patch.object(
                deploy,
                "delete_temporary_snippet",
                return_value=(True, []),
            ) as delete_mock,
        ):
            cleaned, failures = deploy.cleanup_temporary_snippets(
                "https://example.test",
                "Basic redacted",
                "tmp-robbottx-deploy-unique",
                None,
            )

        self.assertTrue(cleaned)
        self.assertEqual(failures, [])
        delete_mock.assert_called_once_with(
            "https://example.test",
            91,
            "Basic redacted",
        )

    def test_cleanup_never_deletes_unowned_create_response_id(self):
        with (
            patch.object(
                deploy,
                "find_snippet_ids_by_name",
                side_effect=[([91], []), ([], [])],
            ),
            patch.object(
                deploy,
                "snippet_record_has_exact_name",
                return_value=(False, []),
            ),
            patch.object(
                deploy,
                "delete_temporary_snippet",
                return_value=(True, []),
            ) as delete_mock,
        ):
            cleaned, failures = deploy.cleanup_temporary_snippets(
                "https://example.test",
                "Basic redacted",
                "tmp-robbottx-deploy-unique",
                7,
            )

        self.assertTrue(cleaned)
        self.assertEqual(failures, [])
        delete_mock.assert_called_once_with(
            "https://example.test",
            91,
            "Basic redacted",
        )

    def test_snippet_lookup_matches_exact_unique_name(self):
        response = json.dumps(
            [
                {"id": 7, "name": "tmp-robbottx-deploy-other"},
                {"id": 8, "name": "tmp-robbottx-deploy-unique"},
            ]
        )
        with patch.object(
            deploy,
            "request",
            return_value=(200, "application/json", response),
        ):
            matches, failures = deploy.find_snippet_ids_by_name(
                "https://example.test",
                "tmp-robbottx-deploy-unique",
                "Basic redacted",
            )

        self.assertEqual(matches, [8])
        self.assertEqual(failures, [])

    def test_public_zip_requires_exact_hash_size_root_version_and_marker(self):
        record_hash = "c" * 64
        archive_buffer = io.BytesIO()
        with ZipFile(
            archive_buffer,
            "w",
            compression=ZIP_DEFLATED,
        ) as archive:
            archive.writestr(
                "robbottx-core/robbottx-core.php",
                "<?php\n/**\n * Version: 0.1.3\n */\n"
                "define('ROBBOTTX_CORE_VERSION', '0.1.3');\n",
            )
            archive.writestr(
                "robbottx-core/src/Presentation/Assets.php",
                f"overflow-wrap: anywhere\n{record_hash}",
            )

        archive_bytes = archive_buffer.getvalue()
        digest = hashlib.sha256(archive_bytes).hexdigest()
        result = deploy.verify_plugin_zip(
            archive_bytes,
            expected_size=len(archive_bytes),
            expected_sha256=digest,
            slug="robbottx-core",
            main_file="robbottx-core.php",
            version="0.1.3",
            version_constant="ROBBOTTX_CORE_VERSION",
            package_marker="overflow-wrap: anywhere",
            expected_record_hash=record_hash,
        )
        self.assertEqual(result["zip_sha256"], digest)
        self.assertEqual(len(result["files"]), 2)

        with self.assertRaises(deploy.DeployFailure):
            deploy.verify_plugin_zip(
                archive_bytes,
                expected_size=len(archive_bytes),
                expected_sha256="0" * 64,
                slug="robbottx-core",
                main_file="robbottx-core.php",
                version="0.1.3",
                version_constant="ROBBOTTX_CORE_VERSION",
                package_marker="overflow-wrap: anywhere",
                expected_record_hash=record_hash,
            )

    def test_route_absence_requires_wordpress_json_rest_no_route(self):
        trusted = json.dumps(
            {
                "code": "rest_no_route",
                "message": "No route.",
                "data": {"status": 404},
            }
        )
        with patch.object(
            deploy,
            "request",
            return_value=(404, "application/json; charset=UTF-8", trusted),
        ):
            absent, failures = deploy.prove_deploy_route_absent(
                "https://example.test",
                "Basic redacted",
                "/wp-json/agentdeploy/v1/run-unique",
                attempts=1,
            )
        self.assertTrue(absent)
        self.assertEqual(failures, [])

        with patch.object(
            deploy,
            "request",
            return_value=(404, "text/html", "<h1>nginx</h1>"),
        ):
            absent, failures = deploy.prove_deploy_route_absent(
                "https://example.test",
                "Basic redacted",
                "/wp-json/agentdeploy/v1/run-unique",
                attempts=1,
            )
        self.assertFalse(absent)
        self.assertTrue(failures)

    def test_snippet_delete_requires_independent_record_absence(self):
        deleted = json.dumps({"success": True})
        absent = json.dumps(
            {
                "code": "rest_cannot_get",
                "message": "The snippet could not be found.",
                "data": {"status": 500},
            }
        )
        with patch.object(
            deploy,
            "request",
            side_effect=[
                (200, "application/json", deleted),
                (500, "application/json", absent),
            ],
        ):
            success, failures = deploy.delete_temporary_snippet(
                "https://example.test",
                91,
                "Basic redacted",
                attempts=1,
            )
        self.assertTrue(success)
        self.assertEqual(failures, [])

    def test_snippet_absence_accepts_code_snippets_verified_missing_shape(self):
        missing = json.dumps(
            {
                "code": "rest_cannot_get",
                "message": "The snippet could not be found.",
                "data": {"status": 500},
            }
        )
        with patch.object(
            deploy,
            "request",
            return_value=(500, "application/json; charset=UTF-8", missing),
        ):
            absent, failure = deploy.prove_snippet_record_absent(
                "https://example.test",
                91,
                "Basic redacted",
            )
        self.assertTrue(absent)
        self.assertEqual(failure, "")

        wrong_message = json.dumps(
            {
                "code": "rest_cannot_get",
                "message": "Different error.",
                "data": {"status": 500},
            }
        )
        with patch.object(
            deploy,
            "request",
            return_value=(
                500,
                "application/json; charset=UTF-8",
                wrong_message,
            ),
        ):
            absent, failure = deploy.prove_snippet_record_absent(
                "https://example.test",
                91,
                "Basic redacted",
            )
        self.assertFalse(absent)
        self.assertIn("HTTP 500", failure)

    def test_manifest_and_inventory_must_match_exact_release(self):
        digest = "a" * 64
        zip_url = (
            f"{deploy.EXPECTED_RAW_ROOT}/robbottx-core-0.1.3.zip"
        )
        inventory_url = (
            f"{deploy.EXPECTED_RAW_ROOT}/"
            "robbottx-core-0.1.3.inventory.json"
        )
        manifest = {
            "name": "RobbottX Core",
            "slug": "robbottx-core",
            "version": "0.1.3",
            "author": "RobbottX",
            "homepage": "https://robbottx.com/",
            "requires": "6.9",
            "tested": "7.0",
            "requires_php": "8.3",
            "download_url": zip_url,
            "download_sha256": digest,
            "download_size": 123,
            "inventory_url": inventory_url,
            "record_hash": "c" * 64,
            "last_updated": "2026-07-23 20:00:00",
            "sections": {"changelog": "<h4>0.1.3</h4>"},
        }
        deploy.verify_manifest(
            manifest,
            version="0.1.3",
            slug="robbottx-core",
            zip_url=zip_url,
            zip_sha256=digest,
            zip_size=123,
            inventory_url=inventory_url,
            record_hash="c" * 64,
        )
        files = [
            {
                "path": "robbottx-core/robbottx-core.php",
                "bytes": 10,
                "sha256": "b" * 64,
            }
        ]
        deploy.verify_inventory(
            {
                "artifact": "robbottx-core-0.1.3.zip",
                "version": "0.1.3",
                "zip_sha256": digest,
                "zip_bytes": 123,
                "files": files,
            },
            version="0.1.3",
            slug="robbottx-core",
            zip_sha256=digest,
            zip_size=123,
            packaged_files=files,
        )

        broken = dict(manifest)
        broken["download_size"] = 122
        with self.assertRaises(deploy.DeployFailure):
            deploy.verify_manifest(
                broken,
                version="0.1.3",
                slug="robbottx-core",
                zip_url=zip_url,
                zip_sha256=digest,
                zip_size=123,
                inventory_url=inventory_url,
                record_hash="c" * 64,
            )

        extra_manifest = dict(manifest)
        extra_manifest["unexpected"] = True
        with self.assertRaises(deploy.DeployFailure):
            deploy.verify_manifest(
                extra_manifest,
                version="0.1.3",
                slug="robbottx-core",
                zip_url=zip_url,
                zip_sha256=digest,
                zip_size=123,
                inventory_url=inventory_url,
                record_hash="c" * 64,
            )

        extra_inventory = {
            "artifact": "robbottx-core-0.1.3.zip",
            "version": "0.1.3",
            "zip_sha256": digest,
            "zip_bytes": 123,
            "files": files,
            "unexpected": True,
        }
        with self.assertRaises(deploy.DeployFailure):
            deploy.verify_inventory(
                extra_inventory,
                version="0.1.3",
                slug="robbottx-core",
                zip_sha256=digest,
                zip_size=123,
                packaged_files=files,
            )

        for ambiguous_json in (
            '{"version":"0.1.3","version":"0.1.4"}',
            '{"value":NaN}',
            '{"value":1e9999}',
        ):
            with self.subTest(ambiguous_json=ambiguous_json):
                with self.assertRaises(deploy.DeployFailure):
                    deploy.json_body(
                        200,
                        "application/json",
                        ambiguous_json,
                        "Public metadata",
                    )

    def test_release_inputs_reject_noncanonical_artifact_url(self):
        args = Namespace(
            version="0.1.3",
            zip_url="https://attacker.example/robbottx-core-0.1.3.zip",
            manifest_url=(
                f"{deploy.EXPECTED_RAW_ROOT}/robbottx-core.json"
            ),
            inventory_url="",
            zip_sha256="a" * 64,
            zip_size=123,
            record_hash="c" * 64,
            boundary_receipt=Path("boundary-release-receipt.json"),
            package_marker="Featured system configuration",
            plugin_slug="robbottx-core",
            plugin_main_file="robbottx-core.php",
            version_constant="ROBBOTTX_CORE_VERSION",
            health_path="/wp-json/robbottx/v1/healthcheck",
            render_path="/",
            new_body_marker="",
            old_body_marker="<!-- robbottx-core:0.1.2 -->",
        )
        with self.assertRaises(deploy.DeployFailure):
            deploy.validate_release_inputs(
                args,
                "https://robbottx.com",
            )

    def test_public_zip_rejects_traversal_member(self):
        record_hash = "c" * 64
        archive_buffer = io.BytesIO()
        with ZipFile(
            archive_buffer,
            "w",
            compression=ZIP_DEFLATED,
        ) as archive:
            archive.writestr(
                "robbottx-core/robbottx-core.php",
                "<?php\n/**\n * Version: 0.1.3\n */\n"
                "define('ROBBOTTX_CORE_VERSION', '0.1.3');\n"
                f"// Featured system configuration {record_hash}\n",
            )
            archive.writestr(
                "robbottx-core/../outside.php",
                "<?php",
            )
        archive_bytes = archive_buffer.getvalue()
        with self.assertRaises(deploy.DeployFailure):
            deploy.verify_plugin_zip(
                archive_bytes,
                expected_size=len(archive_bytes),
                expected_sha256=hashlib.sha256(archive_bytes).hexdigest(),
                slug="robbottx-core",
                main_file="robbottx-core.php",
                version="0.1.3",
                version_constant="ROBBOTTX_CORE_VERSION",
                package_marker="Featured system configuration",
                expected_record_hash=record_hash,
            )

    def test_snippet_lookup_fails_closed_on_incomplete_pagination(self):
        records = [
            {"id": index, "name": f"other-{index}"}
            for index in range(100)
        ]
        with patch.object(
            deploy,
            "request",
            return_value=(200, "application/json", json.dumps(records)),
        ):
            matches, failures = deploy.find_snippet_ids_by_name(
                "https://example.test",
                "tmp-robbottx-deploy-unique",
                "Basic redacted",
                max_pages=1,
            )
        self.assertEqual(matches, [])
        self.assertTrue(
            any("exhaustive pagination" in failure for failure in failures)
        )

    def test_rendered_marker_must_be_inside_closed_body(self):
        good = (
            "<html><head></head><body>"
            "<!-- robbottx-core:0.1.3 -->"
            "</body></html>"
        )
        digest = deploy.verify_rendered_body(
            good,
            new_marker="<!-- robbottx-core:0.1.3 -->",
            old_marker="<!-- robbottx-core:0.1.2 -->",
        )
        self.assertRegex(digest, r"^[0-9a-f]{64}$")

        after_body = (
            "<html><body>catalog</body>"
            "<!-- robbottx-core:0.1.3 --></html>"
        )
        with self.assertRaises(deploy.DeployFailure):
            deploy.verify_rendered_body(
                after_body,
                new_marker="<!-- robbottx-core:0.1.3 -->",
                old_marker="<!-- robbottx-core:0.1.2 -->",
            )


if __name__ == "__main__":
    unittest.main()
