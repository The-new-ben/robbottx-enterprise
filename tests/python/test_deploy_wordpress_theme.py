import hashlib
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
import warnings
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPOSITORY_ROOT / "scripts" / "deploy-wordpress-theme.py"
THEME_ROUTE_TEMPLATE = (
    REPOSITORY_ROOT
    / "scripts"
    / "templates"
    / "deploy-theme-route.php.txt"
).read_text(encoding="utf-8")
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
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)

    def valid_args(self, archive_bytes, *, execute=True):
        return SimpleNamespace(
            version="0.1.3",
            previous_version="0.1.2",
            zip_url=(
                "https://raw.githubusercontent.com/The-new-ben/"
                "robbottx-enterprise/main/plugin-dist/"
                "robbottx-0.1.3.zip"
            ),
            zip_sha256=hashlib.sha256(archive_bytes).hexdigest(),
            zip_size=len(archive_bytes),
            boundary_receipt=(
                Path(self.temporary_directory.name)
                / "theme-boundary-receipt.json"
            ),
            package_marker="release-marker-0.1.3",
            theme_slug="robbottx",
            render_path="/",
            new_body_marker='data-theme-release="0.1.3"',
            old_body_marker='data-theme-release="0.1.2"',
            expect_fallback_favicon=True,
            previous_favicon_absent=False,
            output=(
                Path(self.temporary_directory.name)
                / "theme-deploy-evidence.json"
            ),
            execute=execute,
        )

    def boundary_result(self, args):
        return {
            "artifact_path": f"plugin-dist/robbottx-{args.version}.zip",
            "git_head": "d" * 40,
            "receipt_body_sha256": "e" * 64,
            "route_template": THEME_ROUTE_TEMPLATE,
        }

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
            {"previous_version": "0.1.3"},
            {"previous_version": "0.1.2'; phpinfo();"},
            {"package_marker": " short "},
            {"new_body_marker": "same-marker", "old_body_marker": "same-marker"},
            {"render_path": "https://example.test/"},
            {
                "expect_fallback_favicon": False,
                "previous_favicon_absent": True,
            },
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

    def test_boundary_receipt_binds_current_scan_and_exact_theme_artifact(self):
        archive_bytes = make_theme_zip()
        args = self.valid_args(archive_bytes, execute=False)
        scan_report = SimpleNamespace(
            public_snapshot_payload_sha256="c" * 64,
            git_head="d" * 40,
        )
        captured = {}

        def run_scan(repository_root):
            captured["scan_root"] = repository_root
            return scan_report

        def validate_receipt(receipt_path, **kwargs):
            captured["receipt_path"] = receipt_path
            captured["validation"] = kwargs
            return {
                "artifact_path": "plugin-dist/robbottx-0.1.3.zip",
                "git_head": "d" * 40,
                "receipt_body_sha256": "e" * 64,
            }

        verifier = SimpleNamespace(
            DeployFailure=RuntimeError,
            _reviewed_git_head="d" * 40,
            read_clean_index_file=lambda *args, **kwargs: (
                THEME_ROUTE_TEMPLATE.encode("utf-8"),
                "d" * 40,
            ),
            run_reviewed_boundary_scan=run_scan,
            validate_boundary_receipt=validate_receipt,
        )
        with patch.object(
            deploy,
            "load_reviewed_boundary_verifier",
            return_value=verifier,
        ):
            result = deploy.validate_theme_boundary_receipt(args)

        self.assertEqual(captured["scan_root"], REPOSITORY_ROOT)
        self.assertEqual(
            captured["receipt_path"],
            args.boundary_receipt,
        )
        self.assertEqual(captured["validation"]["version"], "0.1.3")
        self.assertEqual(captured["validation"]["slug"], "robbottx")
        self.assertEqual(
            captured["validation"]["zip_sha256"],
            args.zip_sha256,
        )
        self.assertEqual(
            captured["validation"]["record_hash"],
            "c" * 64,
        )
        self.assertEqual(
            captured["validation"]["repository_root"],
            REPOSITORY_ROOT,
        )
        self.assertIs(
            captured["validation"]["scan_report"],
            scan_report,
        )
        self.assertEqual(
            result["artifact_path"],
            "plugin-dist/robbottx-0.1.3.zip",
        )
        self.assertEqual(result["route_template"], THEME_ROUTE_TEMPLATE)

    def test_index_reader_ignores_dirty_worktree_verifier(self):
        repository = (
            Path(self.temporary_directory.name)
            / "dirty-helper-repository"
        )
        helper = repository / "scripts" / "deploy-wordpress.py"
        helper.parent.mkdir(parents=True)
        git = deploy.resolve_trusted_git_executable()
        environment = deploy._trusted_git_environment(git)

        def run_git(*arguments):
            completed = subprocess.run(
                [
                    str(git),
                    "-C",
                    str(repository),
                    *arguments,
                ],
                capture_output=True,
                check=False,
                env=environment,
            )
            self.assertEqual(
                completed.returncode,
                0,
                completed.stderr.decode("utf-8", errors="replace"),
            )

        subprocess.run(
            [str(git), "init", str(repository)],
            capture_output=True,
            check=True,
            env=environment,
        )
        run_git("config", "user.name", "Theme Test")
        run_git("config", "user.email", "theme@example.invalid")
        run_git("config", "core.autocrlf", "false")
        reviewed = b"ORIGIN = 'reviewed-index'\n"
        helper.write_bytes(reviewed)
        run_git("add", "--", "scripts/deploy-wordpress.py")
        run_git("commit", "--no-verify", "-m", "reviewed verifier")
        helper.write_text(
            "raise RuntimeError('dirty verifier executed')\n",
            encoding="utf-8",
            newline="\n",
        )

        payload, git_head = deploy._read_head_index_file(
            repository,
            "scripts/deploy-wordpress.py",
            max_bytes=1024,
        )

        self.assertEqual(payload, reviewed)
        self.assertRegex(git_head, r"^[0-9a-f]{40}$")

    def test_verifier_loader_executes_only_index_reader_payload(self):
        reviewed_payload = (
            "class DeployFailure(RuntimeError):\n"
            "    pass\n"
            "ORIGIN = 'reviewed-index'\n"
            "def read_clean_index_file(*args, **kwargs):\n"
            "    return b'reviewed', 'd' * 40\n"
            "def run_reviewed_boundary_scan(*args, **kwargs):\n"
            "    return None\n"
            "def validate_boundary_receipt(*args, **kwargs):\n"
            "    return {}\n"
        ).encode("utf-8")
        with patch.object(
            deploy,
            "_read_head_index_file",
            return_value=(reviewed_payload, "d" * 40),
        ), patch.object(
            deploy.Path,
            "read_bytes",
            side_effect=AssertionError("worktree verifier read"),
        ), patch.object(
            deploy.Path,
            "read_text",
            side_effect=AssertionError("worktree verifier read"),
        ):
            verifier = deploy.load_reviewed_boundary_verifier()

        self.assertEqual(verifier.ORIGIN, "reviewed-index")
        self.assertEqual(verifier._reviewed_git_head, "d" * 40)

    def test_route_template_is_frozen_before_boundary_scan(self):
        mutable_worktree = {"template": THEME_ROUTE_TEMPLATE}
        scan_report = SimpleNamespace(
            git_head="d" * 40,
            public_snapshot_payload_sha256="c" * 64,
        )

        def scan(_repository):
            mutable_worktree["template"] = "<?php throw new Exception();"
            return scan_report

        verifier = SimpleNamespace(
            DeployFailure=RuntimeError,
            _reviewed_git_head="d" * 40,
            read_clean_index_file=lambda *args, **kwargs: (
                THEME_ROUTE_TEMPLATE.encode("utf-8"),
                "d" * 40,
            ),
            run_reviewed_boundary_scan=scan,
            validate_boundary_receipt=lambda *args, **kwargs: {
                "artifact_path": "plugin-dist/robbottx-0.1.3.zip",
                "git_head": "d" * 40,
                "receipt_body_sha256": "e" * 64,
            },
        )
        args = self.valid_args(make_theme_zip(), execute=False)
        with patch.object(
            deploy,
            "load_reviewed_boundary_verifier",
            return_value=verifier,
        ), patch.object(
            deploy.Path,
            "read_text",
            side_effect=AssertionError("worktree template reread"),
        ):
            boundary = deploy.validate_theme_boundary_receipt(args)
            route_code = deploy.build_route_code(
                route_template=boundary["route_template"],
                theme_slug=args.theme_slug,
                version=args.version,
                zip_url=args.zip_url,
                zip_sha256=args.zip_sha256,
                zip_size=args.zip_size,
                route_token="0-1-3-1700000000-aabbccddeeff",
            )

        self.assertNotEqual(
            boundary["route_template"],
            mutable_worktree["template"],
        )
        self.assertIn(
            "'/run-0-1-3-1700000000-aabbccddeeff'",
            route_code,
        )

    def test_theme_boundary_rejects_a_year_2000_receipt(self):
        archive_bytes = make_theme_zip()
        args = self.valid_args(archive_bytes, execute=False)
        receipt = {
            "schema_version": 1,
            "receipt_type": "robbottx_public_boundary_release",
            "release_mode": True,
            "created_at": "2000-01-01T00:00:00Z",
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
                "path": "plugin-dist/robbottx-0.1.3.zip",
                "sha256": args.zip_sha256,
            },
        }
        canonical = json.dumps(
            receipt,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        receipt["receipt_body_sha256"] = hashlib.sha256(
            canonical
        ).hexdigest()
        args.boundary_receipt.write_text(
            json.dumps(receipt),
            encoding="utf-8",
        )
        scan_report = SimpleNamespace(
            findings=(),
            git_head="d" * 40,
            git_dirty=False,
            git_index_content_sha256="f" * 64,
            worktree_content_sha256="f" * 64,
            repository_content_sha256="f" * 64,
            asset_manifest_sha256="b" * 64,
            public_snapshot_payload_sha256="c" * 64,
            release_artifacts=(
                (
                    "plugin-dist/robbottx-0.1.3.zip",
                    args.zip_sha256,
                ),
            ),
        )
        class BoundaryFailure(RuntimeError):
            pass

        verifier = SimpleNamespace(
            DeployFailure=BoundaryFailure,
            _reviewed_git_head="d" * 40,
            read_clean_index_file=lambda *args, **kwargs: (
                THEME_ROUTE_TEMPLATE.encode("utf-8"),
                "d" * 40,
            ),
            run_reviewed_boundary_scan=lambda _root: scan_report,
            validate_boundary_receipt=lambda *args, **kwargs: (
                (_ for _ in ()).throw(
                    BoundaryFailure(
                        "Public boundary release receipt timestamp "
                        "is outside the release window."
                    )
                )
            ),
        )
        with (
            patch.object(
                deploy,
                "load_reviewed_boundary_verifier",
                return_value=verifier,
            ),
            self.assertRaises(deploy.DeployFailure) as raised,
        ):
            deploy.validate_theme_boundary_receipt(args)

        self.assertIn("outside the release window", str(raised.exception))

    def test_boundary_gate_precedes_wordpress_credentials_and_network(self):
        archive_bytes = make_theme_zip()
        args = self.valid_args(archive_bytes, execute=False)
        evidence = {
            "execute": False,
            "status": "started",
        }
        with (
            patch.object(
                deploy,
                "validate_theme_boundary_receipt",
                side_effect=deploy.DeployFailure("boundary rejected"),
            ),
            patch.object(deploy, "required_env") as environment_mock,
            patch.object(deploy, "request") as request_mock,
            patch.object(deploy, "request_bytes") as download_mock,
            self.assertRaises(deploy.DeployFailure),
        ):
            deploy._run_deployment(args, evidence)

        self.assertEqual(evidence["failure_stage"], "public_boundary")
        environment_mock.assert_not_called()
        request_mock.assert_not_called()
        download_mock.assert_not_called()

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

    def test_snippet_lookup_uses_a_fresh_exact_name_inventory(self):
        response = json.dumps(
            [
                {
                    "id": 91,
                    "name": "tmp-robbottx-theme-deploy-unique",
                }
            ]
        )
        with patch.object(
            deploy,
            "request",
            return_value=(200, "application/json", response),
        ) as request_mock:
            matches, failures = deploy.find_snippet_ids_by_name(
                "https://example.test",
                "tmp-robbottx-theme-deploy-unique",
                "Basic redacted",
            )

        self.assertEqual(matches, [91])
        self.assertEqual(failures, [])
        lookup_url = request_mock.call_args.args[0]
        self.assertIn("per_page=100&page=1", lookup_url)
        self.assertIn("&rbtxcb=", lookup_url)

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
        for delete_index in (0, 2):
            delete_call = request_mock.call_args_list[delete_index]
            self.assertEqual(
                delete_call.kwargs["method"],
                "POST",
            )
            self.assertIn("_method=DELETE", delete_call.args[0])
            self.assertIn("rbtxcb=", delete_call.args[0])
            self.assertEqual(delete_call.kwargs["payload"], {})
        for proof_index in (1, 3):
            self.assertIn(
                "rbtxcb=",
                request_mock.call_args_list[proof_index].args[0],
            )

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
                    "robbottx",
                    "0.1.3",
                    True,
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
                    "robbottx",
                    "0.1.3",
                    True,
                )

    def test_rendered_release_requires_exact_versioned_theme_assets(self):
        def rendered(style_version="0.1.3", favicon_version="0.1.3"):
            return (
                "<html><head>"
                '<link rel="stylesheet" '
                'href="https://example.test/wp-content/themes/'
                f'robbottx/style.css?ver={style_version}">'
                '<link sizes="any" type="image/svg+xml" rel="icon" '
                'href="/wp-content/themes/robbottx/assets/'
                f'favicon.svg?ver={favicon_version}">'
                "</head><body>"
                '<main data-theme-release="0.1.3"></main>'
                "</body></html>"
            )

        with patch.object(
            deploy,
            "request",
            return_value=(
                200,
                "text/html; charset=UTF-8",
                rendered(),
            ),
        ):
            assets = deploy.verify_rendered_body(
                "https://example.test",
                "/",
                'data-theme-release="0.1.3"',
                'data-theme-release="0.1.2"',
                "robbottx",
                "0.1.3",
                True,
            )
        self.assertEqual(
            assets["stylesheet_path"],
            "/wp-content/themes/robbottx/style.css",
        )
        self.assertEqual(
            assets["favicon_path"],
            "/wp-content/themes/robbottx/assets/favicon.svg",
        )
        self.assertEqual(assets["version"], "0.1.3")

        for style_version, favicon_version in (
            ("0.1.2", "0.1.3"),
            ("0.1.3", "0.1.2"),
        ):
            with self.subTest(
                style_version=style_version,
                favicon_version=favicon_version,
            ):
                with patch.object(
                    deploy,
                    "request",
                    return_value=(
                        200,
                        "text/html; charset=UTF-8",
                        rendered(style_version, favicon_version),
                    ),
                ):
                    with self.assertRaises(deploy.DeployFailure):
                        deploy.verify_rendered_body(
                            "https://example.test",
                            "/",
                            'data-theme-release="0.1.3"',
                            'data-theme-release="0.1.2"',
                            "robbottx",
                            "0.1.3",
                            True,
                        )

    def test_previous_release_can_prove_exact_favicon_absence(self):
        document = (
            "<html><head>"
            '<link rel="stylesheet" href="/wp-content/themes/robbottx/'
            'style.css?ver=0.1.3">'
            "</head><body>"
            '<main data-theme-release="0.1.3"></main>'
            "</body></html>"
        )
        identity = {
            "id": 0,
            "mime_by_url": {},
            "mode": "theme_fallback",
            "urls": set(),
        }
        with patch.object(
            deploy,
            "request",
            return_value=(
                200,
                "text/html; charset=UTF-8",
                document,
            ),
        ):
            assets = deploy.verify_rendered_transition(
                "https://example.test",
                "/",
                'data-theme-release="0.1.3"',
                'data-theme-release="0.1.2"',
                "robbottx",
                "0.1.3",
                identity,
                fetch_assets=False,
                allow_missing_fallback_favicon=True,
            )

        self.assertEqual(
            assets["favicon_mode"],
            "theme_fallback_absent",
        )
        self.assertIsNone(assets["favicon_path"])
        self.assertEqual(assets["icon_count"], 0)

        for relation in ("icon", "apple-touch-icon", "mask-icon"):
            unexpected_icon = document.replace(
                "</head>",
                f'<link rel="{relation}" href="/wp-content/themes/robbottx/'
                'assets/favicon.svg?ver=0.1.3"></head>',
            )
            with self.subTest(relation=relation):
                with patch.object(
                    deploy,
                    "request",
                    return_value=(
                        200,
                        "text/html; charset=UTF-8",
                        unexpected_icon,
                    ),
                ):
                    with self.assertRaises(deploy.DeployFailure):
                        deploy.verify_rendered_transition(
                            "https://example.test",
                            "/",
                            'data-theme-release="0.1.3"',
                            'data-theme-release="0.1.2"',
                            "robbottx",
                            "0.1.3",
                            identity,
                            fetch_assets=False,
                            allow_missing_fallback_favicon=True,
                        )

    def test_rendered_release_rejects_external_decoy_and_duplicate_assets(self):
        valid_style = (
            "/wp-content/themes/robbottx/style.css?ver=0.1.3"
        )
        valid_icon = (
            "/wp-content/themes/robbottx/assets/favicon.svg?ver=0.1.3"
        )

        def document(head_links, body_links=""):
            return (
                "<html><head>"
                + head_links
                + "</head><body>"
                + body_links
                + '<main data-theme-release="0.1.3"></main>'
                + "</body></html>"
            )

        invalid_documents = (
            document(
                '<link rel="stylesheet" href="https://evil.test'
                + valid_style
                + '"><link rel="icon" href="'
                + valid_icon
                + '">'
            ),
            document(
                '<link rel="stylesheet" href="'
                + valid_style
                + '"><link rel="icon" href="https://evil.test'
                + valid_icon
                + '">'
            ),
            document(
                '<link rel="stylesheet" href="'
                + valid_style
                + '"><link rel="stylesheet" href="'
                + valid_style
                + '"><link rel="icon" href="'
                + valid_icon
                + '">'
            ),
            document(
                "",
                '<link rel="stylesheet" href="'
                + valid_style
                + '"><link rel="icon" href="'
                + valid_icon
                + '">',
            ),
            document(
                '<link rel="stylesheet" href="'
                + valid_style
                + '"><link rel="icon" href="'
                + valid_icon
                + '"><link rel="mask-icon" href="'
                + valid_icon
                + '">'
            ),
        )

        for rendered in invalid_documents:
            with self.subTest(rendered=rendered[:100]):
                with patch.object(
                    deploy,
                    "request",
                    return_value=(
                        200,
                        "text/html; charset=UTF-8",
                        rendered,
                    ),
                ):
                    with self.assertRaises(deploy.DeployFailure):
                        deploy.verify_rendered_body(
                            "https://example.test",
                            "/",
                            'data-theme-release="0.1.3"',
                            'data-theme-release="0.1.2"',
                            "robbottx",
                            "0.1.3",
                            True,
                        )

    def test_rendered_release_supports_explicit_configured_site_icon_mode(self):
        configured = (
            "<html><head>"
            '<link rel="stylesheet" href="/wp-content/themes/robbottx/'
            'style.css?ver=0.1.3">'
            '<link rel="icon" href="/wp-content/uploads/site-icon.png">'
            "</head><body>"
            '<main data-theme-release="0.1.3"></main>'
            "</body></html>"
        )
        with patch.object(
            deploy,
            "request",
            return_value=(
                200,
                "text/html; charset=UTF-8",
                configured,
            ),
        ):
            assets = deploy.verify_rendered_body(
                "https://example.test",
                "/",
                'data-theme-release="0.1.3"',
                'data-theme-release="0.1.2"',
                "robbottx",
                "0.1.3",
                False,
            )

        self.assertEqual(assets["favicon_mode"], "configured_site_icon")
        self.assertEqual(
            assets["favicon_path"],
            "/wp-content/uploads/site-icon.png",
        )

    def test_rendered_release_rejects_extra_escaped_asset_queries(self):
        rendered = (
            "<html><head>"
            '<link rel="stylesheet" href="/wp-content/themes/robbottx/'
            'style.css?cache=1&amp;ver=0.1.3">'
            '<link rel="icon" href="/wp-content/themes/robbottx/assets/'
            'favicon.svg?cache=1&amp;ver=0.1.3">'
            "</head><body>"
            '<main data-theme-release="0.1.3"></main>'
            "</body></html>"
        )
        with patch.object(
            deploy,
            "request",
            return_value=(
                200,
                "text/html; charset=UTF-8",
                rendered,
            ),
        ):
            with self.assertRaises(deploy.DeployFailure):
                deploy.verify_rendered_body(
                    "https://example.test",
                    "/",
                    'data-theme-release="0.1.3"',
                    'data-theme-release="0.1.2"',
                    "robbottx",
                    "0.1.3",
                    True,
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

    def test_snippet_capacity_allows_98_and_rejects_99(self):
        for count, accepted in ((98, True), (99, False), (100, False)):
            with self.subTest(count=count):
                response = (
                    200,
                    "application/json",
                    json.dumps([{"id": index + 1} for index in range(count)]),
                )
                with patch.object(
                    deploy,
                    "request",
                    return_value=response,
                ):
                    if accepted:
                        self.assertEqual(
                            deploy.require_snippet_capacity(
                                "https://robbottx.com",
                                "Basic redacted",
                            ),
                            count,
                        )
                    else:
                        with self.assertRaises(deploy.DeployFailure):
                            deploy.require_snippet_capacity(
                                "https://robbottx.com",
                                "Basic redacted",
                            )

    def test_browser_resolution_and_exact_asset_fetch_with_same_origin_base(self):
        document = (
            "<html><head>"
            '<base href="/"><base href="https://example.test/">'
            '<link rel="stylesheet" href="wp-content/themes/robbottx/'
            'style.css?ver=0.1.3">'
            '<link rel="icon" href="wp-content/themes/robbottx/assets/'
            'favicon.svg?ver=0.1.3">'
            "</head><body>"
            '<main data-theme-release="0.1.3"></main>'
            "</body></html>"
        )
        requested_urls = []

        def side_effect(url, **kwargs):
            requested_urls.append(url)
            if "rbtxcb=" in url:
                return (200, "text/html; charset=UTF-8", document)
            if url.endswith("style.css?ver=0.1.3"):
                return (200, "text/css; charset=UTF-8", "body{}")
            if url.endswith("favicon.svg?ver=0.1.3"):
                return (
                    200,
                    "image/svg+xml",
                    '<svg xmlns="http://www.w3.org/2000/svg"></svg>',
                )
            raise AssertionError(url)

        with patch.object(deploy, "request", side_effect=side_effect):
            result = deploy.verify_rendered_transition(
                "https://example.test",
                "/catalog/item/",
                'data-theme-release="0.1.3"',
                'data-theme-release="0.1.2"',
                "robbottx",
                "0.1.3",
                {
                    "id": 0,
                    "mime_by_url": {},
                    "mode": "theme_fallback",
                    "urls": set(),
                },
            )

        self.assertEqual(result["base_mode"], "same_origin_base")
        self.assertIn(
            "https://example.test/wp-content/themes/robbottx/"
            "style.css?ver=0.1.3",
            requested_urls,
        )
        self.assertIn(
            "https://example.test/wp-content/themes/robbottx/assets/"
            "favicon.svg?ver=0.1.3",
            requested_urls,
        )

    def test_relative_assets_resolve_against_nested_document_url(self):
        document = (
            "<html><head>"
            '<link rel="stylesheet" href="../../wp-content/themes/robbottx/'
            'style.css?ver=0.1.3">'
            '<link rel="icon" href="../../wp-content/themes/robbottx/assets/'
            'favicon.svg?ver=0.1.3">'
            "</head><body>"
            '<main data-theme-release="0.1.3"></main>'
            "</body></html>"
        )
        requested_urls = []

        def side_effect(url, **kwargs):
            requested_urls.append(url)
            if "rbtxcb=" in url:
                return (200, "text/html", document)
            if url.endswith("style.css?ver=0.1.3"):
                return (200, "text/css", "body{}")
            return (
                200,
                "image/svg+xml",
                '<svg xmlns="http://www.w3.org/2000/svg"></svg>',
            )

        with patch.object(deploy, "request", side_effect=side_effect):
            result = deploy.verify_rendered_transition(
                "https://example.test",
                "/catalog/item/",
                'data-theme-release="0.1.3"',
                'data-theme-release="0.1.2"',
                "robbottx",
                "0.1.3",
                {
                    "id": 0,
                    "mime_by_url": {},
                    "mode": "theme_fallback",
                    "urls": set(),
                },
            )
        self.assertEqual(result["base_mode"], "document_url")
        self.assertIn(
            "https://example.test/wp-content/themes/robbottx/"
            "style.css?ver=0.1.3",
            requested_urls,
        )

    def test_external_or_mixed_base_is_rejected_before_asset_fetch(self):
        base_tags = [
            '<base href="https://evil.test/">',
            '<base href="/one/"><base href="/two/">',
            "<base>",
        ]
        for base_markup in base_tags:
            with self.subTest(base_markup=base_markup):
                document = (
                    "<html><head>"
                    + base_markup
                    + '<link rel="stylesheet" href="/wp-content/themes/'
                    'robbottx/style.css?ver=0.1.3">'
                    '<link rel="icon" href="/wp-content/themes/robbottx/'
                    'assets/favicon.svg?ver=0.1.3">'
                    "</head><body>"
                    '<main data-theme-release="0.1.3"></main>'
                    "</body></html>"
                )
                with patch.object(
                    deploy,
                    "request",
                    return_value=(
                        200,
                        "text/html; charset=UTF-8",
                        document,
                    ),
                ) as request_mock:
                    with self.assertRaises(deploy.DeployFailure):
                        deploy.verify_rendered_transition(
                            "https://example.test",
                            "/nested/",
                            'data-theme-release="0.1.3"',
                            'data-theme-release="0.1.2"',
                            "robbottx",
                            "0.1.3",
                            {
                                "id": 0,
                                "mime_by_url": {},
                                "mode": "theme_fallback",
                                "urls": set(),
                            },
                        )
                self.assertEqual(request_mock.call_count, 1)

    def test_exact_asset_fetch_rejects_bad_status_type_and_svg(self):
        document = (
            "<html><head>"
            '<link rel="stylesheet" href="/wp-content/themes/robbottx/'
            'style.css?ver=0.1.3">'
            '<link rel="icon" href="/wp-content/themes/robbottx/assets/'
            'favicon.svg?ver=0.1.3">'
            "</head><body>"
            '<main data-theme-release="0.1.3"></main>'
            "</body></html>"
        )
        invalid_asset_responses = [
            (404, "text/css", "missing"),
            (200, "text/html", "<html></html>"),
            (200, "image/svg+xml", "<not-svg></not-svg>"),
        ]
        for invalid_response in invalid_asset_responses:
            with self.subTest(response=invalid_response[:2]):
                responses = [
                    (200, "text/html; charset=UTF-8", document),
                    (200, "text/css", "body{}"),
                    invalid_response,
                ]
                if invalid_response[1] != "image/svg+xml":
                    responses = [
                        (200, "text/html; charset=UTF-8", document),
                        invalid_response,
                    ]
                with patch.object(
                    deploy,
                    "request",
                    side_effect=responses,
                ):
                    with self.assertRaises(deploy.DeployFailure):
                        deploy.verify_rendered_transition(
                            "https://example.test",
                            "/",
                            'data-theme-release="0.1.3"',
                            'data-theme-release="0.1.2"',
                            "robbottx",
                            "0.1.3",
                            {
                                "id": 0,
                                "mime_by_url": {},
                                "mode": "theme_fallback",
                                "urls": set(),
                            },
                        )

    def test_configured_icon_is_bound_to_authenticated_media_identity(self):
        media_url = (
            "https://robbottx.com/wp-content/uploads/site-icon-512.png"
        )
        responses = [
            (200, "application/json", '{"site_icon":42}'),
            (
                200,
                "application/json",
                json.dumps(
                    {
                        "id": 42,
                        "source_url": media_url,
                        "media_type": "image",
                        "mime_type": "image/png",
                        "media_details": {
                            "sizes": {
                                "thumbnail": {
                                    "source_url": (
                                        "https://robbottx.com/wp-content/"
                                        "uploads/site-icon-150.png"
                                    ),
                                    "mime_type": "image/png",
                                }
                            }
                        },
                    }
                ),
            ),
        ]
        with patch.object(deploy, "request", side_effect=responses):
            identity = deploy.read_site_icon_identity(
                "https://robbottx.com",
                "Basic redacted",
                expect_fallback_favicon=False,
            )
        self.assertEqual(identity["id"], 42)
        self.assertIn(media_url, identity["urls"])

        valid_document = (
            "<html><head>"
            '<link rel="stylesheet" href="/wp-content/themes/robbottx/'
            'style.css?ver=0.1.3">'
            f'<link rel="icon" href="{media_url}">'
            "</head><body>"
            '<main data-theme-release="0.1.3"></main>'
            "</body></html>"
        )
        with patch.object(
            deploy,
            "request",
            side_effect=[
                (200, "text/html", valid_document),
                (200, "text/css", "body{}"),
                (200, "image/png", "PNG"),
            ],
        ):
            rendered = deploy.verify_rendered_transition(
                "https://robbottx.com",
                "/",
                'data-theme-release="0.1.3"',
                'data-theme-release="0.1.2"',
                "robbottx",
                "0.1.3",
                identity,
            )
        self.assertEqual(rendered["favicon_mode"], "configured_site_icon")

        mismatch_document = valid_document.replace(
            media_url,
            "https://robbottx.com/wp-content/uploads/unrelated.png",
        )
        with patch.object(
            deploy,
            "request",
            side_effect=[
                (200, "text/html", mismatch_document),
                (200, "text/css", "body{}"),
            ],
        ):
            with self.assertRaises(deploy.DeployFailure):
                deploy.verify_rendered_transition(
                    "https://robbottx.com",
                    "/",
                    'data-theme-release="0.1.3"',
                    'data-theme-release="0.1.2"',
                    "robbottx",
                    "0.1.3",
                    identity,
                )

    def test_favicon_modes_conflict_with_authenticated_settings(self):
        for site_icon, expect_fallback in ((42, True), (0, False)):
            with self.subTest(
                site_icon=site_icon,
                expect_fallback=expect_fallback,
            ):
                with patch.object(
                    deploy,
                    "request",
                    return_value=(
                        200,
                        "application/json",
                        json.dumps({"site_icon": site_icon}),
                    ),
                ):
                    with self.assertRaises(deploy.DeployFailure):
                        deploy.read_site_icon_identity(
                            "https://robbottx.com",
                            "Basic redacted",
                            expect_fallback_favicon=expect_fallback,
                        )

    def test_atomic_evidence_refuses_overwrite_and_removes_failed_temporary(self):
        output_path = (
            Path(self.temporary_directory.name) / "atomic-evidence.json"
        )
        deploy.write_new_evidence(output_path, {"status": "ok"})
        self.assertEqual(
            json.loads(output_path.read_text(encoding="utf-8")),
            {"status": "ok"},
        )
        with self.assertRaises(deploy.DeployFailure):
            deploy.write_new_evidence(output_path, {"status": "replacement"})
        self.assertEqual(
            json.loads(output_path.read_text(encoding="utf-8")),
            {"status": "ok"},
        )

        failed_path = (
            Path(self.temporary_directory.name) / "failed-evidence.json"
        )
        with (
            patch.object(deploy.os, "link", side_effect=OSError("sentinel")),
            self.assertRaises(deploy.DeployFailure),
        ):
            deploy.write_new_evidence(failed_path, {"status": "failed"})
        self.assertFalse(failed_path.exists())
        self.assertEqual(
            list(Path(self.temporary_directory.name).glob(".*.tmp-*")),
            [],
        )

        with self.assertRaises(deploy.DeployFailure):
            deploy.require_allowlisted_evidence(
                {
                    "status": "failed",
                    "raw_response_body": "sentinel-private-body",
                }
            )

    def test_main_writes_failure_receipt_and_refuses_existing_output(self):
        archive_bytes = make_theme_zip()
        args = self.valid_args(archive_bytes, execute=False)
        args.previous_version = args.version
        stdout = io.StringIO()
        with (
            patch.object(deploy, "parse_args", return_value=args),
            redirect_stdout(stdout),
            self.assertRaises(deploy.DeployFailure),
        ):
            deploy.main()
        receipt = json.loads(args.output.read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(receipt["failure_stage"], "input_validation")
        self.assertFalse(receipt["cleanup"]["attempted"])
        self.assertFalse(receipt["cleanup"]["proven"])
        self.assertIsNone(receipt["cleanup"]["route_absent"])
        self.assertIsNone(receipt["cleanup"]["snippet_absent"])

        original = args.output.read_bytes()
        with (
            patch.object(deploy, "parse_args", return_value=args),
            self.assertRaises(deploy.DeployFailure),
        ):
            deploy.main()
        self.assertEqual(args.output.read_bytes(), original)

    def test_route_template_is_unique_and_binds_verified_artifact(self):
        route_code = deploy.build_route_code(
            route_template=THEME_ROUTE_TEMPLATE,
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

    def test_callback_parser_rejects_duplicate_extra_and_truthy_fields(self):
        valid = {
            "result": True,
            "active": True,
            "stylesheet": "robbottx",
            "template": "robbottx",
            "version": "0.1.3",
            "artifact_verified": True,
        }
        deploy.confirm_exact_deployment_callback(
            200,
            "application/json",
            json.dumps(valid),
            theme_slug="robbottx",
            version="0.1.3",
        )
        duplicate = json.dumps(valid, separators=(",", ":")).replace(
            '"result":true',
            '"result":true,"result":true',
            1,
        )
        invalid_bodies = (
            duplicate,
            json.dumps({**valid, "unexpected": True}),
            json.dumps({**valid, "artifact_verified": 1}),
        )
        for body in invalid_bodies:
            with self.subTest(body=body):
                with self.assertRaises(deploy.DeployFailure):
                    deploy.confirm_exact_deployment_callback(
                        200,
                        "application/json",
                        body,
                        theme_slug="robbottx",
                        version="0.1.3",
                    )

    def test_action_boundary_recheck_blocks_snippet_creation(self):
        archive_bytes = make_theme_zip()
        args = self.valid_args(archive_bytes)
        requested_urls = []

        def request_side_effect(url, **kwargs):
            requested_urls.append((url, kwargs.get("method", "GET")))
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
            raise AssertionError(f"Unexpected request: {url}")

        icon_identity = {
            "id": 0,
            "mime_by_url": {},
            "mode": "theme_fallback",
            "urls": set(),
        }
        evidence = {"execute": True, "status": "started"}
        with (
            patch.object(
                deploy,
                "validate_theme_boundary_receipt",
                side_effect=[
                    self.boundary_result(args),
                    deploy.DeployFailure("current scan changed"),
                ],
            ),
            patch.object(
                deploy,
                "required_env",
                side_effect=[
                    "https://robbottx.com",
                    "release-operator",
                    "sentinel-private-value",
                ],
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
                "require_snippet_capacity",
                return_value=12,
            ),
            patch.object(
                deploy,
                "verify_theme_rest_record",
                return_value={
                    "version": args.previous_version,
                },
            ),
            patch.object(
                deploy,
                "read_site_icon_identity",
                return_value=icon_identity,
            ),
            patch.object(
                deploy,
                "verify_rendered_transition",
                return_value={
                    "assets_fetched": True,
                    "base_mode": "document_url",
                    "favicon_mode": "theme_fallback",
                    "favicon_path": (
                        "/wp-content/themes/robbottx/assets/favicon.svg"
                    ),
                    "icon_count": 1,
                    "stylesheet_path": (
                        "/wp-content/themes/robbottx/style.css"
                    ),
                    "version": args.previous_version,
                },
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
            self.assertRaises(deploy.DeployFailure),
        ):
            deploy._run_deployment(args, evidence)

        self.assertEqual(evidence["failure_stage"], "action_boundary")
        self.assertFalse(
            any(
                url.endswith("/wp-json/code-snippets/v1/snippets")
                and method == "POST"
                for url, method in requested_urls
            )
        )
        self.assertTrue(evidence["cleanup"]["proven"])

    def test_callback_artifact_confirmation_is_required_for_success(self):
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
                return (
                    200,
                    "application/json",
                    json.dumps(
                        {
                            "result": True,
                            "active": True,
                            "stylesheet": "robbottx",
                            "template": "robbottx",
                            "version": "0.1.3",
                            "artifact_verified": False,
                        }
                    ),
                )
            raise AssertionError(url)

        icon_identity = {
            "id": 0,
            "mime_by_url": {},
            "mode": "theme_fallback",
            "urls": set(),
        }
        render_result = {
            "assets_fetched": True,
            "base_mode": "document_url",
            "favicon_mode": "theme_fallback",
            "favicon_path": (
                "/wp-content/themes/robbottx/assets/favicon.svg"
            ),
            "icon_count": 1,
            "stylesheet_path": "/wp-content/themes/robbottx/style.css",
            "version": "0.1.3",
        }
        evidence = {
            "execute": True,
            "previous_version": "0.1.2",
            "status": "started",
            "target_version": "0.1.3",
            "theme": "robbottx",
        }
        with (
            patch.object(
                deploy,
                "validate_theme_boundary_receipt",
                return_value=self.boundary_result(args),
            ),
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
                "require_snippet_capacity",
                return_value=10,
            ),
            patch.object(
                deploy,
                "verify_theme_rest_record",
                side_effect=[
                    {"version": "0.1.2"},
                    {"version": "0.1.3"},
                ],
            ),
            patch.object(
                deploy,
                "read_site_icon_identity",
                side_effect=[icon_identity, icon_identity],
            ),
            patch.object(
                deploy,
                "verify_rendered_transition",
                side_effect=[
                    {**render_result, "version": "0.1.2"},
                    render_result,
                ],
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
            self.assertRaises(deploy.DeployFailure),
        ):
            deploy._run_deployment(args, evidence)

        self.assertFalse(evidence["callback"]["confirmed"])
        self.assertTrue(evidence["cleanup"]["proven"])
        self.assertEqual(evidence["failure_stage"], "deployment_callback")

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
                    200,
                    "application/json",
                    json.dumps(
                        {
                            "result": True,
                            "active": True,
                            "stylesheet": "robbottx",
                            "template": "robbottx",
                            "version": "0.1.3",
                            "artifact_verified": True,
                        }
                    ),
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
                        "<html><head>"
                        '<link rel="stylesheet" href="/wp-content/themes/'
                        'robbottx/style.css?ver=0.1.3">'
                        '<link rel="icon" href="/wp-content/themes/robbottx/'
                        'assets/favicon.svg?ver=0.1.3">'
                        "</head><body>"
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
                "validate_theme_boundary_receipt",
                return_value=self.boundary_result(args),
            ),
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
                "require_snippet_capacity",
                return_value=12,
            ),
            patch.object(
                deploy,
                "verify_theme_rest_record",
                side_effect=[
                    {
                        "stylesheet": "robbottx",
                        "template": "robbottx",
                        "status": "active",
                        "version": "0.1.2",
                        "is_block_theme": True,
                    },
                    {
                        "stylesheet": "robbottx",
                        "template": "robbottx",
                        "status": "active",
                        "version": "0.1.3",
                        "is_block_theme": True,
                    },
                ],
            ) as theme_state_verify,
            patch.object(
                deploy,
                "read_site_icon_identity",
                side_effect=[
                    {
                        "id": 0,
                        "mime_by_url": {},
                        "mode": "theme_fallback",
                        "urls": set(),
                    },
                    {
                        "id": 0,
                        "mime_by_url": {},
                        "mode": "theme_fallback",
                        "urls": set(),
                    },
                ],
            ),
            patch.object(
                deploy,
                "verify_rendered_transition",
                side_effect=[
                    {
                        "assets_fetched": True,
                        "base_mode": "document_url",
                        "favicon_mode": "theme_fallback",
                        "favicon_path": (
                            "/wp-content/themes/robbottx/assets/favicon.svg"
                        ),
                        "icon_count": 1,
                        "stylesheet_path": (
                            "/wp-content/themes/robbottx/style.css"
                        ),
                        "version": "0.1.2",
                    },
                    {
                        "assets_fetched": True,
                        "base_mode": "document_url",
                        "favicon_mode": "theme_fallback",
                        "favicon_path": (
                            "/wp-content/themes/robbottx/assets/favicon.svg"
                        ),
                        "icon_count": 1,
                        "stylesheet_path": (
                            "/wp-content/themes/robbottx/style.css"
                        ),
                        "version": "0.1.3",
                    },
                ],
            ) as rendered_transition_verify,
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
        self.assertTrue(evidence["callback"]["confirmed"])
        self.assertTrue(evidence["cleanup"]["snippet_absent"])
        self.assertEqual(evidence["before"]["active_version"], "0.1.2")
        self.assertEqual(evidence["after"]["active_version"], "0.1.3")
        self.assertEqual(
            [
                call.args[3]
                for call in theme_state_verify.call_args_list
            ],
            ["0.1.2", "0.1.3"],
        )
        self.assertEqual(
            [
                (call.args[2], call.args[3], call.args[5])
                for call in rendered_transition_verify.call_args_list
            ],
            [
                (
                    'data-theme-release="0.1.2"',
                    'data-theme-release="0.1.3"',
                    "0.1.2",
                ),
                (
                    'data-theme-release="0.1.3"',
                    'data-theme-release="0.1.2"',
                    "0.1.3",
                ),
            ],
        )
        self.assertEqual(
            json.loads(args.output.read_text(encoding="utf-8")),
            evidence,
        )
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
                "validate_theme_boundary_receipt",
                return_value=self.boundary_result(args),
            ),
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
                "require_snippet_capacity",
                return_value=12,
            ),
            patch.object(
                deploy,
                "verify_theme_rest_record",
                return_value={
                    "stylesheet": "robbottx",
                    "template": "robbottx",
                    "status": "active",
                    "version": "0.1.2",
                    "is_block_theme": True,
                },
            ),
            patch.object(
                deploy,
                "read_site_icon_identity",
                return_value={
                    "id": 0,
                    "mime_by_url": {},
                    "mode": "theme_fallback",
                    "urls": set(),
                },
            ),
            patch.object(
                deploy,
                "verify_rendered_transition",
                return_value={
                    "assets_fetched": True,
                    "base_mode": "document_url",
                    "favicon_mode": "theme_fallback",
                    "favicon_path": (
                        "/wp-content/themes/robbottx/assets/favicon.svg"
                    ),
                    "icon_count": 1,
                    "stylesheet_path": (
                        "/wp-content/themes/robbottx/style.css"
                    ),
                    "version": "0.1.2",
                },
            ),
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
            redirect_stdout(io.StringIO()),
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
        failure_receipt = json.loads(
            args.output.read_text(encoding="utf-8")
        )
        self.assertEqual(failure_receipt["status"], "failed")
        self.assertTrue(failure_receipt["cleanup"]["attempted"])
        self.assertFalse(failure_receipt["cleanup"]["proven"])

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
                return (
                    200,
                    "application/json",
                    json.dumps(
                        {
                            "result": True,
                            "active": True,
                            "stylesheet": "robbottx",
                            "template": "robbottx",
                            "version": "0.1.3",
                            "artifact_verified": True,
                        }
                    ),
                )
            raise AssertionError(f"Unexpected mocked request: {url}")

        with (
            patch.object(deploy, "parse_args", return_value=args),
            patch.object(
                deploy,
                "validate_theme_boundary_receipt",
                return_value=self.boundary_result(args),
            ),
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
                "require_snippet_capacity",
                return_value=12,
            ),
            patch.object(
                deploy,
                "verify_theme_rest_record",
                side_effect=[
                    {
                        "stylesheet": "robbottx",
                        "template": "robbottx",
                        "status": "active",
                        "version": "0.1.2",
                        "is_block_theme": True,
                    },
                    {
                        "stylesheet": "robbottx",
                        "template": "robbottx",
                        "status": "active",
                        "version": "0.1.3",
                        "is_block_theme": True,
                    },
                ],
            ) as rest_verify,
            patch.object(
                deploy,
                "read_site_icon_identity",
                side_effect=[
                    {
                        "id": 0,
                        "mime_by_url": {},
                        "mode": "theme_fallback",
                        "urls": set(),
                    },
                    {
                        "id": 0,
                        "mime_by_url": {},
                        "mode": "theme_fallback",
                        "urls": set(),
                    },
                ],
            ),
            patch.object(
                deploy,
                "verify_rendered_transition",
                side_effect=[
                    {
                        "assets_fetched": True,
                        "base_mode": "document_url",
                        "favicon_mode": "theme_fallback",
                        "favicon_path": (
                            "/wp-content/themes/robbottx/assets/favicon.svg"
                        ),
                        "icon_count": 1,
                        "stylesheet_path": (
                            "/wp-content/themes/robbottx/style.css"
                        ),
                        "version": "0.1.2",
                    },
                    deploy.DeployFailure(
                        "Old rendered-body marker is still present."
                    ),
                ],
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
            redirect_stdout(io.StringIO()),
        ):
            with self.assertRaises(deploy.DeployFailure) as raised:
                deploy.main()

        self.assertEqual(rest_verify.call_count, 2)
        self.assertEqual(render_verify.call_count, 2)
        cleanup.assert_called_once()
        self.assertIn(
            "rendered release verification failed",
            str(raised.exception),
        )
        self.assertNotIn(
            "Old rendered-body marker",
            str(raised.exception),
        )
        failure_receipt = json.loads(
            args.output.read_text(encoding="utf-8")
        )
        self.assertEqual(failure_receipt["status"], "failed")
        self.assertTrue(failure_receipt["cleanup"]["proven"])


if __name__ == "__main__":
    unittest.main()
