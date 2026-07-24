from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from contextlib import redirect_stdout


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "deploy-wordpress-robots.py"
SPEC = importlib.util.spec_from_file_location(
    "deploy_wordpress_robots",
    SCRIPT,
)
assert SPEC is not None and SPEC.loader is not None
robots = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = robots
SPEC.loader.exec_module(robots)

ROBOTS_PAYLOAD = (ROOT / "hosting" / "robots.txt").read_bytes()
ROUTE_TEMPLATE = (
    ROOT
    / "scripts"
    / "templates"
    / "deploy-robots-route.php.txt"
).read_text(encoding="utf-8")
COMMIT = "d" * 40
ROBOTS_SHA256 = hashlib.sha256(ROBOTS_PAYLOAD).hexdigest()
ROUTE_TOKEN = "robots-1700000000-" + ("a1" * 16)
ROUTE_PATH = f"/wp-json/agentrobots/v1/run-{ROUTE_TOKEN}"
BASE_URL = "https://robbottx.com"
AUTH = "Basic redacted"


class DeployWordPressRobotsTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)

    def valid_args(self, *, execute=True):
        return SimpleNamespace(
            commit=COMMIT,
            robots_url=(
                "https://raw.githubusercontent.com/The-new-ben/"
                f"robbottx-enterprise/{COMMIT}/hosting/robots.txt"
            ),
            robots_size=len(ROBOTS_PAYLOAD),
            robots_sha256=ROBOTS_SHA256,
            boundary_receipt=(
                Path(self.temporary_directory.name)
                / "robots-boundary.json"
            ),
            output=(
                Path(self.temporary_directory.name)
                / "robots-evidence.json"
            ),
            execute=execute,
        )

    def fake_ops(self):
        ops = SimpleNamespace()
        ops.DeployFailure = RuntimeError
        ops.normalize_base_url = MagicMock(return_value=BASE_URL)
        ops.required_env = MagicMock(
            side_effect=[BASE_URL, "release-admin", "not-recorded"]
        )
        ops.make_auth = MagicMock(return_value=AUTH)
        ops.make_route_token = MagicMock(return_value=ROUTE_TOKEN)
        ops.require_snippet_name_absent = MagicMock()
        ops.require_snippet_capacity = MagicMock(return_value=7)
        ops.cleanup_temporary_snippets = MagicMock(
            return_value=(True, [])
        )
        ops.request = MagicMock()
        return ops

    def release_context(self, ops=None):
        return robots.ReleaseContext(
            git_head=COMMIT,
            ops=ops or self.fake_ops(),
            ops_payload_sha256="a" * 64,
            receipt_body_sha256="b" * 64,
            robots_payload=ROBOTS_PAYLOAD,
            route_template=ROUTE_TEMPLATE,
        )

    @staticmethod
    def evidence(execute):
        return {
            "execute": execute,
            "recorded_at": "2026-07-24T00:00:00+00:00",
            "schema_version": 1,
            "status": "started",
        }

    def test_inputs_require_commit_pinned_url_exact_size_and_hash(self):
        valid = vars(self.valid_args(execute=False))
        invalid = (
            {"commit": "D" * 40},
            {
                "robots_url": (
                    "https://raw.githubusercontent.com/The-new-ben/"
                    "robbottx-enterprise/main/hosting/robots.txt"
                )
            },
            {"robots_url": valid["robots_url"] + "?cache=1"},
            {"robots_size": 0},
            {"robots_size": True},
            {"robots_sha256": ROBOTS_SHA256.upper()},
        )
        for change in invalid:
            with self.subTest(change=change):
                args = SimpleNamespace(**{**valid, **change})
                with self.assertRaises(robots.DeployFailure):
                    robots.validate_inputs(args)

    def test_route_is_admin_gated_atomic_and_never_overwrites_target(self):
        args = self.valid_args()
        code = robots.build_route_code(
            route_template=ROUTE_TEMPLATE,
            route_token=ROUTE_TOKEN,
            robots_url=args.robots_url,
            robots_size=args.robots_size,
            robots_sha256=args.robots_sha256,
        )

        self.assertIn("current_user_can( 'update_plugins' )", code)
        self.assertIn("current_user_can( 'manage_options' )", code)
        self.assertIn("$target          = ABSPATH . 'robots.txt';", code)
        self.assertIn("@fopen( $temp, 'x+b' )", code)
        self.assertEqual(code.count("@link( $temp, $target )"), 1)
        self.assertIn("agentrobots_existing_conflict", code)
        self.assertIn("! $before['matches']", code)
        self.assertRegex(code, r"'redirection'\s*=> 0")
        self.assertIn(
            "'limit_response_size' => $expected_size + 1",
            code,
        )
        self.assertIn("do_action( 'litespeed_purge_all' )", code)
        self.assertIn("wp_cache_flush()", code)
        self.assertIn("temporary_files_absent", code)
        self.assertNotIn("rename( $temp, $target", code)
        self.assertNotIn("unlink( $target", code)
        self.assertNotIn("file_put_contents( $target", code)
        self.assertNotIn(args.robots_url, code)
        self.assertNotIn("{{", code)

        completed = subprocess.run(
            ["php", "-l"],
            input="<?php\n" + code,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stderr or completed.stdout,
        )

    def test_callback_and_state_parsers_reject_duplicate_or_ambiguous_json(self):
        args = self.valid_args()
        callback = {
            "result": True,
            "created": True,
            "existing_exact": False,
            "artifact_verified": True,
            "bytes": args.robots_size,
            "sha256": args.robots_sha256,
            "cache_flush_sent": True,
            "temporary_files_absent": True,
        }
        self.assertEqual(
            robots.confirm_exact_callback(
                200,
                "application/json",
                json.dumps(callback),
                args,
            ),
            (True, False),
        )
        duplicate = json.dumps(
            callback,
            separators=(",", ":"),
        ).replace(
            '"result":true',
            '"result":true,"result":true',
            1,
        )
        invalid = (
            duplicate,
            json.dumps({**callback, "unexpected": True}),
            json.dumps({**callback, "artifact_verified": 1}),
            json.dumps(
                {
                    **callback,
                    "created": True,
                    "existing_exact": True,
                }
            ),
        )
        for body in invalid:
            with self.subTest(body=body):
                with self.assertRaises(robots.DeployFailure):
                    robots.confirm_exact_callback(
                        200,
                        "application/json",
                        body,
                        args,
                    )

        state = {
            "exists": True,
            "regular_file": True,
            "matches": True,
            "bytes": args.robots_size,
            "sha256": args.robots_sha256,
            "temporary_files_absent": False,
        }
        with self.assertRaises(robots.DeployFailure):
            robots.confirm_exact_authenticated_state(
                200,
                "application/json",
                json.dumps(state),
                args,
            )

    def test_boundary_binds_exact_non_zip_artifact_and_frozen_inputs(self):
        args = self.valid_args(execute=False)
        captured = {}
        ops_source = (
            "class DeployFailure(RuntimeError):\n"
            "    pass\n"
            "def cleanup_temporary_snippets(*args, **kwargs): pass\n"
            "def make_auth(*args, **kwargs): pass\n"
            "def make_route_token(*args, **kwargs): pass\n"
            "def normalize_base_url(*args, **kwargs): pass\n"
            "def request(*args, **kwargs): pass\n"
            "def require_snippet_capacity(*args, **kwargs): pass\n"
            "def require_snippet_name_absent(*args, **kwargs): pass\n"
            "def required_env(*args, **kwargs): pass\n"
        ).encode("utf-8")

        def read_index(_root, relative_path, **_kwargs):
            values = {
                robots.OPS_RELATIVE_PATH: ops_source,
                robots.ROUTE_TEMPLATE_RELATIVE_PATH: (
                    ROUTE_TEMPLATE.encode("utf-8")
                ),
                robots.ROBOTS_RELATIVE_PATH: ROBOTS_PAYLOAD,
            }
            return values[relative_path], COMMIT

        scan_report = SimpleNamespace(
            git_head=COMMIT,
            public_snapshot_payload_sha256="c" * 64,
        )

        def validate(receipt, **kwargs):
            captured["receipt"] = receipt
            captured["kwargs"] = kwargs
            return {
                "artifact_path": robots.ROBOTS_RELATIVE_PATH,
                "git_head": COMMIT,
                "receipt_body_sha256": "b" * 64,
            }

        verifier = SimpleNamespace(
            DeployFailure=RuntimeError,
            read_clean_index_file=read_index,
            run_reviewed_boundary_scan=lambda _root: scan_report,
            validate_boundary_receipt=validate,
        )
        with patch.object(
            robots,
            "load_head_index_module",
            return_value=(verifier, b"verifier", COMMIT),
        ):
            release = robots.prepare_release_boundary(args)

        self.assertEqual(release.robots_payload, ROBOTS_PAYLOAD)
        self.assertEqual(release.route_template, ROUTE_TEMPLATE)
        self.assertEqual(
            captured["kwargs"]["artifact_path"],
            "hosting/robots.txt",
        )
        self.assertEqual(
            captured["kwargs"]["zip_sha256"],
            ROBOTS_SHA256,
        )
        self.assertIs(
            captured["kwargs"]["scan_report"],
            scan_report,
        )

    def test_boundary_failure_precedes_credentials_and_network(self):
        args = self.valid_args(execute=False)
        evidence = self.evidence(False)
        with patch.object(
            robots,
            "prepare_release_boundary",
            side_effect=robots.DeployFailure("stale receipt"),
        ), patch.object(
            robots,
            "request_public_bytes",
        ) as public_request:
            with self.assertRaises(robots.DeployFailure):
                robots._run_deployment(args, evidence)

        self.assertEqual(evidence["failure_stage"], "public_boundary")
        public_request.assert_not_called()

    def test_public_root_rejects_nonmatching_existing_bytes(self):
        args = self.valid_args(execute=False)
        with patch.object(
            robots,
            "request_public_bytes",
            return_value=(200, "text/plain", b"User-agent: *\nDisallow: /\n"),
        ):
            with self.assertRaises(robots.DeployFailure):
                robots.read_public_robots_state(
                    BASE_URL,
                    args,
                    ROBOTS_PAYLOAD,
                    allow_absent=True,
                )

    def test_action_boundary_recheck_blocks_snippet_creation_and_cleans(self):
        args = self.valid_args()
        ops = self.fake_ops()
        release = self.release_context(ops)
        evidence = self.evidence(True)
        with patch.object(
            robots,
            "prepare_release_boundary",
            side_effect=[
                release,
                robots.DeployFailure("current scan changed"),
            ],
        ), patch.object(
            robots,
            "verify_raw_source",
        ), patch.object(
            robots,
            "verify_authority",
        ), patch.object(
            robots,
            "require_robots_namespace_absent",
        ), patch.object(
            robots,
            "require_route_absent",
        ), patch.object(
            robots,
            "read_public_robots_state",
            return_value=("absent", 404, "text/plain"),
        ), patch.object(
            robots,
            "prove_route_absent",
            return_value=(True, []),
        ), patch.object(
            robots,
            "prove_robots_namespace_absent",
            return_value=(True, []),
        ):
            with self.assertRaises(robots.DeployFailure):
                robots._run_deployment(args, evidence)

        self.assertEqual(evidence["failure_stage"], "action_boundary")
        ops.request.assert_not_called()
        ops.cleanup_temporary_snippets.assert_called_once()
        self.assertTrue(evidence["cleanup"]["proven"])

    def run_execute(self, callback_response, *, expect_failure=False):
        args = self.valid_args()
        ops = self.fake_ops()
        release = self.release_context(ops)
        callback_body = callback_response
        state_body = json.dumps(
            {
                "exists": True,
                "regular_file": True,
                "matches": True,
                "bytes": args.robots_size,
                "sha256": args.robots_sha256,
                "temporary_files_absent": True,
            }
        )
        ops.request.side_effect = [
            (201, "application/json", '{"id":73}'),
            callback_body,
            (200, "application/json", state_body),
        ]
        evidence = self.evidence(True)
        with patch.object(
            robots,
            "prepare_release_boundary",
            return_value=release,
        ), patch.object(
            robots,
            "verify_raw_source",
        ), patch.object(
            robots,
            "verify_authority",
        ), patch.object(
            robots,
            "require_robots_namespace_absent",
        ), patch.object(
            robots,
            "require_route_absent",
        ), patch.object(
            robots,
            "read_public_robots_state",
            side_effect=[
                ("absent", 404, "text/plain"),
                ("exact", 200, "text/plain; charset=utf-8"),
            ],
        ), patch.object(
            robots,
            "prove_route_absent",
            return_value=(True, []),
        ), patch.object(
            robots,
            "prove_robots_namespace_absent",
            return_value=(True, []),
        ):
            if expect_failure:
                with self.assertRaises(robots.DeployFailure):
                    robots._run_deployment(args, evidence)
            else:
                robots._run_deployment(args, evidence)
        return args, ops, evidence

    def test_execute_requires_independent_authenticated_and_public_proof(self):
        args = self.valid_args()
        callback = (
            200,
            "application/json",
            json.dumps(
                {
                    "result": True,
                    "created": True,
                    "existing_exact": False,
                    "artifact_verified": True,
                    "bytes": args.robots_size,
                    "sha256": args.robots_sha256,
                    "cache_flush_sent": True,
                    "temporary_files_absent": True,
                }
            ),
        )
        _, ops, evidence = self.run_execute(callback)

        self.assertEqual(evidence["status"], "deployed")
        self.assertTrue(evidence["callback"]["confirmed"])
        self.assertTrue(evidence["callback"]["created"])
        self.assertEqual(
            evidence["public"],
            {
                "content_type": "text/plain",
                "exact_bytes": True,
                "status": 200,
            },
        )
        self.assertTrue(evidence["cleanup"]["proven"])
        creation = ops.request.call_args_list[0]
        self.assertEqual(creation.kwargs["method"], "POST")
        self.assertIn("ABSPATH . 'robots.txt'", creation.kwargs["payload"]["code"])

    def test_proxy_ambiguous_callback_uses_complete_independent_proof(self):
        _, _, evidence = self.run_execute(
            (502, "text/html", "<html>proxy error</html>")
        )

        self.assertEqual(evidence["status"], "deployed")
        self.assertFalse(evidence["callback"]["confirmed"])
        self.assertIsNone(evidence["callback"]["created"])
        self.assertTrue(evidence["public"]["exact_bytes"])
        self.assertTrue(evidence["cleanup"]["proven"])

    def test_html_404_callback_uses_complete_independent_proof(self):
        _, _, evidence = self.run_execute(
            (404, "text/html; charset=UTF-8", "<html>not found</html>")
        )

        self.assertEqual(evidence["status"], "deployed")
        self.assertFalse(evidence["callback"]["confirmed"])
        self.assertIsNone(evidence["callback"]["created"])
        self.assertTrue(evidence["public"]["exact_bytes"])
        self.assertTrue(evidence["cleanup"]["proven"])

    def test_proxy_ambiguity_rejects_json_and_non_html_404_responses(self):
        self.assertFalse(
            robots.is_proxy_ambiguous_callback_response(
                404,
                "application/json",
            )
        )
        self.assertFalse(
            robots.is_proxy_ambiguous_callback_response(
                404,
                "text/plain",
            )
        )
        self.assertFalse(
            robots.is_proxy_ambiguous_callback_response(
                200,
                "text/html",
            )
        )

    def test_public_robots_cache_buster_is_unique_per_call(self):
        with patch.object(
            robots.time,
            "time_ns",
            return_value=1_700_000_000_000_000_000,
        ), patch.object(
            robots.secrets,
            "token_hex",
            side_effect=("a" * 16, "b" * 16),
        ):
            first = robots.cache_busted_robots_url(BASE_URL)
            second = robots.cache_busted_robots_url(BASE_URL)

        self.assertNotEqual(first, second)
        self.assertEqual(
            first,
            (
                f"{BASE_URL}/robots.txt?"
                "rbtxcb=1700000000000000000-aaaaaaaaaaaaaaaa"
            ),
        )
        self.assertEqual(
            second,
            (
                f"{BASE_URL}/robots.txt?"
                "rbtxcb=1700000000000000000-bbbbbbbbbbbbbbbb"
            ),
        )

    def test_explicit_json_callback_failure_is_not_proxy_ambiguity(self):
        _, ops, evidence = self.run_execute(
            (
                500,
                "application/json",
                json.dumps(
                    {
                        "code": "agentrobots_write_failed",
                        "message": "redacted",
                        "data": {"status": 500},
                    }
                ),
            ),
            expect_failure=True,
        )

        self.assertEqual(ops.request.call_count, 2)
        self.assertFalse(evidence["callback"]["confirmed"])
        self.assertEqual(evidence["failure_stage"], "deployment_callback")
        self.assertTrue(evidence["cleanup"]["proven"])

    def test_allowlist_rejects_credentials_route_tokens_and_responses(self):
        for field in (
            "password",
            "route_token",
            "raw_response",
        ):
            with self.subTest(field=field):
                with self.assertRaises(robots.DeployFailure):
                    robots.require_allowlisted_evidence(
                        {
                            "status": "failed",
                            field: "must-not-persist",
                        }
                    )

    def test_main_writes_new_allowlisted_evidence_and_refuses_reuse(self):
        args = self.valid_args(execute=False)

        def preflight(_args, evidence):
            evidence["status"] = "preflight_ok"
            evidence["cleanup"] = {
                "attempted": False,
                "namespace_absent": True,
                "proven": True,
                "route_absent": True,
                "snippet_absent": True,
            }

        captured = io.StringIO()
        with patch.object(
            robots,
            "parse_args",
            return_value=args,
        ), patch.object(
            robots,
            "_run_deployment",
            side_effect=preflight,
        ), redirect_stdout(captured):
            self.assertEqual(robots.main(), 0)

        receipt_bytes = args.output.read_bytes()
        receipt = json.loads(receipt_bytes)
        self.assertEqual(receipt["status"], "preflight_ok")
        serialized = captured.getvalue()
        self.assertNotIn("not-recorded", serialized)
        self.assertNotIn("Basic ", serialized)

        with patch.object(robots, "parse_args", return_value=args):
            with self.assertRaises(robots.DeployFailure):
                robots.main()
        self.assertEqual(args.output.read_bytes(), receipt_bytes)

    def test_index_reader_ignores_dirty_worktree_helper(self):
        repository = (
            Path(self.temporary_directory.name)
            / "dirty-helper-repository"
        )
        helper = repository / "scripts" / "deploy-wordpress.py"
        helper.parent.mkdir(parents=True)
        git = robots.resolve_trusted_git_executable()
        environment = robots._trusted_git_environment(git)

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
        run_git("config", "user.name", "Robots Test")
        run_git("config", "user.email", "robots@example.invalid")
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

        payload, git_head = robots.read_head_index_file(
            repository,
            "scripts/deploy-wordpress.py",
            max_bytes=1024,
        )

        self.assertEqual(payload, reviewed)
        self.assertRegex(git_head, r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
