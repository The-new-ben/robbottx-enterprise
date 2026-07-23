import hashlib
import importlib.util
import io
import json
import unittest
import warnings
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPOSITORY_ROOT / "scripts" / "deploy-wordpress-theme.py"
SPEC = importlib.util.spec_from_file_location(
    "deploy_wordpress_theme",
    MODULE_PATH,
)
deploy = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(deploy)


def make_theme_zip(
    *,
    root="robbottx",
    version="0.1.3",
    marker="release-marker-0.1.3",
):
    archive_buffer = io.BytesIO()
    with ZipFile(
        archive_buffer,
        "w",
        compression=ZIP_DEFLATED,
    ) as archive:
        archive.writestr(
            f"{root}/style.css",
            "/*\n"
            "Theme Name: RobbottX Test\n"
            f"Version: {version}\n"
            "*/\n",
        )
        archive.writestr(
            f"{root}/parts/header.html",
            f"<!-- {marker} -->\n",
        )
    return archive_buffer.getvalue()


class DeployWordPressThemeTests(unittest.TestCase):
    def valid_args(self, archive_bytes, *, execute=True):
        return SimpleNamespace(
            version="0.1.3",
            zip_url=(
                "https://raw.githubusercontent.com/The-new-ben/"
                "robbottx-enterprise/main/plugin-dist/"
                "robbottx-0.1.3.zip"
            ),
            zip_sha256=hashlib.sha256(archive_bytes).hexdigest(),
            zip_size=len(archive_bytes),
            package_marker="release-marker-0.1.3",
            theme_slug="robbottx",
            render_path="/",
            new_body_marker='data-theme-release="0.1.3"',
            old_body_marker='data-theme-release="0.1.2"',
            execute=execute,
        )

    def test_inputs_reject_unsafe_url_slug_and_weak_markers(self):
        archive_bytes = make_theme_zip()
        valid = vars(self.valid_args(archive_bytes, execute=False))
        invalid_cases = [
            {"zip_url": "http://downloads.example.test/theme.zip"},
            {"zip_url": "https://user@example.test/theme.zip"},
            {"zip_url": "https://example.test/theme.zip#fragment"},
            {
                "zip_url": (
                    "https://raw.githubusercontent.com/The-new-ben/"
                    "robbottx-enterprise/main/plugin-dist/"
                    "robbottx-0.1.2.zip"
                )
            },
            {"theme_slug": "RobbottX"},
            {"version": "0.1.3'; phpinfo();"},
            {"package_marker": " short "},
            {"new_body_marker": "same-marker", "old_body_marker": "same-marker"},
            {"render_path": "https://example.test/"},
        ]
        for change in invalid_cases:
            with self.subTest(change=change):
                args = SimpleNamespace(**{**valid, **change})
                with self.assertRaises(deploy.DeployFailure):
                    deploy.validate_inputs(args)

        self.assertEqual(
            deploy.normalize_base_url("https://robbottx.com/"),
            "https://robbottx.com",
        )
        for unsafe_base_url in [
            "https://www.robbottx.com",
            "https://example.test",
            "https://robbottx.com:8443",
            "http://robbottx.com",
        ]:
            with self.subTest(base_url=unsafe_base_url):
                with self.assertRaises(deploy.DeployFailure):
                    deploy.normalize_base_url(unsafe_base_url)

    def test_public_zip_requires_exact_hash_size_root_version_and_marker(self):
        archive_bytes = make_theme_zip()
        digest = hashlib.sha256(archive_bytes).hexdigest()

        result = deploy.verify_theme_zip(
            archive_bytes,
            expected_size=len(archive_bytes),
            expected_sha256=digest,
            slug="robbottx",
            version="0.1.3",
            package_marker="release-marker-0.1.3",
        )
        self.assertEqual(result["zip_sha256"], digest)
        self.assertEqual(result["zip_bytes"], len(archive_bytes))

        invalid_cases = [
            {"expected_size": len(archive_bytes) + 1},
            {"expected_sha256": "0" * 64},
            {"slug": "wrong-root"},
            {"version": "0.1.2"},
            {"package_marker": "missing-marker"},
        ]
        defaults = {
            "expected_size": len(archive_bytes),
            "expected_sha256": digest,
            "slug": "robbottx",
            "version": "0.1.3",
            "package_marker": "release-marker-0.1.3",
        }
        for change in invalid_cases:
            with self.subTest(change=change):
                with self.assertRaises(deploy.DeployFailure):
                    deploy.verify_theme_zip(
                        archive_bytes,
                        **{**defaults, **change},
                    )

    def test_public_zip_rejects_traversal_duplicate_and_secret_paths(self):
        def archive_with(entries):
            buffer = io.BytesIO()
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with ZipFile(buffer, "w") as archive:
                    for name, body in entries:
                        archive.writestr(name, body)
            return buffer.getvalue()

        style = "/*\nVersion: 0.1.3\nrelease-marker-0.1.3\n*/"
        cases = [
            [
                ("robbottx/style.css", style),
                ("robbottx/../outside.php", "bad"),
            ],
            [
                ("robbottx/style.css", style),
                ("robbottx/.env", "bad"),
            ],
            [
                ("robbottx/style.css", style),
                ("robbottx/style.css", style),
            ],
            [
                (
                    "robbottx/style.css",
                    style + "\nTemplate: parent-theme\n",
                ),
            ],
        ]
        for entries in cases:
            archive_bytes = archive_with(entries)
            with self.subTest(entries=[name for name, _ in entries]):
                with self.assertRaises(deploy.DeployFailure):
                    deploy.verify_theme_zip(
                        archive_bytes,
                        expected_size=len(archive_bytes),
                        expected_sha256=hashlib.sha256(
                            archive_bytes
                        ).hexdigest(),
                        slug="robbottx",
                        version="0.1.3",
                        package_marker="release-marker-0.1.3",
                    )

    def test_route_absence_requires_wordpress_json_rest_no_route(self):
        valid_response = (
            404,
            "application/json; charset=UTF-8",
            json.dumps(
                {
                    "code": "rest_no_route",
                    "message": "No route was found.",
                    "data": {"status": 404},
                }
            ),
        )
        with patch.object(deploy, "request", return_value=valid_response):
            absent, failures = deploy.prove_deploy_route_absent(
                "https://example.test",
                "Basic redacted",
                "/wp-json/agenttheme/v1/run-unique",
                attempts=1,
            )
        self.assertTrue(absent)
        self.assertEqual(failures, [])

        invalid_responses = [
            (404, "text/html", "<h1>Not found</h1>"),
            (
                404,
                "application/json",
                json.dumps(
                    {
                        "code": "rest_forbidden",
                        "data": {"status": 404},
                    }
                ),
            ),
            (200, "application/json", valid_response[2]),
            (404, "application/json", "{"),
        ]
        for response in invalid_responses:
            with self.subTest(response=response[:2]):
                with patch.object(deploy, "request", return_value=response):
                    absent, _ = deploy.prove_deploy_route_absent(
                        "https://example.test",
                        "Basic redacted",
                        "/wp-json/agenttheme/v1/run-unique",
                        attempts=1,
                    )
                self.assertFalse(absent)

    def test_legacy_route_proof_uses_only_exact_rest_inventory(self):
        index = json.dumps({"routes": {}})
        with patch.object(
            deploy,
            "request",
            return_value=(200, "application/json", index),
        ) as request_mock:
            absent, failures = deploy.prove_legacy_route_absent(
                "https://example.test",
            )

        self.assertTrue(absent)
        self.assertEqual(failures, [])
        request_mock.assert_called_once()
        requested_url = request_mock.call_args.args[0]
        self.assertTrue(requested_url.startswith("https://example.test/wp-json/?"))
        self.assertNotIn(deploy.LEGACY_ROUTE_PATH, requested_url)
        self.assertEqual(request_mock.call_args.kwargs, {"timeout": 30})

    def test_legacy_route_proof_fails_closed_on_inventory_failure(self):
        with patch.object(
            deploy,
            "prove_route_not_registered",
            return_value=(
                False,
                ["the route remains registered in REST inventory"],
            ),
        ):
            absent, failures = deploy.prove_legacy_route_absent(
                "https://example.test",
            )

        self.assertFalse(absent)
        self.assertEqual(
            failures,
            ["the route remains registered in REST inventory"],
        )

    def test_ambiguous_create_recovers_exact_name_and_proves_record_absent(self):
        with (
            patch.object(
                deploy,
                "find_snippet_ids_by_name",
                side_effect=[([91], []), ([], [])],
            ),
            patch.object(
                deploy,
                "delete_and_prove_snippet",
                return_value=(True, []),
            ) as delete_mock,
        ):
            cleaned, failures = deploy.cleanup_temporary_snippets(
                "https://example.test",
                "Basic redacted",
                "tmp-robbottx-theme-deploy-unique",
                None,
            )

        self.assertTrue(cleaned)
        self.assertEqual(failures, [])
        delete_mock.assert_called_once_with(
            "https://example.test",
            91,
            "Basic redacted",
        )

    def test_cleanup_never_deletes_a_wrong_create_response_id(self):
        with (
            patch.object(
                deploy,
                "find_snippet_ids_by_name",
                side_effect=[([92], []), ([], [])],
            ),
            patch.object(
                deploy,
                "request",
                return_value=(
                    200,
                    "application/json",
                    json.dumps(
                        {
                            "id": 91,
                            "name": "unrelated-permanent-snippet",
                        }
                    ),
                ),
            ),
            patch.object(
                deploy,
                "delete_and_prove_snippet",
                return_value=(True, []),
            ) as delete_mock,
        ):
            cleaned, failures = deploy.cleanup_temporary_snippets(
                "https://example.test",
                "Basic redacted",
                "tmp-robbottx-theme-deploy-unique",
                91,
            )

        self.assertFalse(cleaned)
        self.assertIn(
            "created snippet ID did not resolve to the exact one-use name",
            failures,
        )
        delete_mock.assert_called_once_with(
            "https://example.test",
            92,
            "Basic redacted",
        )

    def test_snippet_record_absence_rejects_route_level_or_html_404(self):
        invalid_responses = [
            (
                404,
                "application/json",
                json.dumps(
                    {
                        "code": "rest_no_route",
                        "data": {"status": 404},
                    }
                ),
            ),
            (404, "text/html", "<h1>Not found</h1>"),
            (
                404,
                "application/json",
                json.dumps(
                    {
                        "code": "rest_forbidden",
                        "message": "The snippet could not be found.",
                        "data": {"status": 404},
                    }
                ),
            ),
            (
                500,
                "application/json",
                json.dumps(
                    {
                        "code": "rest_cannot_get",
                        "message": "Different server response.",
                        "data": {"status": 500},
                    }
                ),
            ),
        ]
        for response in invalid_responses:
            with self.subTest(response=response[:2]):
                with patch.object(deploy, "request", return_value=response):
                    absent, _ = deploy.prove_snippet_record_absent(
                        "https://example.test",
                        91,
                        "Basic redacted",
                        attempts=1,
                    )
                self.assertFalse(absent)

        for status in [404, 500]:
            record_response = (
                status,
                "application/json",
                json.dumps(
                    {
                        "code": "rest_cannot_get",
                        "message": "The snippet could not be found.",
                        "data": {"status": status},
                    }
                ),
            )
            with self.subTest(confirmed_status=status):
                with patch.object(deploy, "request", return_value=record_response):
                    absent, failures = deploy.prove_snippet_record_absent(
                        "https://example.test",
                        91,
                        "Basic redacted",
                        attempts=1,
                    )
                self.assertTrue(absent)
                self.assertEqual(failures, [])

    def test_delete_retries_after_code_snippets_soft_trash(self):
        record_present = (
            200,
            "application/json",
            json.dumps(
                {
                    "id": 91,
                    "name": "tmp-robbottx-theme-deploy-unique",
                    "trashed": True,
                }
            ),
        )
        record_absent = (
            404,
            "application/json",
            json.dumps(
                {
                    "code": "rest_cannot_get",
                    "message": "The snippet could not be found.",
                    "data": {"status": 404},
                }
            ),
        )
        responses = [
            (200, "application/json", '{"trashed":true}'),
            record_present,
            (204, "application/json", ""),
            record_absent,
        ]
        with (
            patch.object(deploy, "request", side_effect=responses) as request_mock,
            patch.object(deploy.time, "sleep"),
        ):
            absent, _ = deploy.delete_and_prove_snippet(
                "https://example.test",
                91,
                "Basic redacted",
                attempts=2,
            )

        self.assertTrue(absent)
        self.assertEqual(request_mock.call_count, 4)

    def test_rendered_marker_must_be_inside_closed_body(self):
        response = (
            200,
            "text/html; charset=UTF-8",
            (
                "<html><body><main>old page</main></body>"
                '<!-- data-theme-release="0.1.3" --></html>'
            ),
        )
        with patch.object(deploy, "request", return_value=response):
            with self.assertRaises(deploy.DeployFailure):
                deploy.verify_rendered_body(
                    "https://example.test",
                    "/",
                    'data-theme-release="0.1.3"',
                    'data-theme-release="0.1.2"',
                )

        retained_old_response = (
            200,
            "text/html; charset=UTF-8",
            (
                "<html><body>"
                '<main data-theme-release="0.1.3"></main>'
                '<aside data-theme-release="0.1.2"></aside>'
                "</body></html>"
            ),
        )
        with patch.object(
            deploy,
            "request",
            return_value=retained_old_response,
        ):
            with self.assertRaises(deploy.DeployFailure):
                deploy.verify_rendered_body(
                    "https://example.test",
                    "/",
                    'data-theme-release="0.1.3"',
                    'data-theme-release="0.1.2"',
                )

    def test_theme_rest_requires_exact_standalone_active_block_theme(self):
        live_record = {
            "stylesheet": "robbottx",
            "template": "robbottx",
            "version": "0.1.3",
            "status": "active",
            "is_block_theme": True,
        }
        with patch.object(
            deploy,
            "request",
            return_value=(
                200,
                "application/json",
                json.dumps(live_record),
            ),
        ):
            verified = deploy.verify_theme_rest_record(
                "https://robbottx.com",
                "Basic redacted",
                "robbottx",
                "0.1.3",
            )
        self.assertEqual(verified["template"], "robbottx")

        invalid_changes = [
            {"stylesheet": "other"},
            {"template": "parent-theme"},
            {"version": "0.1.2"},
            {"status": "inactive"},
            {"is_block_theme": False},
        ]
        for change in invalid_changes:
            with self.subTest(change=change):
                with patch.object(
                    deploy,
                    "request",
                    return_value=(
                        200,
                        "application/json",
                        json.dumps({**live_record, **change}),
                    ),
                ):
                    with self.assertRaises(deploy.DeployFailure):
                        deploy.verify_theme_rest_record(
                            "https://robbottx.com",
                            "Basic redacted",
                            "robbottx",
                            "0.1.3",
                        )

    def test_route_template_is_unique_and_binds_verified_artifact(self):
        route_code = deploy.build_route_code(
            theme_slug="robbottx",
            version="0.1.3",
            zip_url=(
                "https://raw.githubusercontent.com/The-new-ben/"
                "robbottx-enterprise/main/plugin-dist/"
                "robbottx-0.1.3.zip"
            ),
            zip_sha256="a" * 64,
            zip_size=13996,
            route_token="0-1-3-1700000000-aabbccddeeff",
        )
        self.assertIn(
            "'/run-0-1-3-1700000000-aabbccddeeff'",
            route_code,
        )
        self.assertNotIn("'/run'", route_code)
        self.assertIn("$expected_sha256 = '" + ("a" * 64) + "'", route_code)
        self.assertIn("$expected_size = 13996", route_code)
        self.assertIn("hash_equals", route_code)
        self.assertIn("'result' => true", route_code)
        self.assertIn("'artifact_verified' => true", route_code)
        self.assertIn("$active_template !== $theme_slug", route_code)
        self.assertNotIn("raw.githubusercontent.com", route_code)
        self.assertNotIn("{{", route_code)

    def test_success_path_emits_only_allowlisted_redacted_evidence(self):
        archive_bytes = make_theme_zip()
        args = self.valid_args(archive_bytes)
        create_payloads = []

        def request_side_effect(url, **kwargs):
            if "/wp/v2/users/me?" in url:
                return (
                    200,
                    "application/json",
                    json.dumps(
                        {
                            "roles": ["administrator"],
                            "capabilities": {
                                "install_themes": True,
                                "switch_themes": True,
                                "update_themes": True,
                            },
                        }
                    ),
                )
            if (
                url.endswith("/wp-json/code-snippets/v1/snippets")
                and kwargs.get("method") == "POST"
            ):
                create_payloads.append(kwargs["payload"])
                return (201, "application/json", '{"id":73}')
            if "/wp-json/agenttheme/v1/run-" in url:
                return (
                    502,
                    "text/html",
                    "<html>sentinel-proxy-private-body</html>",
                )
            if "/wp-json/wp/v2/themes/robbottx?" in url:
                return (
                    200,
                    "application/json",
                    json.dumps(
                        {
                            "stylesheet": "robbottx",
                            "template": "robbottx",
                            "status": "active",
                            "version": "0.1.3",
                            "is_block_theme": True,
                        }
                    ),
                )
            if url.startswith("https://robbottx.com/?"):
                return (
                    200,
                    "text/html; charset=UTF-8",
                    (
                        "<html><body>"
                        '<main data-theme-release="0.1.3"></main>'
                        "</body></html>"
                    ),
                )
            raise AssertionError(f"Unexpected mocked request: {url}")

        environment = {
            "WP_BASE_URL": "https://robbottx.com",
            "WP_USER": "release-operator",
            "WP_APP_PASSWORD": "sentinel-private-value",
        }
        stdout = io.StringIO()
        with (
            patch.object(deploy, "parse_args", return_value=args),
            patch.object(
                deploy,
                "required_env",
                side_effect=lambda name: environment[name],
            ),
            patch.object(
                deploy,
                "request_bytes",
                return_value=(
                    200,
                    "application/zip",
                    archive_bytes,
                ),
            ),
            patch.object(deploy, "request", side_effect=request_side_effect),
            patch.object(deploy, "require_legacy_route_absent"),
            patch.object(deploy, "require_route_not_registered"),
            patch.object(deploy, "require_deploy_route_absent"),
            patch.object(deploy, "require_snippet_name_absent"),
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
            patch.object(
                deploy,
                "prove_route_not_registered",
                return_value=(True, []),
            ),
            patch.object(
                deploy,
                "prove_legacy_route_absent",
                return_value=(True, []),
            ),
            patch.object(deploy.time, "time", return_value=1700000000),
            patch.object(
                deploy.secrets,
                "token_hex",
                return_value="aabbccddeeff",
            ),
            redirect_stdout(stdout),
        ):
            result = deploy.main()

        self.assertEqual(result, 0)
        self.assertEqual(len(create_payloads), 1)
        self.assertEqual(
            create_payloads[0]["name"],
            "tmp-robbottx-theme-deploy-0-1-3-1700000000-aabbccddeeff",
        )
        self.assertIn(
            "/run-0-1-3-1700000000-aabbccddeeff",
            create_payloads[0]["code"],
        )
        evidence_text = stdout.getvalue()
        evidence = json.loads(evidence_text)
        self.assertEqual(evidence["status"], "deployed")
        self.assertFalse(evidence["callback_confirmed"])
        self.assertTrue(evidence["snippet_record_absent_after"])
        self.assertEqual(
            evidence["artifact"]["sha256"],
            hashlib.sha256(archive_bytes).hexdigest(),
        )
        for private_value in [
            "sentinel-private-value",
            "release-operator",
            "Basic ",
            "https://robbottx.com",
            "raw.githubusercontent.com",
            "aabbccddeeff",
            "tmp-robbottx",
            "sentinel-proxy-private-body",
        ]:
            self.assertNotIn(private_value, evidence_text)

    def test_cleanup_stages_continue_after_ambiguous_create_and_exception(self):
        archive_bytes = make_theme_zip()
        args = self.valid_args(archive_bytes)
        environment = {
            "WP_BASE_URL": "https://robbottx.com",
            "WP_USER": "release-operator",
            "WP_APP_PASSWORD": "sentinel-private-value",
        }

        def request_side_effect(url, **kwargs):
            if "/wp/v2/users/me?" in url:
                return (
                    200,
                    "application/json",
                    json.dumps(
                        {
                            "roles": ["administrator"],
                            "capabilities": {
                                "install_themes": True,
                                "switch_themes": True,
                                "update_themes": True,
                            },
                        }
                    ),
                )
            if url.endswith("/wp-json/code-snippets/v1/snippets"):
                return (
                    502,
                    "application/json",
                    json.dumps(
                        {
                            "code": "upstream_failure",
                            "data": {"status": 502},
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
                "request_bytes",
                return_value=(200, "application/zip", archive_bytes),
            ),
            patch.object(deploy, "request", side_effect=request_side_effect),
            patch.object(deploy, "require_legacy_route_absent"),
            patch.object(deploy, "require_route_not_registered"),
            patch.object(deploy, "require_deploy_route_absent"),
            patch.object(deploy, "require_snippet_name_absent"),
            patch.object(
                deploy,
                "cleanup_temporary_snippets",
                side_effect=RuntimeError("sentinel-cleanup-detail"),
            ),
            patch.object(
                deploy,
                "prove_deploy_route_absent",
                return_value=(True, []),
            ) as route_proof,
            patch.object(
                deploy,
                "prove_route_not_registered",
                return_value=(True, []),
            ) as inventory_proof,
            patch.object(
                deploy,
                "prove_legacy_route_absent",
                return_value=(True, []),
            ) as legacy_proof,
            patch.object(deploy.time, "time", return_value=1700000000),
            patch.object(
                deploy.secrets,
                "token_hex",
                return_value="aabbccddeeff",
            ),
        ):
            with self.assertRaises(deploy.DeployFailure) as raised:
                deploy.main()

        route_proof.assert_called_once()
        inventory_proof.assert_called_once()
        legacy_proof.assert_called_once()
        self.assertNotIn(
            "sentinel-cleanup-detail",
            str(raised.exception),
        )
        self.assertIn("cleanup was not proven", str(raised.exception))

    def test_independent_render_failure_fails_main_and_still_cleans(self):
        archive_bytes = make_theme_zip()
        args = self.valid_args(archive_bytes)
        environment = {
            "WP_BASE_URL": "https://robbottx.com",
            "WP_USER": "release-operator",
            "WP_APP_PASSWORD": "sentinel-private-value",
        }

        def request_side_effect(url, **kwargs):
            if "/wp/v2/users/me?" in url:
                return (
                    200,
                    "application/json",
                    json.dumps(
                        {
                            "roles": ["administrator"],
                            "capabilities": {
                                "install_themes": True,
                                "switch_themes": True,
                                "update_themes": True,
                            },
                        }
                    ),
                )
            if url.endswith("/wp-json/code-snippets/v1/snippets"):
                return (201, "application/json", '{"id":73}')
            if "/wp-json/agenttheme/v1/run-" in url:
                return (200, "application/json", '{"result":true}')
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
                "request_bytes",
                return_value=(200, "application/zip", archive_bytes),
            ),
            patch.object(deploy, "request", side_effect=request_side_effect),
            patch.object(deploy, "require_legacy_route_absent"),
            patch.object(deploy, "require_route_not_registered"),
            patch.object(deploy, "require_deploy_route_absent"),
            patch.object(deploy, "require_snippet_name_absent"),
            patch.object(
                deploy,
                "verify_theme_rest_record",
                return_value={
                    "stylesheet": "robbottx",
                    "template": "robbottx",
                    "status": "active",
                    "version": "0.1.3",
                    "is_block_theme": True,
                },
            ) as rest_verify,
            patch.object(
                deploy,
                "verify_rendered_body",
                side_effect=deploy.DeployFailure(
                    "Old rendered-body marker is still present."
                ),
            ) as render_verify,
            patch.object(
                deploy,
                "cleanup_temporary_snippets",
                return_value=(True, []),
            ) as cleanup,
            patch.object(
                deploy,
                "prove_deploy_route_absent",
                return_value=(True, []),
            ),
            patch.object(
                deploy,
                "prove_route_not_registered",
                return_value=(True, []),
            ),
            patch.object(
                deploy,
                "prove_legacy_route_absent",
                return_value=(True, []),
            ),
            patch.object(deploy.time, "time", return_value=1700000000),
            patch.object(
                deploy.secrets,
                "token_hex",
                return_value="aabbccddeeff",
            ),
        ):
            with self.assertRaises(deploy.DeployFailure) as raised:
                deploy.main()

        rest_verify.assert_called_once()
        render_verify.assert_called_once()
        cleanup.assert_called_once()
        self.assertIn(
            "rendered-body verification failed",
            str(raised.exception),
        )
        self.assertNotIn(
            "Old rendered-body marker",
            str(raised.exception),
        )


if __name__ == "__main__":
    unittest.main()
