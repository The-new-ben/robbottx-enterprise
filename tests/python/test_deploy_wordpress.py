import hashlib
import importlib.util
import io
import json
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPOSITORY_ROOT / "scripts" / "deploy-wordpress.py"
SPEC = importlib.util.spec_from_file_location("deploy_wordpress", MODULE_PATH)
deploy = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(deploy)


class DeployWordPressTests(unittest.TestCase):
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
