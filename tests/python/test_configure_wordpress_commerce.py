from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "configure-wordpress-commerce.py"
SPEC = importlib.util.spec_from_file_location(
    "configure_wordpress_commerce",
    SCRIPT,
)
assert SPEC is not None and SPEC.loader is not None
configure = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = configure
SPEC.loader.exec_module(configure)
RUN_COMMERCE_DOM_PROOF = configure.run_commerce_dom_proof


TOKEN = "commerce-1700000000-" + ("a1" * 16)
ROUTE_PATH = f"/wp-json/agentconfigure/v1/run-{TOKEN}"
BASE_URL = "https://robbottx.com"
AUTH = "Basic redacted"
VALID_OFFER_CHECKED_AT = datetime.now(timezone.utc).strftime(
    "%Y-%m-%dT%H:%M:%SZ"
)
BEFORE_TITLES = {
    "shop": False,
    "cart": True,
    "checkout": False,
    "my-account": True,
}
AFTER_TITLES = {
    "shop": True,
    "cart": True,
    "checkout": True,
    "my-account": True,
}
EXPECTED_PAGE_IDS = {
    "shop": 29,
    "cart": 30,
    "checkout": 31,
    "my-account": 32,
}
ORIGINAL_TITLE_VALUES = {
    "shop": "Legacy shop",
    "cart": "Cart",
    "checkout": "Legacy checkout",
    "my-account": "My account",
}
EXPECTED_TITLE_VALUES = {
    "shop": "Shop",
    "cart": "Cart",
    "checkout": "Checkout",
    "my-account": "My account",
}
CALLBACK_BODY = {
    "result": True,
    "store_live": True,
    "cache_flush_sent": True,
    "titles_verified": AFTER_TITLES,
    "state": {
        "coming_soon": "no",
        "store_pages_only": "yes",
        "page_ids": EXPECTED_PAGE_IDS,
    },
}
ROUTE_TEMPLATE = (
    ROOT
    / "scripts"
    / "templates"
    / "configure-commerce-route.php.txt"
).read_text(encoding="utf-8")


def commerce_dom_result(
    mode: str,
    *,
    route_ui: str,
    path: str,
    dom: dict,
    redirect_status=None,
    redirect_count: int = 0,
) -> dict:
    return {
        "schemaVersion": "1.0",
        "operational": True,
        "passed": True,
        "mode": mode,
        "source": "live",
        "routeUi": route_ui,
        "failureCodes": [],
        "navigation": {
            "status": 200,
            "redirectStatus": redirect_status,
            "finalOrigin": BASE_URL,
            "finalPath": path,
            "redirectCount": redirect_count,
        },
        "stylesheets": {
            "externalCount": 2,
            "loadedCount": 2,
            "failedCount": 0,
            "blockedCount": 0,
        },
        "dom": dom,
    }


class ConfigureWordPressCommerceTests(unittest.TestCase):
    def setUp(self):
        self.browser_proof_patcher = patch.object(
            configure,
            "run_commerce_dom_proof",
        )
        self.browser_proof = self.browser_proof_patcher.start()
        self.addCleanup(self.browser_proof_patcher.stop)

    @staticmethod
    def evidence(execute: bool) -> dict:
        return {
            "execute": execute,
            "recorded_at": "2026-07-24T00:00:00+00:00",
            "schema_version": 1,
            "status": "started",
        }

    def execution_patches(
        self,
        *,
        request_responses=None,
        before_options=None,
        after_options=None,
        before_page_ids=None,
        after_page_ids=None,
        before_title_values=None,
        after_title_values=None,
        cleanup_result=(True, []),
        route_proof=(True, []),
        namespace_proof=(True, []),
        public_error=None,
    ):
        if request_responses is None:
            request_responses = [
                (
                    201,
                    "application/json",
                    json.dumps({"id": 501}),
                ),
                (
                    200,
                    "application/json",
                    json.dumps(CALLBACK_BODY),
                ),
            ]
        if before_options is None:
            before_options = {
                "coming_soon": "yes",
                "store_pages_only": "yes",
            }
        if after_options is None:
            after_options = {
                "coming_soon": "no",
                "store_pages_only": "yes",
            }
        if before_page_ids is None:
            before_page_ids = EXPECTED_PAGE_IDS
        if after_page_ids is None:
            after_page_ids = EXPECTED_PAGE_IDS
        if before_title_values is None:
            before_title_values = ORIGINAL_TITLE_VALUES
        if after_title_values is None:
            after_title_values = EXPECTED_TITLE_VALUES

        stack = contextlib.ExitStack()
        stack.enter_context(
            patch.object(
                configure,
                "verify_commerce_release_boundary",
                return_value=ROUTE_TEMPLATE,
            )
        )
        stack.enter_context(
            patch.object(
                configure.ops,
                "required_env",
                side_effect=[BASE_URL, "release-admin", "not-recorded"],
            )
        )
        stack.enter_context(
            patch.object(
                configure.ops,
                "normalize_base_url",
                return_value=BASE_URL,
            )
        )
        stack.enter_context(
            patch.object(configure.ops, "make_auth", return_value=AUTH)
        )
        stack.enter_context(patch.object(configure, "verify_authority"))
        stack.enter_context(
            patch.object(
                configure,
                "verify_snippet_bound",
                return_value=7,
            )
        )
        stack.enter_context(
            patch.object(
                configure,
                "verify_pages",
                side_effect=[BEFORE_TITLES, AFTER_TITLES],
            )
        )
        stack.enter_context(
            patch.object(
                configure.ops,
                "make_route_token",
                return_value=TOKEN,
            )
        )
        stack.enter_context(
            patch.object(
                configure,
                "require_configuration_namespace_absent",
            )
        )
        stack.enter_context(
            patch.object(configure.ops, "require_snippet_name_absent")
        )
        stack.enter_context(
            patch.object(
                configure,
                "build_route_code",
                return_value="reviewed route code",
            )
        )
        stack.enter_context(
            patch.object(
                configure.ops,
                "request",
                side_effect=request_responses,
            )
        )
        stack.enter_context(
            patch.object(
                configure,
                "read_page_title_values",
                side_effect=[
                    before_title_values,
                    after_title_values,
                ],
            )
        )
        stack.enter_context(
            patch.object(
                configure,
                "read_commerce_state",
                side_effect=[
                    {
                        "woocommerce_options": before_options,
                        "woocommerce_page_ids": before_page_ids,
                    },
                    {
                        "woocommerce_options": after_options,
                        "woocommerce_page_ids": after_page_ids,
                    },
                ],
            )
        )
        if public_error is None:
            stack.enter_context(
                patch.object(configure, "verify_public_store")
            )
        else:
            stack.enter_context(
                patch.object(
                    configure,
                    "verify_public_store",
                    side_effect=public_error,
                )
            )
        stack.enter_context(
            patch.object(
                configure.ops,
                "cleanup_temporary_snippets",
                return_value=cleanup_result,
            )
        )
        stack.enter_context(
            patch.object(
                configure.ops,
                "prove_deploy_route_absent",
                return_value=route_proof,
            )
        )
        stack.enter_context(
            patch.object(
                configure,
                "prove_configuration_namespace_absent",
                return_value=namespace_proof,
            )
        )
        return stack

    def test_route_code_is_capability_gated_and_write_scoped(self):
        code = configure.build_route_code(TOKEN, ROUTE_TEMPLATE)

        self.assertIn(f"'/run-{TOKEN}'", code)
        self.assertEqual(
            code.count("'methods'             => 'GET'"),
            1,
        )
        self.assertEqual(
            code.count("'methods'             => 'POST'"),
            1,
        )
        self.assertIn("current_user_can( 'manage_options' )", code)
        self.assertIn("current_user_can( 'manage_woocommerce' )", code)
        self.assertIn("current_user_can( 'update_plugins' )", code)
        self.assertIn("current_user_can( 'edit_published_pages' )", code)
        self.assertIn("current_user_can( 'edit_post', $page_id )", code)
        self.assertIn("wc_get_page_id(", code)
        self.assertEqual(
            code.count("update_option("),
            1,
        )
        self.assertEqual(
            code.count("'woocommerce_coming_soon'"),
            6,
        )
        self.assertNotIn(
            "update_option( 'woocommerce_store_pages_only'",
            code,
        )
        self.assertEqual(code.count("wp_update_post("), 1)
        self.assertIn("$rollback = static function", code)
        self.assertEqual(code.count("$wpdb->query("), 3)
        self.assertIn(
            "$wpdb->query( 'START TRANSACTION' )",
            code,
        )
        self.assertIn("$wpdb->query( 'ROLLBACK' )", code)
        self.assertIn("$wpdb->query( 'COMMIT' )", code)
        self.assertIn("clean_post_cache( $page_id )", code)
        self.assertEqual(code.count("wp_cache_delete("), 3)
        self.assertIn(
            "robbottx_commerce_transaction_rolled_back",
            code,
        )
        self.assertIn("'page_ids'         => $page_ids", code)
        self.assertGreaterEqual(code.count("wc_get_page_id("), 3)
        self.assertIn("do_action( 'litespeed_purge_all' )", code)
        self.assertNotIn("{{", code)
        route_registration = code.index("register_rest_route")
        self.assertGreater(
            code.index("update_option", route_registration),
            route_registration,
        )
        self.assertGreater(
            code.index("update_option"),
            code.index("wp_update_post"),
        )

        php_probe = (
            "<?php\n"
            "$GLOBALS['writes'] = 0;\n"
            "$GLOBALS['registered'] = null;\n"
            "function add_action($hook, $callback) {"
            "$GLOBALS['registered'] = $callback; }\n"
            "function update_option(...$args) {"
            "$GLOBALS['writes'] += 1; }\n"
            "function wp_update_post(...$args) {"
            "$GLOBALS['writes'] += 1; }\n"
            + code
            + "\n"
            "if ($GLOBALS['writes'] !== 0"
            " || !is_callable($GLOBALS['registered'])) { exit(1); }\n"
        )
        completed = subprocess.run(
            ["php"],
            input=php_probe,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stderr or completed.stdout,
        )

    def test_index_module_loader_ignores_dirty_worktree_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory) / "repository"
            helper = repository / "scripts" / "helper.py"
            helper.parent.mkdir(parents=True)
            git = configure.resolve_trusted_git_executable()
            environment = configure._trusted_git_environment(git)

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
                    completed.stderr.decode(
                        "utf-8",
                        errors="replace",
                    ),
                )

            subprocess.run(
                [str(git), "init", str(repository)],
                capture_output=True,
                check=True,
                env=environment,
            )
            run_git("config", "user.name", "Commerce Test")
            run_git("config", "user.email", "commerce@example.invalid")
            run_git("config", "core.autocrlf", "false")
            helper.write_text(
                "ORIGIN = 'reviewed-index'\n",
                encoding="utf-8",
                newline="\n",
            )
            run_git("add", "--", "scripts/helper.py")
            run_git("commit", "--no-verify", "-m", "reviewed helper")
            helper.write_text(
                "raise RuntimeError('dirty helper executed')\n",
                encoding="utf-8",
                newline="\n",
            )

            module, git_head = configure.load_clean_index_module(
                repository,
                "scripts/helper.py",
                "_commerce_dirty_helper_negative_test",
                max_bytes=1024,
            )

            self.assertEqual(module.ORIGIN, "reviewed-index")
            self.assertRegex(git_head, r"^[0-9a-f]{40}$")

    def test_stale_or_fabricated_boundary_fails_before_credentials(self):
        class BoundaryFailure(RuntimeError):
            pass

        scan_report = SimpleNamespace(
            git_head=configure.OPS_GIT_HEAD,
            public_snapshot_payload_sha256="b" * 64,
        )
        args = SimpleNamespace(
            boundary_receipt=Path("untrusted-receipt.json"),
            execute=False,
            plugin_version="1.2.3",
            plugin_zip_sha256="a" * 64,
        )
        for message in (
            "receipt timestamp is outside the release window",
            "receipt body hash does not match",
        ):
            with self.subTest(message=message):
                verifier = SimpleNamespace(
                    DeployFailure=BoundaryFailure,
                    run_reviewed_boundary_scan=MagicMock(
                        return_value=scan_report
                    ),
                    validate_boundary_receipt=MagicMock(
                        side_effect=BoundaryFailure(message)
                    ),
                )
                evidence = self.evidence(False)
                with patch.object(
                    configure,
                    "read_clean_index_file",
                    return_value=(
                        ROUTE_TEMPLATE.encode("utf-8"),
                        configure.OPS_GIT_HEAD,
                    ),
                ), patch.object(
                    configure,
                    "load_clean_index_module",
                    return_value=(
                        verifier,
                        configure.OPS_GIT_HEAD,
                    ),
                ), patch.object(
                    configure.ops,
                    "required_env",
                ) as required_env:
                    with self.assertRaises(configure.ops.DeployFailure):
                        configure._run_configuration(args, evidence)

                self.assertEqual(
                    evidence["failure_stage"],
                    "public_boundary",
                )
                required_env.assert_not_called()

    def test_template_is_frozen_before_scan_and_never_reread(self):
        mutable_worktree = {"template": ROUTE_TEMPLATE}
        scan_report = SimpleNamespace(
            git_head=configure.OPS_GIT_HEAD,
            public_snapshot_payload_sha256="b" * 64,
        )

        def scan(_repository):
            mutable_worktree["template"] = (
                "<?php throw new RuntimeException('mutated');"
            )
            return scan_report

        validator = MagicMock(
            return_value={
                "artifact_path": (
                    "plugin-dist/robbottx-core-1.2.3.zip"
                ),
                "git_head": configure.OPS_GIT_HEAD,
                "receipt_body_sha256": "c" * 64,
            }
        )
        verifier = SimpleNamespace(
            DeployFailure=RuntimeError,
            run_reviewed_boundary_scan=scan,
            validate_boundary_receipt=validator,
        )
        args = SimpleNamespace(
            boundary_receipt=Path("reviewed-receipt.json"),
            plugin_version="1.2.3",
            plugin_zip_sha256="a" * 64,
        )
        with patch.object(
            configure,
            "read_clean_index_file",
            return_value=(
                ROUTE_TEMPLATE.encode("utf-8"),
                configure.OPS_GIT_HEAD,
            ),
        ), patch.object(
            configure,
            "load_clean_index_module",
            return_value=(verifier, configure.OPS_GIT_HEAD),
        ), patch.object(
            configure.Path,
            "read_text",
            side_effect=AssertionError("worktree template reread"),
        ):
            frozen_template = (
                configure.verify_commerce_release_boundary(args)
            )
            code = configure.build_route_code(TOKEN, frozen_template)

        self.assertNotEqual(
            frozen_template,
            mutable_worktree["template"],
        )
        self.assertIn(f"'/run-{TOKEN}'", code)
        validator.assert_called_once()
        self.assertEqual(
            validator.call_args.kwargs["version"],
            "1.2.3",
        )
        self.assertEqual(
            validator.call_args.kwargs["slug"],
            "robbottx-core",
        )
        self.assertEqual(
            validator.call_args.kwargs["zip_sha256"],
            "a" * 64,
        )

    def test_route_code_rejects_unbound_token_and_added_write(self):
        with self.assertRaises(configure.ops.DeployFailure):
            configure.build_route_code("commerce-unsafe", ROUTE_TEMPLATE)

        original = ROUTE_TEMPLATE
        option_anchor = (
            "                            update_option(\n"
            "                                'woocommerce_coming_soon',\n"
            "                                'no'\n"
            "                            );"
        )
        self.assertIn(option_anchor, original)
        expanded = original.replace(
            option_anchor,
            option_anchor
            + "\n"
            + "                            update_option(\n"
            + "                                'woocommerce_store_pages_only',\n"
            + "                                'no'\n"
            + "                            );",
            1,
        )
        with self.assertRaises(configure.ops.DeployFailure):
            configure.build_route_code(TOKEN, expanded)

        user_meta_write = original.replace(
            "do_action( 'litespeed_purge_all' );",
            "update_user_meta( 1, 'scope_escape', 'yes' );\n"
            "                    do_action( 'litespeed_purge_all' );",
        )
        with self.assertRaises(configure.ops.DeployFailure):
            configure.build_route_code(TOKEN, user_meta_write)

    def test_route_transaction_rolls_back_and_reports_hard_failures(self):
        code = configure.build_route_code(TOKEN, ROUTE_TEMPLATE)

        def run_probe(mode: str) -> subprocess.CompletedProcess:
            php_probe = (
                "<?php\n"
                f"$GLOBALS['mode'] = '{mode}';\n"
                "$GLOBALS['query_log'] = array();\n"
                "$GLOBALS['post_cache_clears'] = 0;\n"
                "$GLOBALS['option_cache_clears'] = 0;\n"
                "$GLOBALS['update_calls'] = 0;\n"
                "class WP_Post {"
                " public $ID; public $post_name; public $post_status;"
                " public $post_title; public $post_type;"
                " public function __construct($id,$slug,$title) {"
                "  $this->ID=$id; $this->post_name=$slug;"
                "  $this->post_status='publish';"
                "  $this->post_title=$title; $this->post_type='page';"
                " }}\n"
                "class WP_Error {"
                " public $code; public $message; public $data;"
                " public function __construct($code,$message='',$data=array()){"
                "  $this->code=$code; $this->message=$message;"
                "  $this->data=$data;"
                " }}\n"
                "$GLOBALS['pages'] = array("
                "29=>new WP_Post(29,'shop','Legacy shop'),"
                "30=>new WP_Post(30,'cart','Cart'),"
                "31=>new WP_Post(31,'checkout','Legacy checkout'),"
                "32=>new WP_Post(32,'my-account','My account'));"
                "$GLOBALS['options'] = array("
                "'woocommerce_coming_soon'=>'yes',"
                "'woocommerce_store_pages_only'=>'yes');\n"
                "class FakeWpdb {"
                " public $page_snapshot; public $option_snapshot;"
                " public function query($sql) {"
                "  $GLOBALS['query_log'][]=$sql;"
                "  if ('START TRANSACTION'===$sql) {"
                "   if ('start'===$GLOBALS['mode']) { return false; }"
                "   $this->page_snapshot=unserialize(serialize("
                "$GLOBALS['pages']));"
                "   $this->option_snapshot=$GLOBALS['options'];"
                "   return 0;"
                "  }"
                "  if ('ROLLBACK'===$sql) {"
                "   if ('rollback'===$GLOBALS['mode']) { return false; }"
                "   $GLOBALS['pages']=$this->page_snapshot;"
                "   $GLOBALS['options']=$this->option_snapshot;"
                "   return 0;"
                "  }"
                "  if ('COMMIT'===$sql) {"
                "   return 'commit'===$GLOBALS['mode'] ? false : 0;"
                "  }"
                "  return false;"
                " }}\n"
                "$GLOBALS['wpdb']=new FakeWpdb();\n"
                "function add_action($hook,$callback) {"
                " $GLOBALS['rest_init']=$callback; }\n"
                "function register_rest_route($namespace,$route,$args) {"
                " $GLOBALS['route_args']=$args; }\n"
                "function current_user_can(...$args) { return true; }\n"
                "function is_wp_error($value) {"
                " return $value instanceof WP_Error; }\n"
                "function wc_get_page_id($key) {"
                " return array('shop'=>29,'cart'=>30,'checkout'=>31,"
                "'myaccount'=>32)[$key]; }\n"
                "function get_post($id) {"
                " return $GLOBALS['pages'][$id] ?? null; }\n"
                "function get_permalink($id) {"
                " return 'https://robbottx.com/'"
                "  .$GLOBALS['pages'][$id]->post_name.'/'; }\n"
                "function home_url($path) {"
                " return 'https://robbottx.com'.$path; }\n"
                "function untrailingslashit($value) {"
                " return rtrim($value,'/'); }\n"
                "function get_option($key,$default=null) {"
                " return $GLOBALS['options'][$key] ?? $default; }\n"
                "function update_option($key,$value) {"
                " $GLOBALS['options'][$key]=$value; return true; }\n"
                "function wp_slash($value) { return $value; }\n"
                "function wp_update_post($value,$wp_error=false) {"
                " $GLOBALS['update_calls']++;"
                " if ('throw'===$GLOBALS['mode']"
                " && 2===$GLOBALS['update_calls']) {"
                "  throw new Error('forced throwable');"
                " }"
                " if (in_array($GLOBALS['mode'],array('write','rollback'),"
                "true) && 2===$GLOBALS['update_calls']) {"
                "  return new WP_Error('forced_write_failure');"
                " }"
                " $GLOBALS['pages'][$value['ID']]->post_title="
                "$value['post_title'];"
                " return $value['ID'];"
                " }\n"
                "function clean_post_cache($id) {"
                " $GLOBALS['post_cache_clears']++; }\n"
                "function wp_cache_delete($key,$group='') {"
                " $GLOBALS['option_cache_clears']++; return true; }\n"
                "function do_action(...$args) {}\n"
                "function wp_cache_flush() { return true; }\n"
                "define('WC_VERSION','10.0.0');\n"
                + code
                + "\n"
                "$GLOBALS['rest_init']();"
                "$result=$GLOBALS['route_args'][1]['callback']();"
                "$expected=array("
                "'write'=>'robbottx_commerce_transaction_rolled_back',"
                "'rollback'=>'robbottx_commerce_rollback_failed',"
                "'commit'=>'robbottx_commerce_transaction_rolled_back',"
                "'throw'=>'robbottx_commerce_transaction_rolled_back',"
                "'start'=>'robbottx_commerce_transaction_start_failed');"
                "if (!($result instanceof WP_Error)"
                " || $result->code!==$expected[$GLOBALS['mode']]) {"
                " fwrite(STDERR,'unexpected error result'); exit(20);"
                "}"
                "$original=("
                "'Legacy shop'===$GLOBALS['pages'][29]->post_title"
                " && 'Cart'===$GLOBALS['pages'][30]->post_title"
                " && 'Legacy checkout'===$GLOBALS['pages'][31]->post_title"
                " && 'My account'===$GLOBALS['pages'][32]->post_title"
                " && 'yes'===$GLOBALS['options']["
                "'woocommerce_coming_soon']);"
                "if ('rollback'===$GLOBALS['mode']) {"
                " if ($original) {"
                "  fwrite(STDERR,'failed rollback looked restored');"
                "  exit(21);"
                " }"
                "} elseif (!$original) {"
                " fwrite(STDERR,'transaction did not restore originals');"
                " exit(22);"
                "}"
                "if ('start'===$GLOBALS['mode']) {"
                " if (1!==count($GLOBALS['query_log'])"
                "  || 0!==$GLOBALS['update_calls']) {"
                "  fwrite(STDERR,'start failure mutated state'); exit(23);"
                " }"
                "} else {"
                " if ($GLOBALS['post_cache_clears']<4"
                "  || $GLOBALS['option_cache_clears']<3"
                "  || !in_array('ROLLBACK',$GLOBALS['query_log'],true)) {"
                "  fwrite(STDERR,'rollback cleanup not proven'); exit(24);"
                " }"
                "}"
            )
            return subprocess.run(
                ["php"],
                input=php_probe,
                text=True,
                capture_output=True,
                check=False,
            )

        for mode in ("write", "rollback", "commit", "throw", "start"):
            with self.subTest(mode=mode):
                completed = run_probe(mode)
                self.assertEqual(
                    completed.returncode,
                    0,
                    completed.stderr or completed.stdout,
                )

    def test_authority_requires_positive_identity_and_every_capability(self):
        capabilities = {
            "edit_pages": True,
            "edit_published_pages": True,
            "manage_options": True,
            "manage_woocommerce": True,
            "update_plugins": True,
        }
        good = {
            "id": 17,
            "roles": ["administrator"],
            "capabilities": capabilities,
        }
        with patch.object(
            configure.ops,
            "request",
            return_value=(
                200,
                "application/json",
                json.dumps(good),
            ),
        ) as request:
            configure.verify_authority(BASE_URL, AUTH)
        self.assertIn("_fields=id,roles,capabilities", request.call_args.args[0])

        bad_id = {**good, "id": 0}
        bad_capability = {
            **good,
            "capabilities": {**capabilities, "manage_woocommerce": False},
        }
        for record in (bad_id, bad_capability, {**good, "roles": ["editor"]}):
            with self.subTest(record=record):
                with patch.object(
                    configure.ops,
                    "request",
                    return_value=(
                        200,
                        "application/json",
                        json.dumps(record),
                    ),
                ):
                    with self.assertRaises(configure.ops.DeployFailure):
                        configure.verify_authority(BASE_URL, AUTH)

    def test_page_title_prefers_raw_edit_value(self):
        self.assertEqual(
            configure.page_title(
                {"title": {"raw": "Shop", "rendered": "Wrong"}}
            ),
            "Shop",
        )
        self.assertEqual(configure.page_title({"title": "Shop"}), "")

    def test_exact_page_identity_and_title_are_required(self):
        responses = []
        for page_id, (slug, title) in configure.EXPECTED_PAGES.items():
            responses.append(
                (
                    200,
                    "application/json",
                    json.dumps(
                        {
                            "id": page_id,
                            "slug": slug,
                            "status": "publish",
                            "title": {"raw": title},
                            "link": f"{BASE_URL}/{slug}/",
                        }
                    ),
                )
            )
        with patch.object(
            configure.ops,
            "request",
            side_effect=responses,
        ):
            result = configure.verify_pages(
                BASE_URL,
                AUTH,
                require_titles=True,
            )
        self.assertEqual(result, AFTER_TITLES)

        wrong = list(responses)
        wrong[0] = (
            200,
            "application/json",
            json.dumps(
                {
                    "id": 29,
                    "slug": "catalog",
                    "status": "publish",
                    "title": {"raw": "Shop"},
                    "link": f"{BASE_URL}/shop/",
                }
            ),
        )
        with patch.object(configure.ops, "request", side_effect=wrong):
            with self.assertRaises(configure.ops.DeployFailure):
                configure.verify_pages(
                    BASE_URL,
                    AUTH,
                    require_titles=True,
                )

    def test_browser_helper_and_dependency_are_exactly_release_pinned(self):
        reviewed_executable = Path(sys.executable).resolve()
        with (
            patch.object(
                configure.shutil,
                "which",
                return_value=str(reviewed_executable),
            ),
            patch.object(
                configure,
                "find_commerce_chrome",
                return_value=reviewed_executable,
            ),
        ):
            node_path, chrome_path, helper_path = (
                configure.verify_commerce_dom_dependencies()
            )
        self.assertEqual(node_path, reviewed_executable)
        self.assertEqual(chrome_path, reviewed_executable)
        self.assertEqual(
            helper_path,
            (
                ROOT / "tools" / "qa" / "verify-commerce-dom.mjs"
            ).resolve(),
        )
        self.assertEqual(
            configure.hashlib.sha256(helper_path.read_bytes()).hexdigest(),
            configure.COMMERCE_DOM_HELPER_SHA256,
        )
        self.assertRegex(
            configure.COMMERCE_DOM_HELPER_SHA256,
            r"\A[0-9a-f]{64}\Z",
        )

    def test_browser_proof_process_is_pinned_bounded_and_secret_free(self):
        result = commerce_dom_result(
            "shop",
            route_ui="product_catalog",
            path="/shop/",
            dom={"productCardCount": 1, "productLinkCount": 1},
        )
        process = SimpleNamespace(
            communicate=MagicMock(
                return_value=(json.dumps(result), None)
            ),
            kill=MagicMock(),
            pid=901,
            poll=MagicMock(return_value=0),
            returncode=0,
        )
        node_path = ROOT / "reviewed-node"
        chrome_path = ROOT / "reviewed-chrome"
        helper_path = ROOT / "tools" / "qa" / "verify-commerce-dom.mjs"
        profile_path = (
            ROOT
            / f"{configure.COMMERCE_DOM_PROFILE_PREFIX}reviewed"
        )
        with (
            patch.object(
                configure,
                "verify_commerce_dom_dependencies",
                return_value=(node_path, chrome_path, helper_path),
            ),
            patch.object(
                configure.subprocess,
                "Popen",
                return_value=process,
            ) as popen,
            patch.object(
                configure.tempfile,
                "mkdtemp",
                return_value=str(profile_path),
            ),
            patch.object(
                configure,
                "remove_owned_commerce_dom_profile",
                return_value=True,
            ) as remove_profile,
            patch.dict(
                configure.os.environ,
                {
                    "PATH": "reviewed-path",
                    "WP_APP_PASSWORD": "must-not-be-inherited",
                    "UNRELATED_TOKEN": "must-not-be-inherited",
                },
                clear=True,
            ),
        ):
            RUN_COMMERCE_DOM_PROOF(
                "shop",
                f"{BASE_URL}/shop/?rbtxcb=1700000000",
            )

        arguments = popen.call_args.args[0]
        options = popen.call_args.kwargs
        self.assertEqual(
            arguments,
            [
                str(node_path),
                str(helper_path),
                "--chrome",
                str(chrome_path),
                "--profile",
                str(profile_path),
            ],
        )
        self.assertFalse(options["shell"] if "shell" in options else False)
        self.assertEqual(
            json.loads(process.communicate.call_args.kwargs["input"]),
            {
                "expectedOrigin": BASE_URL,
                "expectedPath": "/shop/",
                "mode": "shop",
                "url": f"{BASE_URL}/shop/?rbtxcb=1700000000",
            },
        )
        self.assertNotIn("WP_APP_PASSWORD", options["env"])
        self.assertNotIn("UNRELATED_TOKEN", options["env"])
        self.assertEqual(options["env"]["PATH"], "reviewed-path")
        self.assertEqual(
            process.communicate.call_args.kwargs["timeout"],
            configure.COMMERCE_DOM_PROCESS_TIMEOUT_SECONDS,
        )
        remove_profile.assert_called_once_with(profile_path)

    def test_browser_proof_timeout_terminates_tree_and_removes_profile(self):
        process = SimpleNamespace(
            communicate=MagicMock(
                side_effect=[
                    subprocess.TimeoutExpired(
                        cmd="reviewed-node",
                        timeout=75,
                    ),
                    ("", None),
                ]
            ),
            kill=MagicMock(),
            pid=902,
            poll=MagicMock(return_value=None),
            returncode=None,
        )
        profile_path = (
            ROOT
            / f"{configure.COMMERCE_DOM_PROFILE_PREFIX}timeout"
        )
        with (
            patch.object(
                configure,
                "verify_commerce_dom_dependencies",
                return_value=(
                    ROOT / "reviewed-node",
                    ROOT / "reviewed-chrome",
                    ROOT / "tools" / "qa" / "verify-commerce-dom.mjs",
                ),
            ),
            patch.object(
                configure.subprocess,
                "Popen",
                return_value=process,
            ),
            patch.object(
                configure.tempfile,
                "mkdtemp",
                return_value=str(profile_path),
            ),
            patch.object(
                configure,
                "terminate_commerce_dom_process_tree",
            ) as terminate,
            patch.object(
                configure,
                "remove_owned_commerce_dom_profile",
                return_value=True,
            ) as remove_profile,
        ):
            with self.assertRaises(configure.ops.DeployFailure):
                RUN_COMMERCE_DOM_PROOF(
                    "shop",
                    f"{BASE_URL}/shop/?rbtxcb=1700000000",
                )
        terminate.assert_called_once_with(process)
        remove_profile.assert_called_once_with(profile_path)

    def test_browser_proof_result_schema_is_exact_and_route_specific(self):
        valid_results = (
            (
                "shop",
                "/shop/",
                commerce_dom_result(
                    "shop",
                    route_ui="product_catalog",
                    path="/shop/",
                    dom={"productCardCount": 2, "productLinkCount": 2},
                ),
            ),
            (
                "cart",
                "/cart/",
                commerce_dom_result(
                    "cart",
                    route_ui="reviewed_empty_state",
                    path="/cart/",
                    dom={
                        "cartFormCount": 0,
                        "dataInputCount": 0,
                        "submitCount": 0,
                    },
                ),
            ),
            (
                "account",
                "/my-account/",
                commerce_dom_result(
                    "account",
                    route_ui="login_form",
                    path="/my-account/",
                    dom={
                        "loginFormCount": 1,
                        "passwordCount": 1,
                        "submitCount": 1,
                        "usernameCount": 1,
                    },
                ),
            ),
            (
                "checkout",
                "/checkout/",
                commerce_dom_result(
                    "checkout",
                    route_ui="empty_cart_redirect",
                    path="/cart/",
                    redirect_status=302,
                    redirect_count=1,
                    dom={
                        "cartFormCount": 0,
                        "dataInputCount": 0,
                        "submitCount": 0,
                    },
                ),
            ),
            (
                "product",
                "/product/robot-component/",
                commerce_dom_result(
                    "product",
                    route_ui="product",
                    path="/product/robot-component/",
                    dom={
                        "actionFormCount": 1,
                        "addToCartCount": 1,
                        "identifierCount": 1,
                        "offerEvidenceCount": 1,
                        "positiveStockCount": 1,
                        "primaryActionCount": 1,
                        "primarySurfaceCount": 1,
                        "productCardCount": 1,
                        "stockCount": 1,
                        "submitCount": 1,
                        "titleCount": 1,
                        "validOfferEvidenceCount": 1,
                    },
                ),
            ),
        )
        for mode, path, result in valid_results:
            with self.subTest(mode=mode):
                configure.validate_commerce_dom_result(
                    result,
                    mode=mode,
                    expected_path=path,
                )

        invalid_results = []
        extra_key = json.loads(json.dumps(valid_results[0][2]))
        extra_key["rawHtml"] = "<secret>"
        invalid_results.append(extra_key)
        boolean_count = json.loads(json.dumps(valid_results[0][2]))
        boolean_count["dom"]["productCardCount"] = True
        invalid_results.append(boolean_count)
        stylesheet_failure = json.loads(json.dumps(valid_results[0][2]))
        stylesheet_failure["stylesheets"]["failedCount"] = 1
        invalid_results.append(stylesheet_failure)
        false_success = json.loads(json.dumps(valid_results[0][2]))
        false_success["failureCodes"] = ["shop_surface"]
        invalid_results.append(false_success)
        for result in invalid_results:
            with self.subTest(result=result):
                with self.assertRaises(configure.ops.DeployFailure):
                    configure.validate_commerce_dom_result(
                        result,
                        mode="shop",
                        expected_path="/shop/",
                    )

    def test_static_shop_cannot_pass_when_browser_proof_fails(self):
        shop = (
            200,
            "text/html; charset=UTF-8",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title>"
            '</head><body class="woocommerce-shop"><main><h1>Shop</h1>'
            '<ul class="products"><li class="product">'
            '<a class="woocommerce-LoopProduct-link" '
            'href="/product/robot-component/">Robot component</a>'
            "</li></ul></main></body></html>",
        )
        self.browser_proof.side_effect = configure.ops.DeployFailure(
            "generic browser rejection"
        )
        with (
            patch.object(configure.ops, "request", return_value=shop),
            patch.object(
                configure,
                "verify_public_product_page",
                return_value=(
                    "https://robbottx.com/product/robot-component/?rbtxcb=test",
                    42,
                ),
            ),
        ):
            with self.assertRaises(configure.ops.DeployFailure):
                configure.verify_public_store(BASE_URL)
        self.browser_proof.assert_called_once()
        self.assertEqual(self.browser_proof.call_args.args[0], "shop")

    def test_public_store_requires_real_shop_ui_and_reviewed_language(self):
        empty_shop = (
            200,
            "text/html; charset=UTF-8",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title>"
            "<style>#end-resizable-editor-section { "
            "display:none }</style>"
            '</head><body class="woocommerce-shop"><main><h1>Shop</h1>'
            '<p class="woocommerce-info">'
            "No products were found matching your selection."
            "</p></main>"
            '<div id="end-resizable-editor-section"></div>'
            "</body></html>",
        )
        product_shop = (
            200,
            "text/html; charset=utf-8",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title>"
            "<style>#end-resizable-editor-section { "
            "display:none }</style>"
            '</head><body class="woocommerce-shop"><main><h1>Shop</h1>'
            '<ul class="products"><li class="product">'
            '<a class="woocommerce-LoopProduct-link" '
            'href="/product/robot-component/">Robot component</a>'
            '<a class="add_to_cart_button" '
            'href="/shop/?add-to-cart=42">Add to cart</a>'
            "</li></ul></main>"
            '<div id="end-resizable-editor-section"></div>'
            "</body></html>",
        )
        product_page = (
            200,
            "text/html; charset=UTF-8",
            '<html lang="en-US"><head>'
            "<title>Robot component \u2013 RobbottX</title>"
            "<style>#end-resizable-editor-section { "
            "display:none }</style>"
            '</head><body class="single-product"><main>'
            '<div id="product-42" '
            'class="post-42 product type-product"><div class="summary">'
            '<h1 class="product_title">Robot component</h1>'
            '<p class="stock in-stock">In stock</p>'
            '<p class="rbtx-offer-evidence" data-supplier="ROBOTIS" '
            'data-region="IL" data-quantity-basis="1 unit" '
            f'data-checked-at="{VALID_OFFER_CHECKED_AT}" '
            'data-offer-hash="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
            'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa">'
            "Supplier ROBOTIS. Region IL. Quantity basis 1 unit. "
            f"Checked {VALID_OFFER_CHECKED_AT}.</p>"
            '<form class="cart" method="post" '
            'action="/product/robot-component/">'
            '<input type="hidden" name="product_id" value="42">'
            '<button type="submit" name="add-to-cart" value="42" '
            'class="single_add_to_cart_button">'
            "Add to cart"
            "</button></form></div></div></main>"
            '<div id="end-resizable-editor-section"></div>'
            "</body></html>",
        )
        with patch.object(
            configure.ops,
            "request",
            return_value=empty_shop,
        ):
            with self.assertRaises(configure.ops.DeployFailure):
                configure.verify_public_store(BASE_URL)
        self.browser_proof.assert_not_called()
        self.browser_proof.reset_mock()
        with patch.object(
            configure.ops,
            "request",
            side_effect=[product_shop, product_page],
        ):
            configure.verify_public_store(BASE_URL)
        self.assertEqual(
            [call.args[0] for call in self.browser_proof.call_args_list],
            ["shop", "cart", "account", "checkout", "product"],
        )
        product_call = self.browser_proof.call_args_list[-1]
        self.assertIn(
            "/product/robot-component/?rbtxcb=",
            product_call.args[1],
        )
        self.assertEqual(product_call.kwargs["product_id"], 42)
        self.browser_proof.reset_mock()

        invalid_bodies = (
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title></head>"
            '<body class="woocommerce-shop '
            'woocommerce-coming-soon-store-only"><main><h1>Shop</h1>'
            '<p class="woocommerce-info">'
            "No products were found matching your selection."
            "</p></main></body></html>",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title>"
            "<style>.woocommerce-info > span { display:none }</style>"
            '</head><body class="woocommerce-shop"><main><h1>Shop</h1>'
            '<p class="woocommerce-info"><span>'
            "No products were found matching your selection."
            "</span></p></main></body></html>",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title>"
            "<style>.woocommerce-info { display: none }</style></head>"
            '<body class="woocommerce-shop"><main><h1>Shop</h1>'
            '<p class="woocommerce-info">'
            "No products were found matching your selection."
            "</p></main></body></html>",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title>"
            "<style>#empty { display: none }</style></head>"
            '<body class="woocommerce-shop"><main><h1>Shop</h1>'
            '<p id="empty" class="woocommerce-info">'
            "No products were found matching your selection."
            "</p></main></body></html>",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title>"
            "<style>.woocommerce-info { opacity: 0%; }</style>"
            '</head><body class="woocommerce-shop"><main><h1>Shop</h1>'
            '<p class="woocommerce-info">'
            "No products were found matching your selection."
            "</p></main></body></html>",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title>"
            "<style>.woocommerce-info { opacity: -0; }</style>"
            '</head><body class="woocommerce-shop"><main><h1>Shop</h1>'
            '<p class="woocommerce-info">'
            "No products were found matching your selection."
            "</p></main></body></html>",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title>"
            "<style>.woocommerce-info { op/**/acity: +0.0%; }</style>"
            '</head><body class="woocommerce-shop"><main><h1>Shop</h1>'
            '<p class="woocommerce-info">'
            "No products were found matching your selection."
            "</p></main></body></html>",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title></head>"
            '<body class="woocommerce-shop"><main><h1>Shop</h1>'
            '<p style="display:/**/none" class="woocommerce-info">'
            "No products were found matching your selection."
            "</p></main></body></html>",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title>"
            '<style>[id="empty"] { display: none }</style></head>'
            '<body class="woocommerce-shop"><main><h1>Shop</h1>'
            '<p id="empty" class="woocommerce-info">'
            "No products were found matching your selection."
            "</p></main></body></html>",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title>"
            "<style>#shop-shell > p { display: none }</style></head>"
            '<body class="woocommerce-shop"><main><h1>Shop</h1>'
            '<div id="shop-shell"><p class="woocommerce-info">'
            "No products were found matching your selection."
            "</p></div></main></body></html>",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title>"
            "<style>[data-public-surface] { "
            "content-visibility: hidden }</style></head>"
            '<body class="woocommerce-shop"><main><h1>Shop</h1>'
            '<p data-public-surface class="woocommerce-info">'
            "No products were found matching your selection."
            "</p></main></body></html>",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title></head>"
            '<body class="woocommerce-shop"><main><h1>'
            "\u05d7\u05e0\u05d5\u05ea"
            "</h1></main></body></html>",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title></head>"
            '<body class="woocommerce-shop"><main><h1>Shop</h1>'
            "</main></body></html>",
            '<html lang="en-US"><body class="woocommerce-shop">'
            "<title>Shop \u2013 RobbottX</title><main><h1>Shop</h1>"
            '<p class="woocommerce-info">'
            "No products were found matching your selection."
            "</p></main></body></html>",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title></head>"
            '<body class="woocommerce-shop"><main><h1>Shop</h1>'
            '<ul class="products"><li class="product"></li></ul>'
            "</main></body></html>",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title></head>"
            '<body class="woocommerce-shop"><main><h1>Shop</h1>'
            '<ul class="products"><li class="product">'
            '<a class="woocommerce-LoopProduct-link" '
            'href="/product/valid/">Valid product</a></li>'
            '<li class="product">Unlinked product</li></ul>'
            "</main></body></html>",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title></head>"
            '<body class="woocommerce-shop"><main><h1>Shop</h1>'
            '<ul class="products"><li class="product">'
            "A product label without a usable product link"
            "</li></ul></main></body></html>",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title></head>"
            '<body class="woocommerce-shop"><main><h1>Shop</h1>'
            '</main><ul class="products"><li class="product">'
            "Outside the customer main area"
            "</li></ul></body></html>",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title></head>"
            '<body class="woocommerce-shop"><main><h1>Shop</h1>'
            '<p class="woocommerce-info">'
            "No products were found matching your selection."
            '</p><div class="wp-block-woocommerce-coming-soon"></div>'
            "</main></body></html>",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title></head>"
            '<body class="woocommerce-shop"><main><h1>Shop</h1>'
            '<div aria-hidden="true"><p class="woocommerce-info">'
            "No products were found matching your selection."
            "</p></div></main></body></html>",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title></head>"
            '<body class="woocommerce-shop"><main><h1>Shop</h1>'
            '<p hidden class="woocommerce-info">'
            "No products were found matching your selection."
            "</p></main></body></html>",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title></head>"
            '<body class="woocommerce-shop"><main><h1>Shop</h1>'
            '<p style="display: none" class="woocommerce-info">'
            "No products were found matching your selection."
            "</p></main></body></html>",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title></head>"
            '<body class="woocommerce-shop"><main><h1>Shop</h1>'
            '<template><p class="woocommerce-info">'
            "No products were found matching your selection."
            "</p></template></main></body></html>",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title></head>"
            '<body class="woocommerce-shop"><main><h1>Shop</h1>'
            '<dialog><p class="woocommerce-info">'
            "No products were found matching your selection."
            "</p></dialog></main></body></html>",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title></head>"
            '<body class="woocommerce-shop"><main><h1>Shop</h1>'
            '<details><p class="woocommerce-info">'
            "No products were found matching your selection."
            "</p></details></main></body></html>",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title>"
            "<style>.woocommerce-info { transform: scale(0) }</style>"
            '</head><body class="woocommerce-shop"><main><h1>Shop</h1>'
            '<p class="woocommerce-info">'
            "No products were found matching your selection."
            "</p></main></body></html>",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title></head>"
            '<body class="woocommerce-shop"><main><h1>Shop</h1>'
            '<p style="transform:scale(0)" class="woocommerce-info">'
            "No products were found matching your selection."
            "</p></main></body></html>",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title>"
            "<style>.woocommerce-info { position:absolute; "
            "width:1px; height:1px; overflow:hidden; "
            "clip:rect(0, 0, 0, 0) }</style></head>"
            '<body class="woocommerce-shop"><main><h1>Shop</h1>'
            '<p class="woocommerce-info">'
            "No products were found matching your selection."
            "</p></main></body></html>",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title>"
            "<style>#end-resizable-editor-section { "
            "display:none }</style></head>"
            '<body class="woocommerce-shop"><main><h1>Shop</h1>'
            '<p class="woocommerce-info">'
            "No products were found matching your selection."
            "</p></main></body></html>",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title></head><body><main>"
            '<div class="woocommerce-shop"><h1>Shop</h1>'
            '<p class="woocommerce-info">'
            "No products were found matching your selection."
            "</p></div></main></body></html>",
            '<html lang="he-IL"><head>'
            "<title>Shop \u2013 RobbottX</title></head>"
            '<body class="woocommerce-shop"><main><h1>Shop</h1>'
            '<p class="woocommerce-info">'
            "No products were found matching your selection."
            "</p></main></body></html>",
        )
        for body in invalid_bodies:
            with self.subTest(body=body):
                with patch.object(
                    configure.ops,
                    "request",
                    return_value=(
                        200,
                        "text/html; charset=UTF-8",
                        body,
                    ),
                ):
                    with self.assertRaises(configure.ops.DeployFailure):
                        configure.verify_public_store(BASE_URL)

        broken_product_page = (
            200,
            "text/html; charset=UTF-8",
            '<html lang="en-US"><head>'
            "<title>Page not found \u2013 RobbottX</title></head>"
            '<body class="single-product"><main>'
            '<h1 class="product_title">Page not found</h1>'
            "</main></body></html>",
        )
        stylesheet_hidden_product_page = (
            200,
            "text/html; charset=UTF-8",
            '<html lang="en-US"><head>'
            "<title>Robot component \u2013 RobbottX</title>"
            "<style>.product { display: none }</style></head>"
            '<body class="single-product"><main>'
            '<div class="product type-product"><div class="summary">'
            '<h1 class="product_title">Robot component</h1>'
            '<div class="stock">In stock</div>'
            "</div></div></main></body></html>",
        )
        disconnected_product_page = (
            200,
            "text/html; charset=UTF-8",
            '<html lang="en-US"><head>'
            "<title>Placeholder \u2013 RobbottX</title></head>"
            '<body class="single-product">'
            '<div class="product type-product"></div>'
            '<div class="summary"></div><main>'
            '<h1 class="product_title">Placeholder</h1>'
            '<div class="stock">Unavailable</div>'
            "</main></body></html>",
        )
        id_hidden_product_page = (
            200,
            "text/html; charset=UTF-8",
            '<html lang="en-US"><head>'
            "<title>Robot component \u2013 RobbottX</title>"
            "<style>#product-42 { display: none }</style></head>"
            '<body class="single-product"><main>'
            '<div id="product-42" class="product type-product">'
            '<div class="summary">'
            '<h1 class="product_title">Robot component</h1>'
            '<div class="stock">In stock</div>'
            "</div></div></main></body></html>",
        )
        attribute_hidden_product_page = (
            200,
            "text/html; charset=UTF-8",
            '<html lang="en-US"><head>'
            "<title>Robot component \u2013 RobbottX</title>"
            '<style>[id="product-42"] { display: none }</style>'
            '</head><body class="single-product"><main>'
            '<div id="product-42" class="product type-product">'
            '<div class="summary">'
            '<h1 class="product_title">Robot component</h1>'
            '<div class="stock">In stock</div>'
            "</div></div></main></body></html>",
        )
        zero_percent_product_page = (
            200,
            "text/html; charset=UTF-8",
            '<html lang="en-US"><head>'
            "<title>Robot component \u2013 RobbottX</title>"
            "<style>.product { opacity: 0%; }</style>"
            '</head><body class="single-product"><main>'
            '<div class="product type-product"><div class="summary">'
            '<h1 class="product_title">Robot component</h1>'
            '<div class="stock">In stock</div>'
            "</div></div></main></body></html>",
        )
        commented_inline_product_page = (
            200,
            "text/html; charset=UTF-8",
            '<html lang="en-US"><head>'
            "<title>Robot component \u2013 RobbottX</title>"
            '</head><body class="single-product"><main>'
            '<div style="display:/**/none" '
            'class="product type-product"><div class="summary">'
            '<h1 class="product_title">Robot component</h1>'
            '<div class="stock">In stock</div>'
            "</div></div></main></body></html>",
        )
        ancestor_hidden_product_page = (
            200,
            "text/html; charset=UTF-8",
            '<html lang="en-US"><head>'
            "<title>Robot component \u2013 RobbottX</title>"
            "<style>#product-shell > div { display: none }</style>"
            '</head><body class="single-product"><main>'
            '<section id="product-shell">'
            '<div class="product type-product"><div class="summary">'
            '<h1 class="product_title">Robot component</h1>'
            '<div class="stock">In stock</div>'
            "</div></div></section></main></body></html>",
        )
        for product_response in (
            (
                404,
                "text/html; charset=UTF-8",
                "<html><body>Not found</body></html>",
            ),
            broken_product_page,
            stylesheet_hidden_product_page,
            disconnected_product_page,
            id_hidden_product_page,
            attribute_hidden_product_page,
            ancestor_hidden_product_page,
            zero_percent_product_page,
            commented_inline_product_page,
        ):
            with self.subTest(product_response=product_response):
                with patch.object(
                    configure.ops,
                    "request",
                    side_effect=[product_shop, product_response],
                ):
                    with self.assertRaises(configure.ops.DeployFailure):
                        configure.verify_public_store(BASE_URL)

        valid_product_html = product_page[2]
        product_form = (
            '<form class="cart" method="post" '
            'action="/product/robot-component/">'
            '<input type="hidden" name="product_id" value="42">'
            '<button type="submit" name="add-to-cart" value="42" '
            'class="single_add_to_cart_button">'
            "Add to cart"
            "</button></form>"
        )
        empty_cart_form = valid_product_html.replace(
            product_form,
            '<form class="cart"></form>',
        )
        empty_stock = valid_product_html.replace(
            '<p class="stock in-stock">In stock</p>',
            '<p class="stock in-stock"></p>',
        )
        fake_submit_div = valid_product_html.replace(
            '<button type="submit" name="add-to-cart" value="42" '
            'class="single_add_to_cart_button">'
            "Add to cart"
            "</button>",
            '<div class="single_add_to_cart_button"></div>',
        )
        templated_stock = valid_product_html.replace(
            '<p class="stock in-stock">In stock</p>',
            '<template><p class="stock in-stock">In stock</p></template>',
        )
        disabled_submit = valid_product_html.replace(
            '<button type="submit"',
            '<button type="submit" disabled',
        )
        mismatched_product_id = valid_product_html.replace(
            'name="product_id" value="42"',
            'name="product_id" value="43"',
        ).replace(
            'name="add-to-cart" value="42"',
            'name="add-to-cart" value="43"',
        )
        disabled_fieldset_submit = valid_product_html.replace(
            '<input type="hidden" name="product_id" value="42">'
            '<button type="submit"',
            '<fieldset disabled>'
            '<input type="hidden" name="product_id" value="42">'
            '<button type="submit"',
        ).replace(
            "Add to cart"
            "</button></form>",
            "Add to cart"
            "</button></fieldset></form>",
        )
        span_identifier = valid_product_html.replace(
            '<input type="hidden" name="product_id" value="42">',
            '<span name="product_id" value="42"></span>',
        ).replace(
            ' name="add-to-cart" value="42"',
            "",
        )
        disabled_identifier = valid_product_html.replace(
            '<input type="hidden" name="product_id" value="42">',
            '<input disabled type="hidden" '
            'name="product_id" value="42">',
        ).replace(
            ' name="add-to-cart" value="42"',
            "",
        )
        reassigned_controls = valid_product_html.replace(
            '<form class="cart"',
            '<form id="decoy"></form><form class="cart"',
        ).replace(
            'name="product_id" value="42"',
            'form="decoy" name="product_id" value="42"',
        ).replace(
            'name="add-to-cart" value="42"',
            'form="decoy" name="add-to-cart" value="42"',
        )
        malformed_nested_form = valid_product_html.replace(
            '<input type="hidden" name="product_id" value="42">',
            '<form id="decoy">'
            '<input type="hidden" name="product_id" value="42">'
            "</form>",
        )
        duplicate_action_attribute = valid_product_html.replace(
            'action="/product/robot-component/"',
            'action="/decoy/" '
            'action="/product/robot-component/"',
        )
        duplicate_method_attribute = valid_product_html.replace(
            'method="post"',
            'method="get" method="post"',
        )
        for invalid_product_html in (
            empty_cart_form,
            empty_stock,
            fake_submit_div,
            templated_stock,
            disabled_submit,
            mismatched_product_id,
            disabled_fieldset_submit,
            span_identifier,
            disabled_identifier,
            reassigned_controls,
            malformed_nested_form,
            duplicate_action_attribute,
            duplicate_method_attribute,
        ):
            self.assertNotEqual(invalid_product_html, valid_product_html)
            with self.subTest(invalid_product_html=invalid_product_html):
                with patch.object(
                    configure.ops,
                    "request",
                    side_effect=[
                        product_shop,
                        (
                            200,
                            "text/html; charset=UTF-8",
                            invalid_product_html,
                        ),
                    ],
                ):
                    with self.assertRaises(configure.ops.DeployFailure):
                        configure.verify_public_store(BASE_URL)

        mutating_detail_link_shop = (
            200,
            "text/html; charset=UTF-8",
            '<html lang="en-US"><head>'
            "<title>Shop \u2013 RobbottX</title>"
            '</head><body class="woocommerce-shop"><main><h1>Shop</h1>'
            '<ul class="products"><li class="product">'
            '<a class="woocommerce-LoopProduct-link" '
            'href="/shop/?add-to-cart=42">Robot component</a>'
            "</li></ul></main></body></html>",
        )
        with patch.object(
            configure.ops,
            "request",
            return_value=mutating_detail_link_shop,
        ) as request:
            with self.assertRaises(configure.ops.DeployFailure):
                configure.verify_public_store(BASE_URL)
        request.assert_called_once()

    @patch.object(
        configure,
        "verify_public_product_page",
        return_value=(
            "https://robbottx.com/product/robot-component/?rbtxcb=test",
            42,
        ),
    )
    def test_public_store_fetches_and_reviews_same_origin_stylesheets(
        self,
        _product_page,
    ):
        def shop_with_link(href: str, *, target: bool = True) -> tuple:
            target_markup = (
                '<div id="end-resizable-editor-section"></div>'
                if target
                else ""
            )
            return (
                200,
                "text/html; charset=UTF-8",
                '<html lang="en-US"><head>'
                "<title>Shop \u2013 RobbottX</title>"
                f'<link rel="stylesheet" href="{href}">'
                '</head><body class="woocommerce-shop">'
                "<main><h1>Shop</h1>"
                '<ul class="products"><li class="product">'
                '<a class="woocommerce-LoopProduct-link" '
                'href="/product/robot-component/">Robot component</a>'
                "</li></ul></main>"
                f"{target_markup}</body></html>",
            )

        exact_live_rule = (
            200,
            "text/css; charset=utf-8",
            ".screen-reader-text { position:absolute; width:1px; "
            "height:1px; overflow:hidden; clip:rect(0,0,0,0) }"
            "#end-resizable-editor-section { display:none }",
        )
        with patch.object(
            configure.ops,
            "request",
            side_effect=[
                shop_with_link(
                    "https://robbottx.com/hide-shop.css"
                ),
                exact_live_rule,
            ],
        ) as request:
            configure.verify_public_store(BASE_URL)
        self.assertEqual(request.call_count, 2)

        hiding_stylesheets = (
            ".products { transform:scale(0) }",
            "@media (min-width:0px) {"
            "@supports (display:block) {"
            ".products { display:none }"
            "}}",
            ".products { position:absolute; width:1px; "
            "height:1px; overflow:hidden; clip:rect(0,0,0,0) }",
        )
        for stylesheet in hiding_stylesheets:
            with self.subTest(stylesheet=stylesheet):
                with patch.object(
                    configure.ops,
                    "request",
                    side_effect=[
                        shop_with_link("/hide-shop.css"),
                        (200, "text/css", stylesheet),
                    ],
                ):
                    with self.assertRaises(configure.ops.DeployFailure):
                        configure.verify_public_store(BASE_URL)

        imported_hide = '@import url("/nested/hide.css"); body{color:#000}'
        with patch.object(
            configure.ops,
            "request",
            side_effect=[
                shop_with_link("/assets/shop.css"),
                (200, "text/css", imported_hide),
                (
                    200,
                    "text/css; charset=UTF-8",
                    ".products{display:none}",
                ),
            ],
        ):
            with self.assertRaises(configure.ops.DeployFailure):
                configure.verify_public_store(BASE_URL)

        for response in (
            (302, "text/css", ".woocommerce-info{display:none}"),
            (200, "text/html", ".woocommerce-info{display:none}"),
            (200, "text/css", ".woocommerce-info{"),
        ):
            with self.subTest(response=response):
                with patch.object(
                    configure.ops,
                    "request",
                    side_effect=[
                        shop_with_link("/assets/shop.css"),
                        response,
                    ],
                ):
                    with self.assertRaises(configure.ops.DeployFailure):
                        configure.verify_public_store(BASE_URL)

        with patch.object(
            configure.ops,
            "request",
            side_effect=[
                shop_with_link("https://example.com/hide-shop.css"),
            ],
        ) as request:
            with self.assertRaises(configure.ops.DeployFailure):
                configure.verify_public_store(BASE_URL)
        request.assert_called_once()

        with patch.object(
            configure.ops,
            "request",
            side_effect=[
                shop_with_link("/assets/one.css"),
                (
                    200,
                    "text/css",
                    '@import "/assets/two.css"; body{color:#000}',
                ),
                (
                    200,
                    "text/css",
                    '@import "/assets/one.css"; body{color:#000}',
                ),
            ],
        ):
            with self.assertRaises(configure.ops.DeployFailure):
                configure.verify_public_store(BASE_URL)

    def test_css_syntax_and_visibility_regressions_are_token_safe(self):
        self.assertNotIn("matchProperty", configure.CSS_TREE_PARSER)
        self.assertNotIn("matchType", configure.CSS_TREE_PARSER)
        # Minimized syntax patterns attributed to WooCommerce 10.0.6.
        # These are regression fragments, not complete upstream fixtures.
        minimized_woocommerce_patterns = (
            ":root{--woocommerce:#720eec}"
            ".wc-regression{"
            "color:var(--button--color-text);"
            "margin:calc(var(--wp--style--block-gap)/ 4) 0;"
            "padding:env(safe-area-inset-bottom,0px)}"
        )
        parsed = configure.parse_css_stylesheet(
            minimized_woocommerce_patterns
        )
        self.assertFalse(parsed["ambiguous"])
        self.assertGreaterEqual(parsed["usable_declarations"], 4)

        for stylesheet in (
            "@keyframes pulse{from,to,50%{opacity:1}}",
            "@-webkit-keyframes pulse{0%,100%{opacity:1}}",
            '.asset{background:url("data:image/svg+xml;a;b");'
            'content:"display:none;"}',
        ):
            with self.subTest(stylesheet=stylesheet):
                self.assertFalse(
                    configure.parse_css_stylesheet(stylesheet)[
                        "ambiguous"
                    ]
                )

        for stylesheet in (
            "body{color:red",
            "body{color:red}<html>",
            "body{color:red;???}",
            "@keyframes pulse{banana{opacity:1}}",
            "@keyframes pulse{101%{opacity:1}}",
            "@keyframes pulse{-1%{opacity:1}}",
            "@-webkit-keyframes pulse{banana{opacity:1}}",
            "@-webkit-keyframes pulse{100.01%{opacity:1}}",
            "html.canvas-mode-edit-transition"
            "::view-transition-group(toggle){animation-delay:255ms}",
            ".ui-helper-zfix{filter:Alpha(Opacity=0)}",
            "[data-rich-text-comment]{span{filter:none}}",
        ):
            with self.subTest(stylesheet=stylesheet):
                with self.assertRaises(configure.ops.DeployFailure):
                    configure.parse_css_stylesheet(stylesheet)

        for declarations in (
            "display:revert",
            "scale:100%",
            'content:"display:none;";'
            'background:url("data:image/svg+xml;display:none");'
            "display:block",
            'content:"!important;display:none";display:block',
            r"content:escaped\;semicolon;display:block",
            "--wc-layout:{gap:1rem;mode:grid};display:block",
        ):
            with self.subTest(declarations=declarations):
                self.assertFalse(
                    configure.css_declarations_hide(declarations)
                )

        for declarations in (
            "display:none}",
            "display:none!important",
            "filter:opacity(0)",
            "-webkit-filter:opacity(0%)",
            "position:absolute;inset-inline-start:-9999px",
            "position:fixed;margin-inline-end:-100rem",
            "overflow:hidden;height:0",
            "overflow:clip;max-height:0px",
            "transform:scale(0)",
            "scale:0%",
        ):
            with self.subTest(declarations=declarations):
                self.assertTrue(
                    configure.css_declarations_hide(declarations)
                )

    def test_configuration_namespace_inventory_fails_closed_on_regex_route(
        self,
    ):
        with patch.object(
            configure.ops,
            "request",
            return_value=(
                200,
                "application/json",
                json.dumps({"routes": {}}),
            ),
        ):
            self.assertEqual(
                configure.prove_configuration_namespace_absent(
                    BASE_URL
                ),
                (True, []),
            )

        for regex_route in (
            "/agentconfigure/v1/(?P<action>run)",
            "/agentconfigure/(?P<version>v1)/run-"
            "(?P<token>[a-z0-9-]+)",
            "/agentconfigure/(?:v1)/run",
        ):
            with self.subTest(regex_route=regex_route):
                with patch.object(
                    configure.ops,
                    "request",
                    return_value=(
                        200,
                        "application/json",
                        json.dumps(
                            {
                                "routes": {
                                    regex_route: {
                                        "methods": ["POST"]
                                    }
                                }
                            }
                        ),
                    ),
                ):
                    absent, failures = (
                        configure.prove_configuration_namespace_absent(
                            BASE_URL
                        )
                    )
                self.assertFalse(absent)
                self.assertTrue(failures)

        with patch.object(
            configure,
            "prove_configuration_namespace_absent",
            return_value=(False, ["registered"]),
        ):
            with self.assertRaises(configure.ops.DeployFailure):
                configure.require_configuration_namespace_absent(
                    BASE_URL,
                    "preflight",
                )

    def test_snippet_capacity_uses_the_shared_ninety_eight_record_gate(self):
        with patch.object(
            configure,
            "require_snippet_capacity",
            return_value=98,
        ) as capacity:
            self.assertEqual(
                configure.verify_snippet_bound(BASE_URL, AUTH),
                98,
            )
        capacity.assert_called_once_with(BASE_URL, AUTH)

    def test_commerce_state_requires_live_options_and_exact_page_mappings(
        self,
    ):
        valid = {
            "coming_soon": "no",
            "store_pages_only": "yes",
            "page_ids": EXPECTED_PAGE_IDS,
        }
        with patch.object(
            configure.ops,
            "request",
            return_value=(
                200,
                "application/json",
                json.dumps(valid),
            ),
        ):
            state = configure.verify_commerce_state(
                BASE_URL,
                AUTH,
                ROUTE_PATH,
            )
        self.assertEqual(
            state,
            {
                "woocommerce_options": {
                    "coming_soon": "no",
                    "store_pages_only": "yes",
                },
                "woocommerce_page_ids": EXPECTED_PAGE_IDS,
            },
        )

        for invalid in (
            {**valid, "coming_soon": "yes"},
            {**valid, "store_pages_only": ""},
            {**valid, "coming_soon": False},
            {
                **valid,
                "page_ids": {**EXPECTED_PAGE_IDS, "checkout": 99},
            },
            {
                **valid,
                "page_ids": {**EXPECTED_PAGE_IDS, "shop": True},
            },
        ):
            with self.subTest(invalid=invalid):
                with patch.object(
                    configure.ops,
                    "request",
                    return_value=(
                        200,
                        "application/json",
                        json.dumps(invalid),
                    ),
                ):
                    with self.assertRaises(configure.ops.DeployFailure):
                        configure.verify_commerce_state(
                            BASE_URL,
                            AUTH,
                            ROUTE_PATH,
                        )

    def test_preflight_is_read_only_and_records_capacity_and_identities(self):
        args = SimpleNamespace(execute=False)
        evidence = self.evidence(False)
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    configure,
                    "verify_commerce_release_boundary",
                    return_value=ROUTE_TEMPLATE,
                )
            )
            stack.enter_context(
                patch.object(
                    configure.ops,
                    "required_env",
                    side_effect=[BASE_URL, "release-admin", "not-recorded"],
                )
            )
            stack.enter_context(
                patch.object(
                    configure.ops,
                    "normalize_base_url",
                    return_value=BASE_URL,
                )
            )
            stack.enter_context(
                patch.object(configure.ops, "make_auth", return_value=AUTH)
            )
            stack.enter_context(patch.object(configure, "verify_authority"))
            stack.enter_context(
                patch.object(
                    configure,
                    "verify_snippet_bound",
                    return_value=98,
                )
            )
            stack.enter_context(
                patch.object(
                    configure,
                    "verify_pages",
                    return_value=BEFORE_TITLES,
                )
            )
            stack.enter_context(
                patch.object(
                    configure,
                    "read_page_title_values",
                    return_value=ORIGINAL_TITLE_VALUES,
                )
            )
            stack.enter_context(
                patch.object(
                    configure.ops,
                    "make_route_token",
                    return_value=TOKEN,
                )
            )
            namespace = stack.enter_context(
                patch.object(
                    configure,
                    "require_configuration_namespace_absent",
                )
            )
            name = stack.enter_context(
                patch.object(
                    configure.ops,
                    "require_snippet_name_absent",
                )
            )
            route_builder = stack.enter_context(
                patch.object(configure, "build_route_code")
            )
            request = stack.enter_context(
                patch.object(configure.ops, "request")
            )

            configure._run_configuration(args, evidence)

        self.assertEqual(evidence["status"], "preflight_ok")
        self.assertEqual(evidence["snippet_count_before"], 98)
        self.assertTrue(evidence["page_identities_verified"])
        self.assertEqual(
            evidence["before"]["woocommerce_options"],
            {"coming_soon": None, "store_pages_only": None},
        )
        self.assertEqual(
            evidence["before"]["woocommerce_page_ids"],
            {
                "cart": None,
                "checkout": None,
                "my-account": None,
                "shop": None,
            },
        )
        self.assertEqual(
            evidence["cleanup"],
            {
                "attempted": False,
                "fixed_route_absent": True,
                "proven": True,
                "required": False,
                "route_absent": True,
                "snippet_absent": True,
            },
        )
        namespace.assert_called_once()
        name.assert_called_once()
        route_builder.assert_not_called()
        request.assert_not_called()

    def test_execute_success_records_pre_post_scope_and_cleanup(self):
        args = SimpleNamespace(execute=True)
        evidence = self.evidence(True)

        with self.execution_patches():
            configure._run_configuration(args, evidence)

        self.assertEqual(evidence["status"], "configured")
        self.assertEqual(
            evidence["before"]["woocommerce_options"],
            {"coming_soon": "yes", "store_pages_only": "yes"},
        )
        self.assertEqual(
            evidence["after"]["woocommerce_options"],
            {"coming_soon": "no", "store_pages_only": "yes"},
        )
        self.assertEqual(
            evidence["before"]["woocommerce_page_ids"],
            EXPECTED_PAGE_IDS,
        )
        self.assertEqual(
            evidence["after"]["woocommerce_page_ids"],
            EXPECTED_PAGE_IDS,
        )
        self.assertTrue(evidence["after"]["page_mappings_unchanged"])
        self.assertTrue(evidence["after"]["store_pages_only_unchanged"])
        self.assertTrue(evidence["after"]["public_store_verified"])
        self.assertEqual(evidence["after"]["titles"], AFTER_TITLES)
        self.assertTrue(evidence["callback_confirmed"])
        configure.require_allowlisted_evidence(
            evidence,
            configure.COMMERCE_EVIDENCE_SCHEMA,
        )
        json.dumps(evidence)
        self.assertEqual(
            evidence["cleanup"],
            {
                "attempted": True,
                "fixed_route_absent": True,
                "proven": True,
                "required": True,
                "route_absent": True,
                "snippet_absent": True,
            },
        )

    def test_action_boundary_recheck_blocks_snippet_creation(self):
        args = SimpleNamespace(execute=True)
        evidence = self.evidence(True)
        with self.execution_patches(), patch.object(
            configure,
            "verify_commerce_release_boundary",
            side_effect=[
                ROUTE_TEMPLATE,
                configure.ops.DeployFailure("current scan changed"),
            ],
        ), patch.object(configure.ops, "request") as request:
            with self.assertRaises(configure.ops.DeployFailure):
                configure._run_configuration(args, evidence)

        self.assertEqual(evidence["failure_stage"], "action_boundary")
        request.assert_not_called()
        self.assertTrue(evidence["cleanup"]["proven"])

    def test_callback_ambiguity_uses_independent_state_as_truth(self):
        args = SimpleNamespace(execute=True)
        evidence = self.evidence(True)
        ambiguous = [
            (
                201,
                "application/json",
                json.dumps({"id": 501}),
            ),
            (502, "text/html", "<html>proxy response</html>"),
        ]

        with self.execution_patches(request_responses=ambiguous):
            configure._run_configuration(args, evidence)

        self.assertEqual(evidence["status"], "configured")
        self.assertFalse(evidence["callback_confirmed"])
        self.assertEqual(
            evidence["after"]["woocommerce_options"]["coming_soon"],
            "no",
        )
        self.assertTrue(evidence["cleanup"]["proven"])

    def test_callback_failure_requires_independent_exact_rollback_proof(self):
        args = SimpleNamespace(execute=True)
        evidence = self.evidence(True)
        original_options = {
            "coming_soon": "yes",
            "store_pages_only": "yes",
        }
        responses = [
            (
                201,
                "application/json",
                json.dumps({"id": 501}),
            ),
            (
                500,
                "application/json",
                json.dumps(
                    {
                        "code": (
                            "robbottx_commerce_transaction_rolled_back"
                        )
                    }
                ),
            ),
        ]

        with self.execution_patches(
            request_responses=responses,
            before_options=original_options,
            after_options=original_options,
            before_title_values=ORIGINAL_TITLE_VALUES,
            after_title_values=ORIGINAL_TITLE_VALUES,
        ):
            with self.assertRaises(configure.ops.DeployFailure):
                configure._run_configuration(args, evidence)

        self.assertEqual(evidence["failure_stage"], "rollback_verified")
        self.assertEqual(
            evidence["after"]["woocommerce_options"],
            original_options,
        )
        self.assertEqual(
            evidence["after"]["woocommerce_page_ids"],
            EXPECTED_PAGE_IDS,
        )
        self.assertFalse(evidence["after"]["titles"]["shop"])
        self.assertFalse(evidence["after"]["titles"]["checkout"])
        self.assertTrue(evidence["cleanup"]["proven"])

    def test_page_mapping_change_fails_closed_and_cleanup_still_runs(self):
        args = SimpleNamespace(execute=True)
        evidence = self.evidence(True)

        with self.execution_patches(
            after_page_ids={**EXPECTED_PAGE_IDS, "checkout": 99},
        ):
            with self.assertRaises(configure.ops.DeployFailure):
                configure._run_configuration(args, evidence)

        self.assertFalse(evidence["after"]["page_mappings_unchanged"])
        self.assertEqual(
            evidence["after"]["woocommerce_page_ids"]["checkout"],
            99,
        )
        self.assertTrue(evidence["cleanup"]["proven"])

    def test_callback_confirmation_rejects_truthy_non_boolean_fields(self):
        args = SimpleNamespace(execute=True)
        evidence = self.evidence(True)
        numeric_callback = {
            **CALLBACK_BODY,
            "titles_verified": {
                key: 1
                for key in AFTER_TITLES
            },
        }
        responses = [
            (
                201,
                "application/json",
                json.dumps({"id": 501}),
            ),
            (
                200,
                "application/json",
                json.dumps(numeric_callback),
            ),
        ]

        with self.execution_patches(request_responses=responses):
            configure._run_configuration(args, evidence)

        self.assertEqual(evidence["status"], "configured")
        self.assertFalse(evidence["callback_confirmed"])

    def test_callback_confirmation_rejects_duplicate_json_keys(self):
        args = SimpleNamespace(execute=True)
        evidence = self.evidence(True)
        callback = json.dumps(
            CALLBACK_BODY,
            separators=(",", ":"),
        )
        duplicate = callback.replace(
            '"result":true',
            '"result":true,"result":true',
            1,
        )
        responses = [
            (
                201,
                "application/json",
                json.dumps({"id": 501}),
            ),
            (200, "application/json", duplicate),
        ]

        with self.execution_patches(request_responses=responses):
            configure._run_configuration(args, evidence)

        self.assertEqual(evidence["status"], "configured")
        self.assertFalse(evidence["callback_confirmed"])
        self.assertTrue(evidence["after"]["public_store_verified"])
        self.assertTrue(evidence["cleanup"]["proven"])

    def test_store_pages_only_change_fails_and_is_recorded(self):
        args = SimpleNamespace(execute=True)
        evidence = self.evidence(True)

        with self.execution_patches(
            after_options={
                "coming_soon": "no",
                "store_pages_only": "no",
            }
        ):
            with self.assertRaises(configure.ops.DeployFailure):
                configure._run_configuration(args, evidence)

        self.assertFalse(evidence["after"]["store_pages_only_unchanged"])
        self.assertEqual(
            evidence["before"]["woocommerce_options"]["store_pages_only"],
            "yes",
        )
        self.assertEqual(
            evidence["after"]["woocommerce_options"]["store_pages_only"],
            "no",
        )
        self.assertTrue(evidence["cleanup"]["proven"])

    def test_cleanup_runs_after_verification_failure_and_can_fail_closed(self):
        args = SimpleNamespace(execute=True)
        evidence = self.evidence(True)
        public_failure = configure.ops.DeployFailure(
            "Public Shop verification failed."
        )

        with self.execution_patches(
            public_error=public_failure,
            cleanup_result=(False, ["snippet cleanup unavailable"]),
            route_proof=(False, ["route proof unavailable"]),
            namespace_proof=(False, ["namespace inventory unavailable"]),
        ):
            with self.assertRaises(configure.ops.DeployFailure):
                configure._run_configuration(args, evidence)

        self.assertEqual(evidence["failure_stage"], "after_state")
        self.assertFalse(evidence["after"]["public_store_verified"])
        self.assertEqual(
            evidence["cleanup"],
            {
                "attempted": True,
                "fixed_route_absent": False,
                "proven": False,
                "required": True,
                "route_absent": False,
                "snippet_absent": False,
            },
        )

    def test_ambiguous_creation_always_delegates_name_based_cleanup(self):
        args = SimpleNamespace(execute=True)
        evidence = self.evidence(True)
        transport_failure = configure.ops.DeployFailure(
            "A WordPress transport request failed."
        )

        with self.execution_patches(
            request_responses=[transport_failure],
        ):
            with patch.object(
                configure.ops,
                "cleanup_temporary_snippets",
                return_value=(True, []),
            ) as cleanup:
                with self.assertRaises(configure.ops.DeployFailure):
                    configure._run_configuration(args, evidence)

        cleanup.assert_called_once()
        self.assertIsNone(cleanup.call_args.args[3])
        self.assertTrue(evidence["cleanup"]["proven"])

    def test_shared_cleanup_recovers_ambiguous_creation_by_unique_name(self):
        snippet_name = f"tmp-robbottx-commerce-configure-{TOKEN}"
        with patch.object(
            configure.ops,
            "find_snippet_ids_by_name",
            side_effect=[([777], []), ([], [])],
        ) as find, patch.object(
            configure.ops,
            "delete_and_prove_snippet",
            return_value=(True, []),
        ) as delete:
            absent, failures = configure.ops.cleanup_temporary_snippets(
                BASE_URL,
                AUTH,
                snippet_name,
                None,
            )

        self.assertTrue(absent)
        self.assertEqual(failures, [])
        self.assertEqual(find.call_count, 2)
        delete.assert_called_once_with(BASE_URL, 777, AUTH)

    def test_main_writes_atomic_allowlisted_success_receipt_and_refuses_reuse(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "commerce-success.json"
            args = SimpleNamespace(execute=False, output=output)

            def preflight(_args, evidence):
                evidence["status"] = "preflight_ok"
                evidence["cleanup"] = {
                    "attempted": False,
                    "fixed_route_absent": True,
                    "proven": True,
                    "required": False,
                    "route_absent": True,
                    "snippet_absent": True,
                }

            captured = io.StringIO()
            with patch.object(
                configure,
                "parse_args",
                return_value=args,
            ), patch.object(
                configure,
                "_run_configuration",
                side_effect=preflight,
            ), contextlib.redirect_stdout(captured):
                self.assertEqual(configure.main(), 0)

            receipt_bytes = output.read_bytes()
            receipt = json.loads(receipt_bytes)
            self.assertEqual(receipt["status"], "preflight_ok")
            self.assertNotIn("not-recorded", captured.getvalue())

            with patch.object(
                configure,
                "parse_args",
                return_value=args,
            ):
                with self.assertRaises(configure.ops.DeployFailure):
                    configure.main()
            self.assertEqual(output.read_bytes(), receipt_bytes)

    def test_main_writes_generic_failure_receipt_without_raw_response(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "commerce-failure.json"
            args = SimpleNamespace(execute=True, output=output)

            def fail(_args, evidence):
                evidence["failure_stage"] = "runtime_authority"
                raise configure.ops.DeployFailure(
                    "Authenticated WordPress user lacks commerce authority."
                )

            with patch.object(
                configure,
                "parse_args",
                return_value=args,
            ), patch.object(
                configure,
                "_run_configuration",
                side_effect=fail,
            ), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(configure.ops.DeployFailure):
                    configure.main()

            receipt = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "failed")
            self.assertEqual(receipt["failure_stage"], "runtime_authority")
            self.assertEqual(
                receipt["failure_type"],
                "DeployFailure",
            )
            self.assertEqual(receipt["cleanup"]["required"], False)
            serialized = json.dumps(receipt)
            self.assertNotIn("response", serialized.lower())
            self.assertNotIn("password", serialized.lower())

    def test_allowlist_rejects_secret_or_response_fields(self):
        for field in ("password", "raw_response", "route_token"):
            with self.subTest(field=field):
                with self.assertRaises(configure.ops.DeployFailure):
                    configure.require_allowlisted_evidence(
                        {
                            "status": "failed",
                            field: "must-not-persist",
                        },
                        configure.COMMERCE_EVIDENCE_SCHEMA,
                    )


if __name__ == "__main__":
    unittest.main()
