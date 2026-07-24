from __future__ import annotations

import base64
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "verify-live-release.py"
SPEC = importlib.util.spec_from_file_location("verify_live_release", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
verify = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verify
SPEC.loader.exec_module(verify)

VALID_OFFER_HASH = "a" * 64


def offer_evidence_html(checked_at: datetime) -> str:
    checked_at_text = checked_at.astimezone(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return (
        '<p class="rbtx-offer-evidence" '
        'data-supplier="ROBOTIS" data-region="IL" '
        'data-quantity-basis="1 unit" '
        f'data-checked-at="{checked_at_text}" '
        f'data-offer-hash="{VALID_OFFER_HASH}">'
        "Supplier ROBOTIS. Region IL. Quantity basis 1 unit. "
        f"Checked {checked_at_text}.</p>"
    )


def current_offer_evidence_html() -> str:
    return offer_evidence_html(
        datetime.now(timezone.utc).replace(microsecond=0)
    )


class VerifyLiveReleaseTests(unittest.TestCase):
    @staticmethod
    def http_result(
        status,
        body=b"",
        *,
        content_type="application/json",
        final_url="https://robbottx.com/",
        headers=None,
    ):
        if isinstance(body, str):
            body = body.encode("utf-8")
        normalized_headers = {}
        header_values = {}
        for name, value in (headers or {}).items():
            lowered = name.lower()
            values = value if isinstance(value, list) else [value]
            header_values[lowered] = list(values)
            normalized_headers[lowered] = values[-1]
        if "content-type" not in header_values:
            header_values["content-type"] = [content_type]
            normalized_headers["content-type"] = content_type
        return verify.HttpResult(
            status=status,
            content_type=content_type,
            headers=normalized_headers,
            body=body,
            final_url=final_url,
            header_seconds=0.01,
            total_seconds=0.02,
            header_values=header_values,
        )

    def test_html_facts_capture_release_evidence(self):
        html = """
        <!doctype html>
        <html lang="en-US">
          <head>
            <title>RobbottX - Robotics systems mapped to evidence</title>
            <meta charset="UTF-8">
            <meta name="description" content="Description">
            <meta property="og:type" content="website">
            <link rel="canonical" href="https://robbottx.com/">
            <link rel="icon" href="/favicon.svg">
            <script type="application/ld+json">
              {"@context":"https://schema.org","@graph":[
                {"@type":"WebSite"},{"@type":"WebPage"}
              ]}
            </script>
          </head>
          <body>
            <a href="#main-content">Skip</a>
            <main id="main-content">
              <h1>Robotics, mapped to evidence.</h1>
              <article class="rbtx-compatibility-card">Condition</article>
            </main>
            <!-- robbottx-core:0.1.5 -->
          </body>
        </html>
        """
        facts = verify.parse_html(html)

        self.assertEqual(facts.html_language, "en-US")
        self.assertEqual(facts.h1_count, 1)
        self.assertEqual(facts.main_count, 1)
        self.assertIn("main-content", facts.element_ids)
        self.assertIn("#main-content", facts.body_hrefs)
        self.assertEqual(facts.class_counts["rbtx-compatibility-card"], 1)
        self.assertEqual(facts.meta_values("description"), ["Description"])
        self.assertEqual(
            verify.json_ld_types(facts),
            {"WebSite", "WebPage"},
        )
        self.assertIn("robbottx-core:0.1.5", facts.body_comments)

    def test_head_facts_ignore_body_decoys(self):
        facts = verify.parse_html(
            """
            <html>
              <head>
                <meta name="description" content="Canonical">
                <link rel="canonical" href="https://robbottx.com/">
              </head>
              <body>
                <meta name="description" content="Body decoy">
                <link rel="canonical" href="https://example.com/">
              </body>
            </html>
            """
        )

        self.assertEqual(
            facts.meta_values("description"),
            ["Canonical"],
        )
        self.assertEqual(
            [link["href"] for link in facts.links],
            ["https://robbottx.com/"],
        )

    def test_html_structure_rejects_misnesting_void_closers_and_trailing_text(
        self,
    ):
        invalid_documents = (
            (
                "<html><head><body></body></head></html>",
                "body nested in head",
            ),
            (
                "<html><head></head><body><img></img></body></html>",
                "void closing tag",
            ),
            (
                "<html><head></head><body></body></html>trailing",
                "trailing visible text",
            ),
            (
                "<html><head></head><body><div></body></div></html>",
                "misnested element",
            ),
            (
                "Warning: inherited output"
                "<html><head></head><body></body></html>",
                "leading visible output",
            ),
            (
                "<html><head>"
                '<meta http-equiv="refresh" content="0;url=/other/">'
                "</head><body></body></html>",
                "client-side redirect",
            ),
            (
                "<html><head></head><body>"
                '<meta http-equiv="refresh" content="0;url=/other/">'
                "</body></html>",
                "body client-side redirect",
            ),
        )
        for html, label in invalid_documents:
            with self.subTest(label=label):
                self.assertFalse(
                    verify.valid_html_document(verify.parse_html(html))
                )

        body_schema = verify.parse_html(
            "<html><head></head><body>"
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@graph":[]}'
            "</script></body></html>"
        )
        self.assertEqual(verify.json_ld_documents(body_schema), ([], []))

    def test_media_and_repeated_headers_fail_closed(self):
        duplicate = self.http_result(
            200,
            "{}",
            headers={
                "content-type": [
                    "application/json",
                    "text/html",
                ]
            },
        )
        with self.assertRaises(ValueError):
            duplicate.text()
        with self.assertRaises(ValueError):
            duplicate.single_header("content-type")

        wrong_media = self.http_result(
            200,
            "{}",
            content_type="application/json-seq; charset=UTF-8",
        )
        with self.assertRaises(ValueError):
            verify.validate_content_type(
                wrong_media,
                allowed_media_types={"application/json"},
                allowed_charsets={None, "utf-8"},
            )

    def test_configured_icon_payload_must_match_a_real_image_format(self):
        self.assertFalse(
            verify.valid_image_payload(
                self.http_result(
                    200,
                    b"",
                    content_type="image/png",
                ),
                "image/png",
            )
        )
        self.assertFalse(
            verify.valid_image_payload(
                self.http_result(
                    200,
                    (
                        b"\x89PNG\r\n\x1a\n"
                        b"\x00\x00\x00\rIHDR"
                        b"\x00\x00\x00\x01\x00\x00\x00\x01"
                        b"\x08\x06\x00\x00\x00"
                    ),
                    content_type="image/png",
                ),
                "image/png",
            )
        )
        self.assertFalse(
            verify.valid_image_payload(
                self.http_result(
                    200,
                    b"\xff\xd8\xff\xe0\x00\x02\xff\xd9",
                    content_type="image/jpeg",
                ),
                "image/jpeg",
            )
        )
        self.assertTrue(
            verify.valid_image_payload(
                self.http_result(
                    200,
                    base64.b64decode(
                        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAf"
                        "FcSJAAAADUlEQVR4nGNgYGBgAAAABQABpfZFQAAA"
                        "AABJRU5ErkJggg=="
                    ),
                    content_type="image/png",
                ),
                "image/png",
            )
        )
        self.assertFalse(
            verify.valid_image_payload(
                self.http_result(
                    200,
                    b"not-a-png",
                    content_type="image/png",
                ),
                "image/png",
            )
        )
        self.assertTrue(
            verify.valid_image_payload(
                self.http_result(
                    200,
                    "<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>",
                    content_type="image/svg+xml; charset=UTF-8",
                ),
                "image/svg+xml",
            )
        )
        self.assertFalse(
            verify.valid_image_payload(
                self.http_result(
                    200,
                    "<svg>",
                    content_type="image/svg+xml; charset=UTF-8",
                ),
                "image/svg+xml",
            )
        )

        wrong_charset = self.http_result(
            200,
            "{}",
            content_type="application/json; charset=ISO-8859-1",
        )
        with self.assertRaises(ValueError):
            wrong_charset.text()

    def test_static_asset_payloads_require_valid_syntax(self):
        self.assertTrue(
            verify.valid_css_payload("body{display:block;color:#111}")
        )
        self.assertTrue(
            verify.valid_css_payload(
                ":root{--wc-primary:#96588a}"
                "body{color:var(--wc-primary)}"
            )
        )
        self.assertTrue(
            verify.valid_css_payload(".woocommerce{display:block}")
        )
        representative_woocommerce_10_0_6_css = (
            "/* WooCommerce 10.0.6 representative syntax fixture. */"
            "#respond input#submit,.woocommerce #reviews h2 small,"
            "#brands_a_z h3:target{"
            "--wc-form-color-background:#fff;"
            "background:var(--wc-form-color-background,#fff);"
            "border-width:var(--wc-form-border-width,1px);"
            "padding:env(safe-area-inset-bottom,0px)}"
            '#\u54c1\u724c[data-label="\u673a\u5668\u4eba\U0001f916"]{display:block}'
        )
        self.assertTrue(
            verify.valid_css_payload(
                representative_woocommerce_10_0_6_css
            )
        )
        for upstream_woocommerce_css in (
            ".ui-helper-zfix{filter:Alpha(Opacity=0)}",
            (
                "html.canvas-mode-edit-transition"
                "::view-transition-group(toggle){"
                "animation-delay:255ms}"
            ),
            (
                "::view-transition-group(*),"
                "::view-transition-old(*),"
                "::view-transition-new(*){animation:none!important}"
            ),
            (
                "[data-rich-text-comment]{background-color:#3858e9;"
                "span{color:#fff;filter:none;padding:0 2px}}"
            ),
        ):
            with self.subTest(css=upstream_woocommerce_css):
                self.assertTrue(
                    verify.valid_css_payload(upstream_woocommerce_css)
                )
        self.assertTrue(
            verify.valid_css_payload(
                ".forbidden-action{display:block}"
            )
        )
        self.assertTrue(
            verify.valid_css_payload(
                "@keyframes x{0%{opacity:0}to{opacity:1}}"
            )
        )
        self.assertTrue(
            verify.valid_css_payload(
                "@keyframes x{0%,100%{opacity:1}}"
            )
        )
        for invalid in (
            "x",
            "Access denied",
            "<html><body>Blocked</body></html>",
            "<h1>Access denied</h1>{:}",
            "???{color:red}",
            ".valid{color:red} trailing ???",
            ".valid{color:red;broken ???}",
            ".valid{filter:Alpha(Opacity=101)}",
            ".valid{color:red;span{broken ???}}",
            "body{display:???}",
            "@keyframes x{banana{color:red}}",
            "@keyframes x{200%{color:red}}",
            "body{display:block",
            "body{font-family:sans-serif}/* Access denied */",
            "body{font-family:sans-serif}/* 403 Forbidden */",
            "body{font-family:sans-serif}/* 403 */",
            '.notice::before{content:"403 Forbidden"}',
            '.notice::after{content:"Access denied"}',
        ):
            with self.subTest(css=invalid):
                self.assertFalse(verify.valid_css_payload(invalid))

        for valid in (
            "const value = 1;",
            "window.wc=window.wc||{};",
            "/* Woo bootstrap */window.wc=window.wc||{};",
            "const message='Access denied'; window.wcMessage=message;",
            (
                "const response={status:403};"
                "if(response.status===403){window.wcRetry=true;}"
            ),
            (
                "function renderError(message){"
                "document.body.textContent=message;}"
            ),
            (
                "const renderError=(message)=>{"
                "document.body.textContent=message;};"
            ),
        ):
            with self.subTest(javascript=valid):
                self.assertTrue(verify.valid_javascript_payload(valid))

        for invalid in (
            "const value = ;",
            "import value from './dep.js';",
            "export default 1;",
            "return;",
            "return 1;",
            "/* Access denied */",
            "/* license only */",
            '"Access denied";',
            "Forbidden",
            "403",
            "Access-denied",
            "Access_Denied",
            "AccessDenied",
            '({status:403,message:"Forbidden"});',
            "({status_code:403});",
            "({statusCode:403});",
            'document.body.innerHTML="<h1>Access denied</h1>";',
            (
                'const message="403 Forbidden";'
                "document.body.textContent=message;"
            ),
            (
                "const body=document.body;"
                'body.textContent="403";'
            ),
            (
                '(()=>{document.body.innerHTML="Forbidden"})();'
            ),
            'document["write"]("401 Unauthorized");',
            (
                "document.body.appendChild("
                'document.createTextNode("403 Forbidden"));'
            ),
            (
                "document.documentElement.replaceChildren("
                'new Text("Access denied"));'
            ),
            (
                "Object.assign(document.body,"
                '{textContent:"401 Unauthorized"});'
            ),
            'document.body.textContent=atob("NDAzIEZvcmJpZGRlbg==");',
            (
                "function deny(){"
                'document.body.textContent="403 Forbidden";}deny();'
            ),
            (
                "const deny=()=>{"
                'document.body.textContent="403 Forbidden";};deny();'
            ),
            (
                "setTimeout(()=>{"
                'document.body.textContent="403 Forbidden";},0);'
            ),
            (
                "queueMicrotask(()=>{"
                'document.body.textContent="403 Forbidden";});'
            ),
            (
                "Promise.resolve().then(()=>{"
                'document.body.textContent="403 Forbidden";});'
            ),
            (
                'const root=document.getElementById("app");'
                'root.textContent="403 Forbidden";'
            ),
            (
                'document.querySelector("main").innerHTML='
                '"403 Forbidden";'
            ),
            (
                'const node=document.createElement("div");'
                'node.textContent="403 Forbidden";'
                "document.body.replaceChildren(node);"
            ),
            (
                'eval("document.body.textContent='
                '\\"403 Forbidden\\"");'
            ),
            (
                'setTimeout("document.body.textContent='
                '\\"403 Forbidden\\"",0);'
            ),
            (
                'new Function("document.body.textContent='
                '\\"403 Forbidden\\"")();'
            ),
            (
                "document.body.textContent="
                "['403','Forbidden'].join(' ');"
            ),
            (
                "document.body.textContent="
                "decodeURIComponent('403%20Forbidden');"
            ),
            (
                "const {body}=document;"
                "body.textContent=String.fromCharCode("
                "52,48,51,32,70,111,114,98,105,100,100,101,110);"
            ),
            (
                "document.body.textContent="
                "'403'.concat(' Forbidden');"
            ),
            (
                "Object.defineProperty(document.body,'textContent',"
                "{value:'403 Forbidden'});"
            ),
            (
                '(0,eval)("document.body.textContent='
                "\\'403 Forbidden\\'\");"
            ),
            (
                "document.body.textContent=['403','Forbidden']"
                ".reduce((a,b)=>a+' '+b);"
            ),
            (
                "document.addEventListener('DOMContentLoaded',()=>"
                "document.querySelector('form.cart').remove());"
            ),
            (
                "document.querySelector("
                "'button[name=add-to-cart]').disabled=true;"
            ),
            (
                "document.querySelector('form.cart')"
                ".addEventListener('submit',event=>"
                "event.preventDefault());"
            ),
        ):
            with self.subTest(javascript=invalid):
                self.assertFalse(verify.valid_javascript_payload(invalid))

        self.assertTrue(
            verify.valid_javascript_payload(
                "import value from './dep.js'; export default value;",
                module=True,
            )
        )
        self.assertTrue(
            verify.valid_javascript_payload(
                "export const wc = {};",
                module=True,
            )
        )
        for invalid in (
            'export default "Access denied";',
            "export default 403;",
            "/* 403 Forbidden */",
        ):
            with self.subTest(module_javascript=invalid):
                self.assertFalse(
                    verify.valid_javascript_payload(invalid, module=True)
                )

    def test_commerce_asset_uses_declared_script_execution_mode(self):
        classic = verify.parse_html(
            "<html><head><script src=\"/wp-content/plugins/"
            "woocommerce/assets/store.js\"></script></head>"
            "<body></body></html>"
        )
        module = verify.parse_html(
            "<html><head><script type=\"module\" src=\"/wp-content/plugins/"
            "woocommerce/assets/store.js\"></script></head>"
            "<body></body></html>"
        )

        def fake_fetch(url, **kwargs):
            return self.http_result(
                200,
                "export default 1;",
                content_type="application/javascript; charset=UTF-8",
                final_url=url,
            )

        with patch.object(verify, "fetch", side_effect=fake_fetch):
            classic_passed, classic_results = (
                verify.verify_commerce_assets(classic)
            )
            module_passed, module_results = (
                verify.verify_commerce_assets(module)
            )

        self.assertFalse(classic_passed)
        self.assertEqual(classic_results[0]["script_mode"], "classic")
        self.assertTrue(module_passed)
        self.assertEqual(module_results[0]["script_mode"], "module")

    def test_active_content_gate_covers_legacy_script_types_and_handlers(self):
        legacy_types = (
            "application/ecmascript",
            "application/javascript",
            "application/x-ecmascript",
            "application/x-javascript",
            "text/ecmascript",
            "text/javascript",
            "text/javascript1.0",
            "text/javascript1.1",
            "text/javascript1.2",
            "text/javascript1.3",
            "text/javascript1.4",
            "text/javascript1.5",
            "text/jscript",
            "text/livescript",
            "text/x-ecmascript",
            "text/x-javascript",
        )
        for script_type in legacy_types:
            with self.subTest(script_type=script_type):
                facts = verify.parse_html(
                    "<html><head><script type=\""
                    + script_type
                    + '\">document.body.textContent="403 Forbidden";'
                    "</script></head><body></body></html>"
                )
                passed, results = verify.verify_executable_scripts(facts)
                self.assertFalse(passed)
                self.assertTrue(
                    any(
                        result.get("kind") == "inline_script"
                        and result.get("loaded") is False
                        for result in results
                    )
                )

        handler_facts = verify.parse_html(
            '<html><head></head><body><img src="/missing" '
            'onerror="document.body.textContent=\'403 Forbidden\'">'
            "</body></html>"
        )
        handler_passed, handler_results = (
            verify.verify_executable_scripts(handler_facts)
        )
        self.assertFalse(handler_passed)
        self.assertIn(
            "inline_event_handlers",
            {result.get("kind") for result in handler_results},
        )

        inline_style_facts = verify.parse_html(
            "<html><head><style>"
            'body::before{content:"403 Forbidden";position:fixed;inset:0}'
            "</style></head><body></body></html>"
        )
        style_passed, style_results = verify.verify_executable_scripts(
            inline_style_facts
        )
        self.assertFalse(style_passed)
        self.assertTrue(
            any(
                result.get("kind") == "inline_stylesheet"
                and result.get("loaded") is False
                for result in style_results
            )
        )

        external_facts = verify.parse_html(
            '<html><head><script src="https://evil.example/deny.js">'
            "</script></head><body></body></html>"
        )
        external_passed, external_results = (
            verify.verify_executable_scripts(external_facts)
        )
        self.assertFalse(external_passed)
        self.assertIn(
            "external_script",
            {result.get("kind") for result in external_results},
        )

    def test_inline_visibility_normalizes_comments_and_percentages(self):
        for hidden_style in (
            "display:/**/none",
            "opacity:0%",
            "transform:scale(0%)",
            "clip-path:inset(50% 50% 50% 50%)",
        ):
            with self.subTest(hidden_style=hidden_style):
                self.assertTrue(
                    verify.inline_style_hides_content(
                        verify.inline_style_declarations(hidden_style)
                    )
                )
        for visible_style in (
            "display:block",
            "opacity:0.1%",
            "transform:scale(0.1%)",
            "clip-path:inset(49%)",
        ):
            with self.subTest(visible_style=visible_style):
                self.assertFalse(
                    verify.inline_style_hides_content(
                        verify.inline_style_declarations(visible_style)
                    )
                )
        hidden_by_stylesheet = verify.parse_html(
            "<html><head><style>"
            ".probe{display:none}"
            "</style></head><body><main>"
            '<div class="probe">Hidden control</div>'
            "</main></body></html>"
        )
        conditional_style = verify.parse_html(
            "<html><head><style>"
            "@media (max-width:1px){.probe{display:none}}"
            "</style></head><body><main>"
            '<div class="probe">Visible control</div>'
            "</main></body></html>"
        )
        self.assertEqual(hidden_by_stylesheet.class_counts["probe"], 0)
        self.assertEqual(conditional_style.class_counts["probe"], 1)

    def test_commerce_assets_reject_denial_bodies_with_valid_syntax(self):
        facts = verify.parse_html(
            "<html><head>"
            "<link rel=\"stylesheet\" href=\"/wp-content/plugins/"
            "woocommerce/assets/store.css\">"
            "<script src=\"/wp-content/plugins/woocommerce/assets/"
            "store.js\"></script>"
            "</head><body></body></html>"
        )

        def denial_fetch(url, **kwargs):
            if url.endswith(".css"):
                return self.http_result(
                    200,
                    "body{font-family:sans-serif}/* Access denied */",
                    content_type="text/css; charset=UTF-8",
                    final_url=url,
                )
            return self.http_result(
                200,
                "/* 403 Forbidden */",
                content_type="application/javascript; charset=UTF-8",
                final_url=url,
            )

        with patch.object(verify, "fetch", side_effect=denial_fetch):
            passed, results = verify.verify_commerce_assets(facts)

        self.assertFalse(passed)
        self.assertEqual(
            {result["kind"] for result in results},
            {"same_origin_script", "script", "stylesheet"},
        )
        self.assertTrue(
            all(result["syntax_valid"] is False for result in results)
        )

    def test_canonical_url_validation_rejects_transport_variants(self):
        self.assertEqual(
            verify.validate_canonical_url(
                "https://robbottx.com/path/?x=1"
            ).path,
            "/path/",
        )
        for url in (
            "http://robbottx.com/",
            "https://example.com/",
            "https://user@robbottx.com/",
            "https://robbottx.com:443/",
            "https://robbottx.com/#fragment",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    verify.validate_canonical_url(url)

    def test_body_markup_excludes_head_and_trailing_markup(self):
        html = (
            "<html><head><!-- robbottx-core:0.1.5 --></head>"
            "<body><main>live</main><!-- robbottx-core:0.1.4 --></body>"
            "<!-- robbottx-core:0.1.3 --></html>"
        )
        body = verify.body_markup(html)

        self.assertIn("robbottx-core:0.1.4", body)
        self.assertNotIn("robbottx-core:0.1.5", body)
        self.assertNotIn("robbottx-core:0.1.3", body)

    def test_xml_locations_support_indexes_and_urlsets(self):
        index_name, index_locations = verify.parse_xml_locations(
            """
            <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <sitemap><loc>https://robbottx.com/one.xml</loc></sitemap>
            </sitemapindex>
            """
        )
        urlset_name, urlset_locations = verify.parse_xml_locations(
            """
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <url><loc>https://robbottx.com/</loc></url>
            </urlset>
            """
        )

        self.assertEqual(index_name, "sitemapindex")
        self.assertEqual(
            index_locations,
            ["https://robbottx.com/one.xml"],
        )
        self.assertEqual(urlset_name, "urlset")
        self.assertEqual(urlset_locations, ["https://robbottx.com/"])

        invalid_documents = (
            "<urlset><url><loc>https://robbottx.com/</loc></url></urlset>",
            (
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                "<url><wrapper><loc>https://robbottx.com/</loc></wrapper>"
                "</url></urlset>"
            ),
            (
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                "<url><loc>https://robbottx.com/</loc>"
                "<loc>https://robbottx.com/two/</loc></url></urlset>"
            ),
        )
        for invalid in invalid_documents:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    verify.parse_xml_locations(invalid)

    def test_robots_policy_parses_exact_root_rule_and_sitemap(self):
        allowed = verify.parse_robots_policy(
            """
            User-agent: *
            Disallow: /private/
            Sitemap: https://robbottx.com/wp-sitemap.xml
            """
        )
        blocked = verify.parse_robots_policy(
            """
            User-agent: Googlebot
            Disallow: /private/
            User-agent: *
            Disallow : /
            """
        )
        public_path_blocked = verify.parse_robots_policy(
            """
            User-agent: *
            Allow: /
            Disallow: /shop/
            """
        )

        self.assertFalse(allowed["blocks_root"])
        self.assertEqual(
            allowed["sitemaps"],
            ["https://robbottx.com/wp-sitemap.xml"],
        )
        self.assertTrue(blocked["blocks_root"])
        self.assertFalse(public_path_blocked["blocks_root"])
        self.assertEqual(
            public_path_blocked["blocked_public_paths"],
            ["/shop/"],
        )
        self.assertFalse(
            public_path_blocked["public_path_access"]["googlebot"][
                "/shop/"
            ]
        )

    def test_home_schema_requires_the_exact_valid_graph(self):
        def facts_for_graph(graph):
            return verify.parse_html(
                "<html><head>"
                '<script type="application/ld+json">'
                + json.dumps(
                    {
                        "@context": "https://schema.org",
                        "@graph": graph,
                    }
                )
                + "</script></head><body></body></html>"
            )

        website = {
            "@type": "WebSite",
            "@id": "https://robbottx.com/#website",
            "url": "https://robbottx.com/",
            "name": "RobbottX",
            "description": verify.HOME_DESCRIPTION,
            "inLanguage": "en-US",
        }
        webpage = {
            "@type": "WebPage",
            "@id": "https://robbottx.com/#webpage",
            "url": "https://robbottx.com/",
            "name": verify.HOME_SOCIAL_TITLE,
            "description": verify.HOME_DESCRIPTION,
            "inLanguage": "en-US",
            "isPartOf": {"@id": "https://robbottx.com/#website"},
        }
        self.assertEqual(
            verify.validate_home_schema(facts_for_graph([website, webpage])),
            [],
        )

        invalid_graphs = []
        wrong_url = json.loads(json.dumps([website, webpage]))
        wrong_url[1]["url"] = "https://example.com/"
        invalid_graphs.append(wrong_url)
        wrong_description = json.loads(json.dumps([website, webpage]))
        wrong_description[0]["description"] = "Wrong"
        invalid_graphs.append(wrong_description)
        duplicate_page = json.loads(json.dumps([website, webpage, webpage]))
        invalid_graphs.append(duplicate_page)
        missing_relationship = json.loads(json.dumps([website, webpage]))
        del missing_relationship[1]["isPartOf"]
        invalid_graphs.append(missing_relationship)

        for graph in invalid_graphs:
            with self.subTest(graph=graph):
                self.assertNotEqual(
                    verify.validate_home_schema(facts_for_graph(graph)),
                    [],
                )

        wrong_context = verify.parse_html(
            "<html><head>"
            '<script type="application/ld+json">'
            + json.dumps(
                {
                    "@context": "https://evil.example/schema",
                    "@graph": [website, webpage],
                }
            )
            + "</script></head><body></body></html>"
        )
        self.assertIn(
            "document_context",
            verify.validate_home_schema(wrong_context),
        )
        offer_graph = facts_for_graph(
            [website, webpage, {"@type": "Offer", "price": "1"}]
        )
        self.assertNotEqual(
            verify.validate_home_schema(offer_graph),
            [],
        )

    def test_sitemap_depth_overflow_is_a_failure(self):
        with self.assertRaises(ValueError):
            verify.verify_sitemap_document(
                "https://robbottx.com/deep.xml",
                depth=3,
                visited=set(),
                sitemap_urls=[],
                content_urls=[],
            )

    def test_broken_active_optional_sitemap_fails_release_check(self):
        sitemap_urlset = (
            '<?xml version="1.0"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://robbottx.com/</loc></url>"
            "</urlset>"
        )

        def fake_fetch(url, **kwargs):
            path = verify.urllib.parse.urlsplit(url).path
            if path == "/wp-sitemap.xml":
                return self.http_result(
                    200,
                    sitemap_urlset,
                    content_type="application/xml",
                    final_url="https://robbottx.com/wp-sitemap.xml",
                )
            if path == "/sitemap_index.xml":
                return self.http_result(
                    200,
                    "<not-xml",
                    content_type="application/xml",
                    final_url="https://robbottx.com/sitemap_index.xml",
                )
            return self.http_result(
                404,
                '{"code":"rest_no_route"}',
                final_url="https://robbottx.com/sitemap.xml",
            )

        report = verify.Report(
            plugin_version="0.1.5",
            previous_plugin_version="0.1.4",
            theme_version="0.1.4",
            record_hash="a" * 64,
            expect_fallback_favicon=True,
        )
        with patch.object(verify, "fetch", side_effect=fake_fetch):
            verify.verify_sitemaps(report)

        self.assertEqual(report.checks[-1].check_id, "discovery.sitemaps")
        self.assertEqual(report.checks[-1].status, "fail")

    def test_unhealthy_optional_sitemap_status_fails_release_check(self):
        sitemap_urlset = (
            '<?xml version="1.0"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://robbottx.com/</loc></url>"
            "</urlset>"
        )

        for optional_status in (302, 500):
            with self.subTest(optional_status=optional_status):
                def fake_fetch(url, **kwargs):
                    path = verify.urllib.parse.urlsplit(url).path
                    if path == "/wp-sitemap.xml":
                        return self.http_result(
                            200,
                            sitemap_urlset,
                            content_type="application/xml",
                            final_url=(
                                "https://robbottx.com/wp-sitemap.xml"
                            ),
                        )
                    if path == "/sitemap_index.xml":
                        return self.http_result(
                            optional_status,
                            final_url=(
                                "https://robbottx.com/sitemap_index.xml"
                            ),
                        )
                    return self.http_result(
                        404,
                        final_url="https://robbottx.com/sitemap.xml",
                    )

                report = verify.Report(
                    plugin_version="0.1.5",
                    previous_plugin_version="0.1.4",
                    theme_version="0.1.4",
                    record_hash="a" * 64,
                    expect_fallback_favicon=True,
                )
                with patch.object(
                    verify,
                    "fetch",
                    side_effect=fake_fetch,
                ):
                    verify.verify_sitemaps(report)

                self.assertEqual(report.checks[-1].status, "fail")

    def test_legacy_url_classification_is_narrow(self):
        for url in (
            "https://robbottx.com/robot/example/",
            "https://robbottx.com/robots-catalog/",
            "https://robbottx.com/category/uncategorized/",
            "https://robbottx.com/author/robojcht_admin/",
            "https://robbottx.com/author/another-author/",
            "https://robbottx.com/hello-world",
            "https://robbottx.com/shop/",
            "https://robbottx.com/cart/",
            "https://robbottx.com/checkout/",
            "https://robbottx.com/my-account/",
            "https://robbottx.com/product/",
            "https://robbottx.com/product/example/",
        ):
            with self.subTest(url=url):
                self.assertTrue(verify.legacy_url(url))

        for url in (
            "https://robbottx.com/",
            "https://robbottx.com/blog/robots/safety/",
            "https://example.com/robot/example/",
            "https://example.com/product/example/",
        ):
            with self.subTest(url=url):
                self.assertFalse(verify.legacy_url(url))

    def test_product_and_product_taxonomy_sitemap_markers_are_private(self):
        for path in (
            "/wp-sitemap-posts-product-1.xml",
            "/wp-sitemap-taxonomies-product_cat-1.xml",
            "/wp-sitemap-taxonomies-product_tag-1.xml",
            "/product-sitemap.xml",
            "/product-category-sitemap.xml",
            "/product-tag-sitemap.xml",
            "/product_cat-sitemap.xml",
            "/product_tag-sitemap.xml",
        ):
            with self.subTest(path=path):
                self.assertTrue(
                    verify.inactive_product_sitemap_url(
                        "https://robbottx.com" + path
                    )
                )
        for path in (
            "/wp-sitemap-posts-page-1.xml",
            "/category-sitemap.xml",
            "/post_tag-sitemap.xml",
        ):
            with self.subTest(path=path):
                self.assertFalse(
                    verify.inactive_product_sitemap_url(
                        "https://robbottx.com" + path
                    )
                )

    def test_versioned_asset_match_is_exact_and_same_origin(self):
        expected = {
            "expected_path": "/wp-content/themes/robbottx/style.css",
            "expected_version": "0.1.4",
        }
        self.assertTrue(
            verify.matches_versioned_asset(
                "/wp-content/themes/robbottx/style.css?ver=0.1.4",
                **expected,
            )
        )
        for url in (
            "/wp-content/themes/robbottx/style.css?ver=0.1.40",
            "/wp-content/themes/robbottx/style.css?ver=0.1.4&ver=0.1.3",
            "https://example.com/wp-content/themes/robbottx/"
            "style.css?ver=0.1.4",
            "/wp-content/themes/robbottx/other.css?ver=0.1.4",
            "/wp-content/themes/robbottx/style.css?ver=0.1.4&x=1",
            "/wp-content/themes/robbottx/style.css?ver=0.1.4#decoy",
        ):
            with self.subTest(url=url):
                self.assertFalse(
                    verify.matches_versioned_asset(url, **expected)
                )

    def test_robots_directives_reject_conflicting_exact_tokens(self):
        facts = verify.parse_html(
            """
            <html>
              <head>
                <meta name="robots" content="noindex, follow">
                <meta name="robots" content="index, follow">
              </head>
              <body></body>
            </html>
            """
        )
        directives = verify.robots_directives(facts)

        self.assertEqual(
            directives,
            {"noindex", "follow", "index"},
        )
        self.assertIn("index", directives)
        self.assertNotIn("nofollow", directives)

    def test_crawler_prefixed_repeated_x_robots_headers_are_enforced(self):
        facts = verify.parse_html(
            "<html><head><title>RobbottX</title>"
            '<meta name="googlebot" content="nofollow">'
            "</head><body></body></html>"
        )
        response = self.http_result(
            200,
            headers={
                "X-Robots-Tag": [
                    "googlebot: index",
                    "noindex, follow",
                    "max-snippet:50",
                ]
            },
        )

        scoped = verify.robots_directives_by_scope(
            facts,
            response.values("x-robots-tag"),
        )

        self.assertEqual(
            scoped["*"],
            {"noindex", "follow", "max-snippet:50"},
        )
        self.assertEqual(
            scoped["googlebot"],
            {"index", "nofollow"},
        )
        self.assertEqual(
            verify.effective_robots_directives(scoped, "googlebot"),
            {
                "follow",
                "index",
                "max-snippet:50",
                "nofollow",
                "noindex",
            },
        )
        combined = verify.robots_directives_by_scope(
            verify.parse_html(
                "<html><head><title>RobbottX</title></head>"
                "<body></body></html>"
            ),
            ["googlebot: index, bingbot: noindex, nofollow"],
        )
        self.assertEqual(combined["*"], set())
        self.assertEqual(combined["googlebot"], {"index"})
        self.assertEqual(
            combined["bingbot"],
            {"noindex", "nofollow"},
        )
        for malformed in (
            "googlebot::",
            "index, googlebot::, follow",
            "bingbot:: noindex",
            "googlebot: :noindex",
        ):
            with self.subTest(malformed=malformed):
                with self.assertRaises(ValueError):
                    verify.robots_directives_by_scope(
                        facts,
                        [malformed],
                    )

    def test_home_requires_one_and_only_one_current_marker(self):
        def marker_status(comments):
            response = self.http_result(
                200,
                (
                    "<html><head><title>RobbottX</title></head><body>"
                    + "".join(f"<!-- {comment} -->" for comment in comments)
                    + "</body></html>"
                ),
                content_type="text/html; charset=UTF-8",
            )
            report = verify.Report(
                plugin_version="0.1.5",
                previous_plugin_version="0.1.4",
                theme_version="0.1.4",
                record_hash="a" * 64,
                expect_fallback_favicon=True,
            )
            with patch.object(verify, "fetch", return_value=response):
                verify.verify_home(report, "0.1.3")
            return next(
                check.status
                for check in report.checks
                if check.check_id == "home.plugin_marker"
            )

        self.assertEqual(
            marker_status(["robbottx-core:0.1.5"]),
            "pass",
        )
        for comments in (
            [],
            ["robbottx-core:0.1.5", "robbottx-core:0.1.5"],
            ["robbottx-core:0.1.5", "robbottx-core:0.1.4"],
            ["robbottx-core:0.1.3"],
        ):
            with self.subTest(comments=comments):
                self.assertEqual(marker_status(comments), "fail")

    def test_home_indexability_rejects_global_and_crawler_noindex(self):
        def status_for(meta="", headers=None):
            html = (
                '<html lang="en-US"><head><title>'
                + verify.HOME_DOCUMENT_TITLE
                + "</title>"
                + meta
                + "</head><body><!-- robbottx-core:0.1.5 --></body></html>"
            )
            response = self.http_result(
                200,
                html,
                content_type="text/html; charset=UTF-8",
                headers=headers,
            )
            report = verify.Report(
                plugin_version="0.1.5",
                previous_plugin_version="0.1.4",
                theme_version="0.1.4",
                record_hash="a" * 64,
                expect_fallback_favicon=True,
            )
            with patch.object(verify, "fetch", return_value=response):
                verify.verify_home(report, "0.1.4")
            return next(
                check.status
                for check in report.checks
                if check.check_id == "home.indexability"
            )

        self.assertEqual(status_for(), "pass")
        self.assertEqual(
            status_for('<meta name="robots" content="noindex">'),
            "fail",
        )
        self.assertEqual(
            status_for('<meta name="googlebot" content="noindex">'),
            "fail",
        )
        self.assertEqual(
            status_for(
                headers={"X-Robots-Tag": "bingbot: noindex"}
            ),
            "fail",
        )
        self.assertEqual(
            status_for(
                headers={
                    "X-Robots-Tag": (
                        "googlebot: unavailable_after: "
                        "25 Jun 2010 15:00:00 PST"
                    )
                }
            ),
            "fail",
        )

    def test_rest_detail_suppression_verifies_get_and_head(self):
        called_detail_methods = []
        called_store_api_methods = []

        def fake_fetch(url, **kwargs):
            path = verify.urllib.parse.urlsplit(url).path
            method = kwargs.get("method", "GET")
            if path == verify.INACTIVE_STORE_API_PATH:
                called_store_api_methods.append(method)
                body = (
                    '{"code":"rest_not_found","message":"Not found.",'
                    '"data":{"status":404}}'
                    if method == "GET"
                    else b""
                )
                return self.http_result(404, body, final_url=url)
            if path in {
                verify.urllib.parse.urlsplit(item).path
                for item in verify.LEGACY_REST_DETAILS
            }:
                called_detail_methods.append((path, method))
                body = (
                    '{"code":"rest_not_found","message":"Not found.",'
                    '"data":{"status":404}}'
                    if method == "GET"
                    else b""
                )
                return self.http_result(404, body, final_url=url)
            if path == "/wp-json/wp/v2/search":
                return self.http_result(
                    200,
                    "[]",
                    final_url=url,
                    headers={"x-wp-total": "0"},
                )
            return self.http_result(
                200,
                "[]",
                final_url=url,
                headers={"x-wp-total": "0"},
            )

        report = verify.Report(
            plugin_version="0.1.5",
            previous_plugin_version="0.1.4",
            theme_version="0.1.4",
            record_hash="a" * 64,
            expect_fallback_favicon=True,
        )
        with patch.object(verify, "fetch", side_effect=fake_fetch):
            verify.verify_rest(report)

        self.assertEqual(
            len(called_detail_methods),
            len(verify.LEGACY_REST_DETAILS) * 2,
        )
        for path in verify.LEGACY_REST_DETAILS:
            normalized = verify.urllib.parse.urlsplit(path).path
            self.assertIn((normalized, "GET"), called_detail_methods)
            self.assertIn((normalized, "HEAD"), called_detail_methods)
        self.assertEqual(
            called_store_api_methods,
            ["GET", "HEAD"],
        )
        details = next(
            check
            for check in report.checks
            if check.check_id == "discovery.rest_details"
        )
        self.assertEqual(details.status, "pass")
        collections = next(
            check
            for check in report.checks
            if check.check_id == "discovery.rest_collections"
        )
        self.assertEqual(collections.status, "pass")
        self.assertIn(
            "/wp-json/wp/v2/product",
            {
                endpoint["path"]
                for endpoint in collections.evidence["endpoints"]
            },
        )
        self.assertEqual(
            next(
                check.status
                for check in report.checks
                if check.check_id
                == "discovery.rest_product_taxonomies"
            ),
            "pass",
        )
        self.assertEqual(
            next(
                check.status
                for check in report.checks
                if check.check_id == "discovery.store_api_products"
            ),
            "pass",
        )

    def test_optional_product_taxonomies_require_exact_json_boundaries(self):
        taxonomy_paths = {
            verify.urllib.parse.urlsplit(path).path
            for path in verify.INACTIVE_PRODUCT_TAXONOMY_COLLECTIONS
        }
        detail_paths = {
            verify.urllib.parse.urlsplit(path).path
            for path in verify.LEGACY_REST_DETAILS
        }

        def taxonomy_status(*, html_proxy=False, code="rest_no_route"):
            def fake_fetch(url, **kwargs):
                path = verify.urllib.parse.urlsplit(url).path
                method = kwargs.get("method", "GET")
                if path in taxonomy_paths:
                    if html_proxy:
                        return self.http_result(
                            404,
                            "<html><body>Missing</body></html>",
                            content_type="text/html",
                            final_url=url,
                        )
                    return self.http_result(
                        404,
                        json.dumps(
                            {
                                "code": code,
                                "message": "Not found.",
                                "data": {"status": 404},
                            }
                        ),
                        final_url=url,
                    )
                if path == verify.INACTIVE_STORE_API_PATH:
                    return self.http_result(
                        404,
                        (
                            '{"code":"rest_no_route",'
                            '"message":"Not found.",'
                            '"data":{"status":404}}'
                            if method == "GET"
                            else b""
                        ),
                        final_url=url,
                    )
                if path in detail_paths:
                    return self.http_result(
                        404,
                        (
                            '{"code":"rest_not_found",'
                            '"message":"Not found.",'
                            '"data":{"status":404}}'
                            if method == "GET"
                            else b""
                        ),
                        final_url=url,
                    )
                return self.http_result(
                    200,
                    "[]",
                    final_url=url,
                    headers={"x-wp-total": "0"},
                )

            report = verify.Report(
                plugin_version="0.1.6",
                previous_plugin_version="0.1.5",
                theme_version="0.1.5",
                record_hash="a" * 64,
                expect_fallback_favicon=True,
            )
            with patch.object(verify, "fetch", side_effect=fake_fetch):
                verify.verify_rest(report)
            return next(
                check.status
                for check in report.checks
                if check.check_id
                == "discovery.rest_product_taxonomies"
            )

        self.assertEqual(taxonomy_status(), "pass")
        self.assertEqual(taxonomy_status(code="rest_not_found"), "fail")
        self.assertEqual(taxonomy_status(html_proxy=True), "fail")

    def test_store_api_product_boundary_rejects_proxy_or_ambiguous_404(self):
        detail_paths = {
            verify.urllib.parse.urlsplit(path).path
            for path in verify.LEGACY_REST_DETAILS
        }

        def store_status(*, html_proxy=False, code="rest_not_found"):
            def fake_fetch(url, **kwargs):
                path = verify.urllib.parse.urlsplit(url).path
                method = kwargs.get("method", "GET")
                if path == verify.INACTIVE_STORE_API_PATH:
                    if html_proxy:
                        return self.http_result(
                            404,
                            "<html><body>Missing</body></html>",
                            content_type="text/html",
                            final_url=url,
                        )
                    return self.http_result(
                        404,
                        (
                            json.dumps(
                                {
                                    "code": code,
                                    "message": "Not found.",
                                    "data": {"status": 404},
                                }
                            )
                            if method == "GET"
                            else b""
                        ),
                        final_url=url,
                    )
                if path in detail_paths:
                    return self.http_result(
                        404,
                        (
                            '{"code":"rest_not_found",'
                            '"message":"Not found.",'
                            '"data":{"status":404}}'
                            if method == "GET"
                            else b""
                        ),
                        final_url=url,
                    )
                return self.http_result(
                    200,
                    "[]",
                    final_url=url,
                    headers={"x-wp-total": "0"},
                )

            report = verify.Report(
                plugin_version="0.1.6",
                previous_plugin_version="0.1.5",
                theme_version="0.1.5",
                record_hash="a" * 64,
                expect_fallback_favicon=True,
            )
            with patch.object(verify, "fetch", side_effect=fake_fetch):
                verify.verify_rest(report)
            return next(
                check.status
                for check in report.checks
                if check.check_id == "discovery.store_api_products"
            )

        self.assertEqual(store_status(), "pass")
        self.assertEqual(store_status(code="rest_no_route"), "pass")
        self.assertEqual(store_status(code="other_error"), "fail")
        self.assertEqual(store_status(html_proxy=True), "fail")

    def test_direct_legacy_html_requires_a_clean_gone_response(self):
        clean_error = (
            '<html lang="en-US"><head><title>Page not found.</title>'
            '<meta name="robots" content="noindex, follow"></head>'
            '<body><main><h1>Page not found.</h1>'
            "<p>The address may have changed.</p></main></body></html>"
        )

        def status_for(status, html=clean_error):
            report = verify.Report(
                plugin_version="0.1.5",
                previous_plugin_version="0.1.4",
                theme_version="0.1.4",
                record_hash="a" * 64,
                expect_fallback_favicon=True,
            )
            response = self.http_result(
                status,
                html,
                content_type="text/html; charset=UTF-8",
            )
            with patch.object(verify, "fetch", return_value=response):
                verify.verify_legacy_html(report)
            return report.checks[-1].status

        self.assertEqual(status_for(404), "fail")
        self.assertEqual(status_for(410), "pass")
        self.assertEqual(status_for(200), "fail")
        self.assertEqual(
            status_for(
                410,
                clean_error.replace(
                    "The address may have changed.",
                    "Hello world",
                ),
            ),
            "fail",
        )

    def test_search_and_feed_reject_result_markup_and_retired_text(self):
        no_results = (
            "No results found. Try another search term or return to the atlas."
        )

        def check(search_extra=""):
            def fake_fetch(url, **kwargs):
                path = verify.urllib.parse.urlsplit(url).path
                if path == "/":
                    return self.http_result(
                        200,
                        (
                            '<html lang="en-US"><head><title>Search</title>'
                            "</head><body><main><h1>Search</h1><p>"
                            + no_results
                            + "</p>"
                            + search_extra
                            + "</main></body></html>"
                        ),
                        content_type="text/html; charset=UTF-8",
                        final_url=url,
                    )
                return self.http_result(404, final_url=url)

            report = verify.Report(
                plugin_version="0.1.5",
                previous_plugin_version="0.1.4",
                theme_version="0.1.4",
                record_hash="a" * 64,
                expect_fallback_favicon=True,
            )
            with patch.object(verify, "fetch", side_effect=fake_fetch):
                verify.verify_search_and_feed(report)
            return {
                item.check_id: item.status for item in report.checks
            }

        self.assertEqual(check()["discovery.html_search"], "pass")
        self.assertEqual(
            check(
                '<h2 class="wp-block-post-title">Hello world</h2>'
            )["discovery.html_search"],
            "fail",
        )

    def test_feed_full_text_is_checked_for_retired_names(self):
        rss = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<rss><channel><title>RobbottX</title>"
            "<description>{description}</description></channel></rss>"
        )

        def feed_status(description):
            def fake_fetch(url, **kwargs):
                return self.http_result(
                    200,
                    rss.format(description=description),
                    content_type="application/rss+xml; charset=UTF-8",
                    final_url=url,
                )

            report = verify.Report(
                plugin_version="0.1.5",
                previous_plugin_version="0.1.4",
                theme_version="0.1.4",
                record_hash="a" * 64,
                expect_fallback_favicon=True,
            )
            with patch.object(verify, "fetch", side_effect=fake_fetch):
                verify.verify_search_and_feed(report)
            return next(
                item.status
                for item in report.checks
                if item.check_id == "discovery.feed"
            )

        self.assertEqual(feed_status("Established robotics records."), "pass")
        self.assertEqual(feed_status("Hello world"), "fail")

    def test_inactive_commerce_routes_are_gone_without_browser_proof(self):
        error_html = (
            '<html lang="en-US"><head><title>'
            "Page not found. \u2013 RobbottX</title>"
            '<meta name="robots" content="noindex, follow"></head>'
            '<body><header><a href="/">RobbottX</a></header>'
            '<main id="main-content" '
            'class="wp-block-group rbtx-content-shell">'
            '<h1 class="wp-block-heading">Page not found.</h1>'
            "<p>The address may have changed. Try another search term "
            "or return to the atlas.</p></main></body></html>"
        )
        home_html = (
            '<html lang="en-US"><head><title>RobbottX</title></head>'
            '<body><nav><a href="/">Atlas</a></nav>'
            '<main id="main-content"><h1>RobbottX</h1></main>'
            "</body></html>"
        )
        cache_headers = {
            "Cache-Control": (
                "no-cache, must-revalidate, max-age=0, no-store, private"
            )
        }

        def statuses(
            *,
            route_html=error_html,
            route_status=410,
            route_headers=cache_headers,
            homepage=home_html,
        ):
            called_paths = []

            def fake_fetch(url, **kwargs):
                path = verify.urllib.parse.urlsplit(url).path
                called_paths.append(path)
                if path == "/":
                    return self.http_result(
                        200,
                        homepage,
                        content_type="text/html; charset=UTF-8",
                        final_url=url,
                    )
                if path in verify.INACTIVE_COMMERCE_PATHS:
                    return self.http_result(
                        route_status,
                        route_html,
                        content_type="text/html; charset=UTF-8",
                        final_url=url,
                        headers=route_headers,
                    )
                raise AssertionError(f"Unexpected path: {path}")

            report = verify.Report(
                plugin_version="0.1.6",
                previous_plugin_version="0.1.5",
                theme_version="0.1.5",
                record_hash="a" * 64,
                expect_fallback_favicon=True,
            )
            with (
                patch.object(verify, "fetch", side_effect=fake_fetch),
                patch.object(
                    verify,
                    "commerce_browser_proof",
                ) as browser_proof,
            ):
                verify.verify_commerce(report)
            browser_proof.assert_not_called()
            return (
                {
                    check.check_id: check.status
                    for check in report.checks
                },
                called_paths,
            )

        baseline, called_paths = statuses()
        self.assertEqual(baseline["commerce.routes"], "pass")
        self.assertEqual(baseline["commerce.navigation"], "pass")
        for path in verify.INACTIVE_COMMERCE_PATHS:
            self.assertIn(path, called_paths)
        self.assertNotIn("/product/", called_paths)

        route_failures = {
            "wrong_status": {"route_status": 404},
            "cacheable": {
                "route_headers": {
                    "Cache-Control": "public, max-age=300"
                }
            },
            "conflicting_robots": {
                "route_html": error_html.replace(
                    "noindex, follow",
                    "noindex, index",
                )
            },
            "wrong_language": {
                "route_html": error_html.replace(
                    'lang="en-US"',
                    'lang="he-IL"',
                )
            },
            "duplicate_main": {
                "route_html": error_html.replace(
                    "</body>",
                    "<main><h1>Other</h1></main></body>",
                )
            },
            "unfinished_language": {
                "route_html": error_html.replace(
                    "The address may have changed.",
                    "Coming soon.",
                )
            },
            "commerce_link": {
                "route_html": error_html.replace(
                    "</main>",
                    '<a href="/product/hidden/">Hidden</a></main>',
                )
            },
            "commerce_class": {
                "route_html": error_html.replace(
                    'class="wp-block-group rbtx-content-shell"',
                    (
                        'class="wp-block-group rbtx-content-shell '
                        'woocommerce-shop"'
                    ),
                )
            },
        }
        for case, arguments in route_failures.items():
            with self.subTest(case=case):
                failed, _called = statuses(**arguments)
                self.assertEqual(failed["commerce.routes"], "fail")

        exposed_navigation, _called = statuses(
            homepage=home_html.replace(
                "</nav>",
                '<a href="/shop/">Shop</a></nav>',
            )
        )
        self.assertEqual(
            exposed_navigation["commerce.navigation"],
            "fail",
        )

    def _active_commerce_contract_reference(self):
        def page(
            body_class,
            *,
            robots=None,
            robots_name="robots",
            extra_class="",
            title="RobbottX commerce",
            route_ui="",
        ):
            robots_meta = (
                f'<meta name="{robots_name}" content="{robots}">'
                if robots
                else ""
            )
            return (
                '<html lang="en-US"><head>'
                f"<title>{title}</title>"
                + robots_meta
                + '<link rel="stylesheet" href="/wp-content/plugins/'
                'woocommerce/assets/store.css">'
                "</head><body class=\""
                + body_class
                + " "
                + extra_class
                + '"><main><h1>Commerce</h1>'
                + route_ui
                + "</main></body></html>"
            )

        valid_pages = {
            "/shop/": page(
                "woocommerce-shop",
                route_ui=(
                    '<ul class="products"><li class="product">'
                    '<a href="/product/reviewed-system/">'
                    "Reviewed system</a></li></ul>"
                ),
            ),
            "/cart/": page(
                "woocommerce-cart",
                robots="noindex, follow",
                route_ui=(
                    '<p class="cart-empty">'
                    "Your cart is currently empty."
                    '</p><p class="return-to-shop">'
                    '<a href="/shop/">Return to shop</a></p>'
                ),
            ),
            "/my-account/": page(
                "woocommerce-account",
                robots="noindex, follow",
                route_ui=(
                    '<form class="woocommerce-form-login" '
                    'method="post" action="">'
                    '<input type="hidden" name="woocommerce-login-nonce" '
                    'value="a1b2c3d4e5">'
                    '<input name="username">'
                    '<input type="password" name="password">'
                    '<button type="submit" name="login" value="Log in">'
                    "Log in</button>"
                    "</form>"
                ),
            ),
        }

        def commerce_status(
            *,
            pages=None,
            checkout="/cart/",
            asset_status=200,
            asset_body="body{display:block}",
            product_page=None,
            product_headers=None,
            checkout_page=None,
        ):
            selected = {**valid_pages, **(pages or {})}

            def fake_fetch(url, **kwargs):
                path = verify.urllib.parse.urlsplit(url).path
                if path.startswith(
                    "/wp-content/plugins/woocommerce/"
                ):
                    return self.http_result(
                        asset_status,
                        asset_body if asset_status == 200 else "",
                        content_type="text/css; charset=UTF-8",
                        final_url=url,
                    )
                if path == "/wp-json/wp/v2/product":
                    query = verify.urllib.parse.parse_qs(
                        verify.urllib.parse.urlsplit(url).query
                    )
                    slug = query.get("slug", [""])[0]
                    payload = (
                        [
                            {
                                "id": 41,
                                "slug": "reviewed-system",
                                "link": (
                                    "https://robbottx.com/product/"
                                    "reviewed-system/"
                                ),
                                "status": "publish",
                                "type": "product",
                            }
                        ]
                        if slug == "reviewed-system"
                        else []
                    )
                    return self.http_result(
                        200,
                        json.dumps(payload),
                        content_type="application/json; charset=UTF-8",
                        final_url=url,
                    )
                if path.startswith("/product/"):
                    if path == "/product/soft-missing/":
                        return self.http_result(
                            200,
                            "<html lang=\"en-US\"><head>"
                            "<title>Page not found</title></head>"
                            "<body class=\"single-product\"><main>"
                            "<h1>Page not found</h1></main></body></html>",
                            content_type="text/html; charset=UTF-8",
                            final_url=url,
                        )
                    if path != "/product/reviewed-system/":
                        return self.http_result(
                            404,
                            "<html lang=\"en-US\"><head><title>Missing</title>"
                            "</head><body><main><h1>Missing</h1></main>"
                            "</body></html>",
                            content_type="text/html; charset=UTF-8",
                            final_url=url,
                        )
                    return self.http_result(
                        200,
                        product_page
                        or (
                            "<html lang=\"en-US\"><head>"
                            "<title>Product</title></head>"
                            "<body class=\"single-product\">"
                            "<main><div class=\"product\">"
                            "<div class=\"summary\">"
                            "<h1 class=\"product_title\">"
                            "Reviewed system</h1>"
                            "<p class=\"stock in-stock\">In stock</p>"
                            + current_offer_evidence_html()
                            + "<form class=\"cart\" method=\"post\" "
                            "action=\"/product/reviewed-system/\">"
                            "<button type=\"submit\" "
                            "name=\"add-to-cart\" value=\"41\">"
                            "Add to cart</button>"
                            "</form></div></div></main>"
                            "</body></html>"
                        ),
                        content_type="text/html; charset=UTF-8",
                        final_url=url,
                        headers=product_headers,
                    )
                if path == "/checkout/":
                    if checkout_page is not None:
                        return self.http_result(
                            200,
                            checkout_page,
                            content_type="text/html; charset=UTF-8",
                            final_url=url,
                        )
                    return self.http_result(
                        302,
                        headers={"location": checkout},
                        content_type="text/html",
                        final_url=url,
                    )
                return self.http_result(
                    200,
                    selected[path],
                    content_type="text/html; charset=UTF-8",
                    final_url=url,
                )

            report = verify.Report(
                plugin_version="0.1.5",
                previous_plugin_version="0.1.4",
                theme_version="0.1.4",
                record_hash="a" * 64,
                expect_fallback_favicon=True,
            )
            def fake_browser_proof(*, mode, **kwargs):
                if mode == "product":
                    route_ui = "product"
                elif mode == "shop":
                    shop_markup = selected["/shop/"]
                    route_ui = (
                        "product_catalog"
                        if "/product/" in shop_markup
                        else "reviewed_empty_state"
                    )
                elif mode == "cart":
                    route_ui = (
                        "cart"
                        if "<form" in selected["/cart/"]
                        else "reviewed_empty_state"
                    )
                elif mode == "account":
                    route_ui = "login_form"
                else:
                    route_ui = (
                        "checkout"
                        if checkout_page is not None
                        else "empty_cart_redirect"
                    )
                return {"passed": True, "routeUi": route_ui}

            with (
                patch.object(verify, "fetch", side_effect=fake_fetch),
                patch.object(
                    verify,
                    "commerce_browser_proof",
                    side_effect=fake_browser_proof,
                ),
            ):
                verify.verify_commerce(report)
            return report.checks[-1].status

        self.assertEqual(commerce_status(), "pass")
        self.assertEqual(
            commerce_status(
                pages={
                    "/shop/": page(
                        "woocommerce-shop",
                        route_ui=(
                            '<ul class="products">'
                            '<li class="product">'
                            '<a href="/product/reviewed-system/">'
                            "Reviewed system</a></li></ul>"
                        ),
                    ),
                    "/cart/": page(
                        "woocommerce-cart",
                        robots="noindex, follow",
                        route_ui=(
                            '<form class="woocommerce-cart-form" '
                            'method="post" action="/cart/">'
                            '<input type="hidden" '
                            'name="woocommerce-cart-nonce" '
                            'value="a1b2c3d4e5">'
                            '<div class="cart_item">'
                            '<input name="cart[1][qty]" value="1"></div>'
                            '<button type="submit" name="update_cart">'
                            "Update cart</button>"
                            "</form>"
                        ),
                    ),
                }
            ),
            "pass",
        )
        reviewed_catalog = {
            "/shop/": page(
                "woocommerce-shop",
                route_ui=(
                    '<ul class="products"><li class="product">'
                    '<a href="/product/reviewed-system/">'
                    "Reviewed system</a></li></ul>"
                ),
            )
        }

        def product_document(
            form_markup,
            *,
            stock_markup=(
                '<p class="stock in-stock">In stock</p>'
            ),
            offer_markup=current_offer_evidence_html(),
            related_markup="",
            outside_markup="",
        ):
            return (
                '<html lang="en-US"><head><title>Product</title></head>'
                '<body class="single-product"><main>'
                '<div class="product"><div class="summary">'
                '<h1 class="product_title">Reviewed system</h1>'
                + stock_markup
                + offer_markup
                + form_markup
                + "</div></div>"
                + related_markup
                + outside_markup
                + "</main></body></html>"
            )

        hidden_identifier = (
            '<form class="cart" method="post" '
            'action="/product/reviewed-system/">'
            '<input type="hidden" name="add-to-cart" value="41">'
            '<input type="hidden" name="product_id" value="41">'
            '<button type="submit">Add to cart</button></form>'
        )
        self.assertEqual(
            commerce_status(
                pages=reviewed_catalog,
                product_page=product_document(hidden_identifier),
            ),
            "pass",
        )
        product_id_only = (
            '<form class="cart" method="post" '
            'action="/product/reviewed-system/">'
            '<input type="hidden" name="product_id" value="41">'
            '<button type="submit">Add to cart</button></form>'
        )
        self.assertEqual(
            commerce_status(
                pages=reviewed_catalog,
                product_page=product_document(product_id_only),
            ),
            "fail",
        )
        image_identifier = (
            '<form class="cart" method="post" '
            'action="/product/reviewed-system/">'
            '<input type="image" name="add-to-cart" value="41" '
            'alt="Add to cart"></form>'
        )
        self.assertEqual(
            commerce_status(
                pages=reviewed_catalog,
                product_page=product_document(image_identifier),
            ),
            "fail",
        )
        hidden_trigger_with_image_submit = (
            '<form class="cart" method="post" '
            'action="/product/reviewed-system/">'
            '<input type="hidden" name="add-to-cart" value="41">'
            '<input type="image" alt="Add to cart"></form>'
        )
        self.assertEqual(
            commerce_status(
                pages=reviewed_catalog,
                product_page=product_document(
                    hidden_trigger_with_image_submit
                ),
            ),
            "pass",
        )
        hidden_submit_identifier = (
            '<form class="cart" method="post" '
            'action="/product/reviewed-system/">'
            '<input type="submit" name="product_id" value="41" hidden>'
            '<button type="submit">Add to cart</button></form>'
        )
        self.assertEqual(
            commerce_status(
                pages=reviewed_catalog,
                product_page=product_document(
                    hidden_submit_identifier
                ),
            ),
            "fail",
        )
        for contradictory_stock in (
            '<p class="stock in-stock">Out of stock</p>',
            '<p class="stock in-stock">Sold out</p>',
            (
                '<p class="stock available-on-backorder">'
                "Unavailable</p>"
            ),
            (
                '<p class="stock in-stock">In stock</p>'
                '<p class="stock out-of-stock">Out of stock</p>'
            ),
        ):
            with self.subTest(stock=contradictory_stock):
                self.assertEqual(
                    commerce_status(
                        pages=reviewed_catalog,
                        product_page=product_document(
                            hidden_identifier,
                            stock_markup=contradictory_stock,
                        ),
                    ),
                    "fail",
                )
        external_identifier_form = (
            '<form id="primary-cart" class="cart" method="post" '
            'action="/product/reviewed-system/">'
            '<button type="submit">Add to cart</button></form>'
        )
        self.assertEqual(
            commerce_status(
                pages=reviewed_catalog,
                product_page=product_document(
                    external_identifier_form,
                    outside_markup=(
                        '<input type="hidden" name="product_id" '
                        'value="41" form="primary-cart">'
                    ),
                ),
            ),
            "fail",
        )
        blocked_submit_handler = hidden_identifier.replace(
            '<form class="cart"',
            '<form class="cart" onsubmit="return false"',
        )
        self.assertEqual(
            commerce_status(
                pages=reviewed_catalog,
                product_page=product_document(
                    blocked_submit_handler
                ),
            ),
            "fail",
        )
        blocked_click_action = hidden_identifier.replace(
            '<button type="submit">',
            '<button type="submit" onclick="return false">',
        )
        self.assertEqual(
            commerce_status(
                pages=reviewed_catalog,
                product_page=product_document(blocked_click_action),
            ),
            "fail",
        )
        for unsafe_override in (
            'formaction="https://evil.example/steal"',
            'formaction="/cart/"',
            'formmethod="get"',
            'formtarget="_blank"',
            'formenctype="text/plain"',
            'onclick="throw new Error()"',
            'onclick="event.returnValue=false"',
        ):
            with self.subTest(submitter_override=unsafe_override):
                unsafe_action = hidden_identifier.replace(
                    '<button type="submit">',
                    f'<button type="submit" {unsafe_override}>',
                )
                self.assertEqual(
                    commerce_status(
                        pages=reviewed_catalog,
                        product_page=product_document(unsafe_action),
                    ),
                    "fail",
                )
        for unsafe_form_attribute in (
            'enctype="text/plain"',
            'target="_blank"',
            'onsubmit="throw new Error()"',
        ):
            with self.subTest(form_override=unsafe_form_attribute):
                unsafe_form = hidden_identifier.replace(
                    '<form class="cart"',
                    f'<form class="cart" {unsafe_form_attribute}',
                )
                self.assertEqual(
                    commerce_status(
                        pages=reviewed_catalog,
                        product_page=product_document(unsafe_form),
                    ),
                    "fail",
                )
        self.assertEqual(
            commerce_status(
                pages=reviewed_catalog,
                product_headers={
                    "X-Robots-Tag": (
                        "index, googlebot::, follow"
                    )
                },
            ),
            "fail",
        )
        self.assertEqual(
            commerce_status(
                pages={
                    "/shop/": page(
                        "woocommerce-shop",
                        route_ui=(
                            '<ul class="products"><li class="product">'
                            '<a href="/product/reviewed-system/"></a>'
                            "</li></ul>"
                        ),
                    ),
                }
            ),
            "fail",
        )
        self.assertEqual(
            commerce_status(
                pages={
                    "/shop/": valid_pages["/shop/"].replace(
                        "</main>",
                        (
                            "<script>document.body.textContent="
                            "'403 Forbidden';</script></main>"
                        ),
                    )
                }
            ),
            "fail",
        )
        disabled_fieldset_action = (
            '<form class="cart" method="post" '
            'action="/product/reviewed-system/">'
            "<fieldset disabled>"
            '<input type="hidden" name="product_id" value="41">'
            '<button type="submit">Add to cart</button>'
            "</fieldset></form>"
        )
        self.assertEqual(
            commerce_status(
                pages=reviewed_catalog,
                product_page=product_document(
                    disabled_fieldset_action
                ),
            ),
            "fail",
        )
        first_legend_action = (
            '<form class="cart" method="post" '
            'action="/product/reviewed-system/">'
            "<fieldset disabled><legend>"
            '<button type="submit" name="add-to-cart" value="41">'
            "Add to cart</button></legend>"
            '<button type="submit" name="add-to-cart" value="999">'
            "Disabled decoy</button></fieldset></form>"
        )
        self.assertEqual(
            commerce_status(
                pages=reviewed_catalog,
                product_page=product_document(first_legend_action),
            ),
            "pass",
        )
        overridden_identifier = (
            '<form class="cart" method="post" '
            'action="/product/reviewed-system/">'
            '<input type="hidden" name="product_id" value="41" '
            'form="other-form">'
            '<button type="submit">Add to cart</button></form>'
        )
        self.assertEqual(
            commerce_status(
                pages=reviewed_catalog,
                product_page=product_document(
                    overridden_identifier,
                    outside_markup='<form id="other-form"></form>',
                ),
            ),
            "fail",
        )
        self.assertEqual(
            commerce_status(
                pages=reviewed_catalog,
                product_page=product_document(
                    hidden_identifier,
                    stock_markup="",
                    outside_markup=(
                        '<p class="stock in-stock">In stock</p>'
                    ),
                ),
            ),
            "fail",
        )
        self.assertEqual(
            commerce_status(
                pages=reviewed_catalog,
                product_page=product_document(
                    hidden_identifier,
                    stock_markup=(
                        '<p class="stock out-of-stock">'
                        "Out of stock</p>"
                    ),
                ),
            ),
            "fail",
        )
        related_card = (
            '<section class="related"><div class="product">'
            "<h2>Related system</h2>"
            '<form class="cart" method="post" action="/product/related/">'
            '<button type="submit" name="add-to-cart" value="99">'
            "View related system</button></form></div></section>"
        )
        self.assertEqual(
            commerce_status(
                pages=reviewed_catalog,
                product_page=product_document(
                    hidden_identifier,
                    related_markup=related_card,
                ),
            ),
            "pass",
        )
        disconnected_product = (
            '<html lang="en-US"><head><title>Product</title></head>'
            '<body class="single-product"><main>'
            '<div class="product"><div class="summary">'
            '<h1 class="product_title">Reviewed system</h1>'
            '<span class="cart">Decoy</span></div></div>'
            '<form class="cart" method="post" '
            'action="/product/reviewed-system/">'
            '<button type="submit" name="add-to-cart">'
            "Add to cart</button></form></main></body></html>"
        )
        self.assertEqual(
            commerce_status(
                pages=reviewed_catalog,
                product_page=disconnected_product,
            ),
            "fail",
        )
        wrong_product_identifier = (
            '<html lang="en-US"><head><title>Product</title></head>'
            '<body class="single-product"><main>'
            '<div class="product"><div class="summary">'
            '<h1 class="product_title">Reviewed system</h1>'
            '<form class="cart" method="post" '
            'action="/product/reviewed-system/">'
            '<button type="submit" name="add-to-cart" value="999">'
            "Add to cart</button></form></div></div>"
            "</main></body></html>"
        )
        self.assertEqual(
            commerce_status(
                pages=reviewed_catalog,
                product_page=wrong_product_identifier,
            ),
            "fail",
        )
        disabled_identifier = (
            '<html lang="en-US"><head><title>Product</title></head>'
            '<body class="single-product"><main>'
            '<div class="product"><div class="summary">'
            '<h1 class="product_title">Reviewed system</h1>'
            '<form class="cart" method="post" '
            'action="/product/reviewed-system/">'
            '<input type="hidden" name="product_id" value="41" disabled>'
            '<button type="submit">Add to cart</button>'
            "</form></div></div></main></body></html>"
        )
        self.assertEqual(
            commerce_status(
                pages=reviewed_catalog,
                product_page=disabled_identifier,
            ),
            "fail",
        )
        split_product_context = (
            '<html lang="en-US"><head><title>Product</title></head>'
            '<body class="single-product"><main>'
            '<div class="product"><div class="summary">'
            '<h1 class="product_title">Reviewed system</h1>'
            "</div></div>"
            '<div class="product"><div class="summary">'
            '<form class="cart" method="post" '
            'action="/product/reviewed-system/">'
            '<button type="submit" name="add-to-cart" value="41">'
            "Add to cart</button></form></div></div>"
            "</main></body></html>"
        )
        self.assertEqual(
            commerce_status(
                pages=reviewed_catalog,
                product_page=split_product_context,
            ),
            "fail",
        )
        disabled_get_product = (
            '<html lang="en-US"><head><title>Product</title></head>'
            '<body class="single-product"><main>'
            '<div class="product"><div class="summary">'
            '<h1 class="product_title">Reviewed system</h1>'
            '<form class="cart" method="get" '
            'action="/product/reviewed-system/">'
            '<button type="submit" name="add-to-cart" disabled>'
            "Add to cart</button></form></div></div>"
            "</main></body></html>"
        )
        self.assertEqual(
            commerce_status(
                pages=reviewed_catalog,
                product_page=disabled_get_product,
            ),
            "fail",
        )
        hidden_product = (
            '<html lang="en-US"><head><title>Product</title></head>'
            '<body class="single-product"><main>'
            '<div class="screen-reader-text"><div class="product">'
            '<div class="summary">'
            '<h1 class="product_title">Reviewed system</h1>'
            '<form class="cart" method="post" '
            'action="/product/reviewed-system/">'
            '<button type="submit" name="add-to-cart">'
            "Add to cart</button></form></div></div></div>"
            "</main></body></html>"
        )
        self.assertEqual(
            commerce_status(
                pages=reviewed_catalog,
                product_page=hidden_product,
            ),
            "fail",
        )
        product_ui = (
            '<div class="product"><div class="summary">'
            '<h1 class="product_title">Reviewed system</h1>'
            '<form class="cart" method="post" '
            'action="/product/reviewed-system/">'
            '<button type="submit" name="add-to-cart" value="41">'
            "Add to cart</button></form></div></div>"
        )
        for wrapper_start, wrapper_end in (
            ("<template>", "</template>"),
            ("<dialog>", "</dialog>"),
            ("<details>", "</details>"),
            (
                '<div style="position:absolute;left:-9999px">',
                "</div>",
            ),
        ):
            with self.subTest(wrapper_start=wrapper_start):
                self.assertEqual(
                    commerce_status(
                        pages=reviewed_catalog,
                        product_page=(
                            '<html lang="en-US"><head>'
                            "<title>Product</title></head>"
                            '<body class="single-product"><main>'
                            + wrapper_start
                            + product_ui
                            + wrapper_end
                            + "</main></body></html>"
                        ),
                    ),
                    "fail",
                )
        soft_error_product = (
            '<html lang="en-US"><head><title>Product</title></head>'
            '<body class="single-product"><main>'
            "<p>Sorry, this requested item could not be located.</p>"
            + product_ui
            + "</main></body></html>"
        )
        self.assertEqual(
            commerce_status(
                pages=reviewed_catalog,
                product_page=soft_error_product,
            ),
            "fail",
        )
        self.assertEqual(
            commerce_status(
                pages=reviewed_catalog,
                product_headers={
                    "X-Robots-Tag": (
                        "googlebot: index, bingbot: noindex"
                    )
                },
            ),
            "fail",
        )
        self.assertEqual(
            commerce_status(
                pages={
                    "/shop/": page(
                        "woocommerce-shop",
                        route_ui=(
                            '<ul class="products">'
                            '<li class="product">'
                            '<a href="/product/nonexistent/">'
                            "Missing system</a></li></ul>"
                        ),
                    ),
                }
            ),
            "fail",
        )
        for hidden_attribute in (
            "hidden",
            'aria-hidden="true"',
            "inert",
            'class="screen-reader-text"',
            'style="display: none"',
            'style="dis/**/play:/**/none"',
            'style="visibility: hidden"',
            'style="content-visibility: hidden"',
            'style="opacity: 0"',
            'style="opacity: 0%"',
            'style="clip: rect(0, 0, 0, 0)"',
            'style="clip-path: inset(50% 50% 50% 50%)"',
            'style="width: 0; height: 0"',
            'style="transform: scale(0%)"',
            'style="transform: translateX(-9999px)"',
            "popover",
        ):
            with self.subTest(hidden_attribute=hidden_attribute):
                self.assertEqual(
                    commerce_status(
                        pages={
                            "/shop/": page(
                                "woocommerce-shop",
                                route_ui=(
                                    f"<div {hidden_attribute}>"
                                    '<p class="woocommerce-info">'
                                    "No products were found matching "
                                    "your selection.</p></div>"
                                ),
                            )
                        }
                    ),
                    "fail",
                )
        for hidden_container in ("datalist", "select"):
            with self.subTest(hidden_container=hidden_container):
                self.assertEqual(
                    commerce_status(
                        pages={
                            "/shop/": page(
                                "woocommerce-shop",
                                route_ui=(
                                    f"<{hidden_container}>"
                                    '<p class="woocommerce-info">'
                                    "No products were found matching "
                                    "your selection.</p>"
                                    f"</{hidden_container}>"
                                ),
                            )
                        }
                    ),
                    "fail",
                )
        self.assertEqual(
            commerce_status(
                pages={
                    "/shop/": page(
                        "woocommerce-shop",
                        route_ui=(
                            '<ul class="products">'
                            '<li class="product">'
                            '<a href="/product/soft-missing/">'
                            "Missing system</a></li></ul>"
                        ),
                    ),
                }
            ),
            "fail",
        )
        self.assertEqual(
            commerce_status(asset_status=404),
            "fail",
        )
        self.assertEqual(
            commerce_status(asset_body="x"),
            "fail",
        )
        self.assertEqual(
            commerce_status(
                pages={
                    "/shop/": page(
                        "woocommerce-shop",
                        extra_class="wp-block-woocommerce-coming-soon",
                    )
                }
            ),
            "fail",
        )
        self.assertEqual(
            commerce_status(
                pages={
                    "/cart/": page(
                        "woocommerce-cart",
                        robots="noindex, follow",
                        route_ui=(
                            '<form class="woocommerce-cart-form" '
                            'action="/cart/"></form>'
                        ),
                    )
                }
            ),
            "fail",
        )
        self.assertEqual(
            commerce_status(
                pages={
                    "/shop/": page(
                        "woocommerce-shop",
                        route_ui=(
                            '<div class="products"></div>'
                            '<div class="product"></div>'
                        ),
                    )
                }
            ),
            "fail",
        )
        self.assertEqual(
            commerce_status(
                pages={"/shop/": page("generic-commerce-page")}
            ),
            "fail",
        )
        self.assertEqual(
            commerce_status(
                pages={
                    "/shop/": page(
                        "generic-commerce-page",
                        route_ui=(
                            '<div class="woocommerce-shop">'
                            '<p class="woocommerce-info">'
                            "No products were found matching your selection."
                            "</p></div>"
                        ),
                    )
                }
            ),
            "fail",
        )
        self.assertEqual(
            commerce_status(
                pages={
                    "/cart/": page(
                        "woocommerce-cart",
                        robots="noindex",
                        robots_name="googlebot",
                        route_ui=(
                            '<div class="woocommerce-cart-form"></div>'
                            '<p class="cart-empty">'
                            "Your cart is currently empty."
                            "</p>"
                            '<p class="return-to-shop"></p>'
                        ),
                    )
                }
            ),
            "fail",
        )
        self.assertEqual(
            commerce_status(
                pages={
                    "/my-account/": page(
                        "woocommerce-account",
                        robots="noindex, follow",
                        route_ui=(
                            '<div class="woocommerce-form-login"></div>'
                            '<input name="username">'
                            '<input name="password">'
                        ),
                    )
                }
            ),
            "fail",
        )
        self.assertEqual(
            commerce_status(
                pages={
                    "/cart/": page(
                        "woocommerce-cart",
                        robots="noindex, follow",
                        route_ui=(
                            '<form class="woocommerce-cart-form" '
                            'action="/cart/">'
                            '<input type="hidden" name="cart[1][qty]" '
                            'value="1">'
                            '<button type="submit">Update cart</button>'
                            "</form>"
                        ),
                    )
                }
            ),
            "fail",
        )
        self.assertEqual(
            commerce_status(
                pages={
                    "/my-account/": page(
                        "woocommerce-account",
                        robots="noindex, follow",
                        route_ui=(
                            '<form class="woocommerce-form-login" action="">'
                            '<input name="username" hidden>'
                            '<input type="password" name="password" hidden>'
                            '<button type="submit">Log in</button>'
                            "</form>"
                        ),
                    )
                }
            ),
            "fail",
        )
        visible_checkout = page(
            "woocommerce-checkout",
            robots="noindex, follow",
            route_ui=(
                '<form class="checkout" method="post" action="/checkout/">'
                '<input type="hidden" '
                'name="woocommerce-process-checkout-nonce" '
                'value="a1b2c3d4e5">'
                '<input name="billing_first_name">'
                '<input name="billing_last_name">'
                '<input name="billing_address_1">'
                '<input name="billing_city">'
                '<input name="billing_postcode">'
                '<input type="email" name="billing_email">'
                '<button type="submit" id="place_order" '
                'name="woocommerce_checkout_place_order">'
                "Place order</button></form>"
            ),
        )
        self.assertEqual(
            commerce_status(checkout_page=visible_checkout),
            "pass",
        )
        hidden_checkout = page(
            "woocommerce-checkout",
            robots="noindex, follow",
            route_ui=(
                '<form class="checkout" method="post" action="/checkout/">'
                '<input type="hidden" name="billing_email">'
                '<button type="submit">Place order</button></form>'
            ),
        )
        self.assertEqual(
            commerce_status(checkout_page=hidden_checkout),
            "fail",
        )
        decoy_checkout = page(
            "woocommerce-checkout",
            robots="noindex, follow",
            route_ui=(
                '<form class="checkout" method="post" action="/checkout/">'
                '<input type="hidden" '
                'name="woocommerce-process-checkout-nonce" '
                'value="a1b2c3d4e5">'
                '<input type="search" name="search">'
                '<button type="submit">Search</button></form>'
            ),
        )
        self.assertEqual(
            commerce_status(checkout_page=decoy_checkout),
            "fail",
        )
        missing_checkout_nonce = visible_checkout.replace(
            '<input type="hidden" '
            'name="woocommerce-process-checkout-nonce" '
            'value="a1b2c3d4e5">',
            "",
        )
        self.assertEqual(
            commerce_status(checkout_page=missing_checkout_nonce),
            "fail",
        )
        self.assertEqual(commerce_status(checkout="/"), "fail")
        self.assertEqual(
            commerce_status(checkout="/cart/?decoy=1"),
            "fail",
        )
        self.assertEqual(
            commerce_status(
                pages={
                    "/cart/": page(
                        "woocommerce-cart",
                        robots="noindex, follow, index",
                    )
                }
            ),
            "fail",
        )
        self.assertEqual(
            commerce_status(
                pages={
                    "/my-account/": page(
                        "woocommerce-account",
                        robots="noindex, follow",
                        title="\u05d7\u05e9\u05d1\u05d5\u05df",
                    )
                }
            ),
            "fail",
        )

    def test_product_gate_rejects_duplicate_primary_action_scopes(self):
        def primary(title, identifier):
            return (
                '<div class="product"><div class="summary">'
                f'<h1 class="product_title">{title}</h1>'
                '<p class="stock in-stock">In stock</p>'
                + current_offer_evidence_html()
                + '<form class="cart" method="post" '
                'action="/product/reviewed-system/">'
                '<button type="submit" name="add-to-cart" '
                f'value="{identifier}">Add to cart</button>'
                "</form></div></div>"
            )

        facts = verify.parse_html(
            '<html lang="en-US"><head><title>Product</title></head>'
            '<body class="single-product"><main>'
            + primary("Reviewed system", "41")
            + primary("Duplicate primary system", "41")
            + "</main></body></html>"
        )
        surface, action, evidence = verify.product_surface_and_action(
            facts,
            product_url=(
                "https://robbottx.com/product/reviewed-system/"
            ),
            product_id=41,
        )

        self.assertFalse(surface)
        self.assertFalse(action)
        self.assertEqual(len(evidence["surface_contexts"]), 2)

        extra_action = verify.parse_html(
            '<html lang="en-US"><head><title>Product</title></head>'
            '<body class="single-product"><main>'
            + primary("Reviewed system", "41")
            + '<form class="cart" method="post" '
            'action="/product/reviewed-system/">'
            '<button type="submit" name="add-to-cart" value="41">'
            "Add to cart</button></form>"
            + "</main></body></html>"
        )
        surface, action, evidence = verify.product_surface_and_action(
            extra_action,
            product_url=(
                "https://robbottx.com/product/reviewed-system/"
            ),
            product_id=41,
        )
        self.assertTrue(surface)
        self.assertFalse(action)
        self.assertEqual(evidence["action_form_count"], 2)

    def test_browser_product_purchase_requires_complete_offer_evidence(self):
        chrome = verify.find_commerce_chrome()
        if chrome is None:
            self.skipTest("Chrome is not installed for the browser proof.")

        purchase_control = (
            '<form class="cart" method="post" '
            'action="/product/reviewed-system/">'
            '<input type="hidden" name="product_id" value="41">'
            '<button type="submit" name="add-to-cart" value="41">'
            "Add to cart</button></form>"
        )

        def product_document(offer_evidence):
            return (
                "<!doctype html><html><head><style>"
                "html,body,main,.product,.summary,form{display:block}"
                "button{display:inline-block;width:9rem;height:2rem}"
                "</style></head><body><main>"
                '<div class="product"><div class="summary">'
                '<h1 class="product_title">Reviewed system</h1>'
                '<p class="stock in-stock">In stock</p>'
                + offer_evidence
                + purchase_control
                + "</div></div></main></body></html>"
            )

        def prove(offer_evidence):
            return verify.commerce_browser_proof(
                mode="product",
                expected_path="/product/reviewed-system/",
                html=product_document(offer_evidence),
                product_id=41,
                chrome_path=chrome,
            )

        offer_clock = datetime.now(timezone.utc).replace(microsecond=0)
        valid_offer_evidence = offer_evidence_html(offer_clock)
        valid = prove(valid_offer_evidence)
        self.assertTrue(valid["passed"])
        self.assertEqual(valid["dom"]["offerEvidenceCount"], 1)
        self.assertEqual(valid["dom"]["validOfferEvidenceCount"], 1)

        valid_checked_at = offer_clock.strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        invalid_attributes = (
            valid_offer_evidence
            .replace('data-supplier="ROBOTIS"', 'data-supplier=""')
            .replace('data-region="IL"', 'data-region="ISR"')
            .replace(
                'data-quantity-basis="1 unit"',
                'data-quantity-basis="one"',
            )
            .replace(
                f'data-checked-at="{valid_checked_at}"',
                'data-checked-at="2026-07-24"',
            )
            .replace(
                f'data-offer-hash="{VALID_OFFER_HASH}"',
                f'data-offer-hash="{VALID_OFFER_HASH.upper()}"',
            )
        )
        invalid_evidence = {
            "missing_element": lambda: "",
            "invalid_attributes": lambda: invalid_attributes,
            "stale_timestamp": lambda: offer_evidence_html(
                datetime.now(timezone.utc).replace(microsecond=0)
                - timedelta(hours=24, minutes=1)
            ),
            "future_timestamp": lambda: offer_evidence_html(
                datetime.now(timezone.utc).replace(microsecond=0)
                + timedelta(minutes=10)
            ),
        }
        for case, evidence_factory in invalid_evidence.items():
            with self.subTest(case=case):
                result = prove(evidence_factory())
                self.assertTrue(result["operational"])
                self.assertFalse(result["passed"])
                self.assertEqual(
                    result["dom"]["offerEvidenceCount"],
                    0 if case == "missing_element" else 1,
                )
                self.assertEqual(
                    result["dom"]["validOfferEvidenceCount"],
                    0,
                )

    def test_browser_commerce_proof_uses_repaired_dom_and_computed_styles(
        self,
    ):
        chrome = verify.find_commerce_chrome()
        if chrome is None:
            self.skipTest("Chrome is not installed for the browser proof.")

        def product_document(action_markup, *, styles=""):
            return (
                "<!doctype html><html><head><style>"
                "html,body,main,.product,.summary,form{display:block}"
                "button{display:inline-block;width:9rem;height:2rem}"
                "input[type=image]{display:inline-block;width:9rem;height:2rem}"
                + styles
                + "</style></head><body><main>"
                '<div class="product"><div class="summary">'
                '<h1 class="product_title">Reviewed system</h1>'
                '<p class="stock in-stock">In stock</p>'
                + current_offer_evidence_html()
                + action_markup
                + "</div></div></main></body></html>"
            )

        def prove(html, *, mode="product", expected_path=None):
            return verify.commerce_browser_proof(
                mode=mode,
                expected_path=(
                    expected_path
                    or "/product/reviewed-system/"
                ),
                html=html,
                product_id=41 if mode == "product" else 0,
                chrome_path=chrome,
            )

        valid_action = (
            '<form class="cart" method="post" '
            'action="/product/reviewed-system/">'
            '<input type="hidden" name="product_id" value="41">'
            '<button type="submit" name="add-to-cart" value="41">'
            "Add to cart</button></form>"
        )
        valid = prove(product_document(valid_action))
        self.assertTrue(valid["operational"])
        self.assertTrue(valid["passed"])
        self.assertEqual(valid["dom"]["identifierCount"], 2)
        self.assertEqual(valid["dom"]["addToCartCount"], 1)
        self.assertEqual(valid["dom"]["offerEvidenceCount"], 1)
        self.assertEqual(valid["dom"]["positiveStockCount"], 1)
        self.assertEqual(valid["dom"]["validOfferEvidenceCount"], 1)

        extra_action = product_document(valid_action).replace(
            "</main>",
            (
                '<form class="cart" method="post" '
                'action="/product/reviewed-system/">'
                '<button type="submit" name="add-to-cart" value="41">'
                "Add to cart</button></form></main>"
            ),
        )
        self.assertFalse(prove(extra_action)["passed"])

        product_id_only = valid_action.replace(
            ' name="add-to-cart" value="41"',
            "",
        )
        self.assertFalse(prove(product_document(product_id_only))["passed"])

        image_identifier = (
            '<form class="cart" method="post" '
            'action="/product/reviewed-system/">'
            '<input type="image" name="add-to-cart" value="41" '
            'alt="Add to cart"></form>'
        )
        self.assertFalse(prove(product_document(image_identifier))["passed"])

        hidden_trigger_with_image = (
            '<form class="cart" method="post" '
            'action="/product/reviewed-system/">'
            '<input type="hidden" name="add-to-cart" value="41">'
            '<input type="image" alt="Add to cart"></form>'
        )
        self.assertTrue(
            prove(product_document(hidden_trigger_with_image))["passed"]
        )

        conflicting_identifier = valid_action.replace(
            '<input type="hidden" name="product_id" value="41">',
            '<input type="hidden" name="product_id" value="42">',
        )
        self.assertFalse(
            prove(product_document(conflicting_identifier))["passed"]
        )

        disabled_identifier = valid_action.replace(
            '<input type="hidden" name="product_id" value="41">',
            (
                '<input type="hidden" name="product_id" '
                'value="41" disabled>'
            ),
        )
        self.assertFalse(
            prove(product_document(disabled_identifier))["passed"]
        )

        duplicate_action = valid_action.replace(
            'action="/product/reviewed-system/"',
            (
                'action="https://example.com/decoy/" '
                'action="/product/reviewed-system/"'
            ),
        )
        self.assertFalse(prove(product_document(duplicate_action))["passed"])

        form_override = (
            '<form id="other" method="post" action="/other/"></form>'
            '<form class="cart" method="post" '
            'action="/product/reviewed-system/">'
            '<input type="hidden" name="product_id" value="41" form="other">'
            '<button type="submit" name="add-to-cart" '
            'value="41" form="other">Add to cart</button></form>'
        )
        self.assertFalse(prove(product_document(form_override))["passed"])

        nested_form = (
            '<form class="cart" method="post" '
            'action="/product/reviewed-system/">'
            '<form id="inner"></form>'
            '<input type="hidden" name="product_id" value="41">'
            '<button type="submit" name="add-to-cart" value="41">'
            "Add to cart</button></form>"
        )
        self.assertFalse(prove(product_document(nested_form))["passed"])

        disabled_fieldset = (
            '<form class="cart" method="post" '
            'action="/product/reviewed-system/"><fieldset disabled>'
            '<input type="hidden" name="product_id" value="41">'
            '<button type="submit" name="add-to-cart" value="41">'
            "Add to cart</button></fieldset></form>"
        )
        self.assertFalse(
            prove(product_document(disabled_fieldset))["passed"]
        )

        first_legend = (
            '<form class="cart" method="post" '
            'action="/product/reviewed-system/"><fieldset disabled>'
            "<legend>"
            '<input type="hidden" name="product_id" value="41">'
            '<button type="submit" name="add-to-cart" value="41">'
            "Add to cart</button></legend>"
            '<button type="button">Disabled decoy</button>'
            "</fieldset></form>"
        )
        self.assertTrue(prove(product_document(first_legend))["passed"])

        self.assertFalse(
            prove(
                product_document(
                    valid_action,
                    styles=".summary{filter:opacity(0%)}",
                )
            )["passed"]
        )
        for invalid_stock in (
            '<p class="stock in-stock">Out of stock</p>',
            '<p class="stock in-stock">Sold out</p>',
            (
                '<p class="stock available-on-backorder">'
                "Unavailable</p>"
            ),
            (
                '<p class="stock in-stock">In stock</p>'
                '<p class="stock out-of-stock">Out of stock</p>'
            ),
        ):
            with self.subTest(browser_stock=invalid_stock):
                self.assertFalse(
                    prove(
                        product_document(valid_action).replace(
                            '<p class="stock in-stock">In stock</p>',
                            invalid_stock,
                        )
                    )["passed"]
                )

        for concealment in (
            ".product{clip-path:inset(100% 0 0 0)}",
            ".product{clip-path:polygon(0 0,0 0,0 0)}",
            ".product{clip-path:circle(.1px)}",
            (
                ".product{mask-image:"
                "linear-gradient(transparent,transparent)}"
            ),
            (
                ".summary{width:1px;height:1px;"
                "overflow:hidden}"
            ),
            ".product{position:fixed;top:10000px}",
            ".product{transform:translateY(10000px)}",
            ".product{transform:translateY(-10000px)}",
        ):
            with self.subTest(concealment=concealment):
                self.assertFalse(
                    prove(
                        product_document(
                            valid_action,
                            styles=concealment,
                        )
                    )["passed"]
                )

        self.assertTrue(
            prove(
                product_document(
                    valid_action,
                    styles=".product{margin-top:120vh}",
                )
            )["passed"]
        )

        covered_product = product_document(valid_action).replace(
            "</main></body>",
            (
                "</main><div style=\"position:fixed;inset:0;"
                "z-index:99999;background:white\"></div></body>"
            ),
        )
        self.assertFalse(prove(covered_product)["passed"])
        pointer_transparent_cover = covered_product.replace(
            'z-index:99999;background:white"',
            'z-index:99999;background:white;pointer-events:none"',
        )
        self.assertFalse(prove(pointer_transparent_cover)["passed"])
        self.assertFalse(
            prove(
                product_document(
                    valid_action,
                    styles=(
                        "body::before{content:'Service unavailable';"
                        "pointer-events:none;position:fixed;inset:0;"
                        "z-index:999999;background:#fff;color:#000;"
                        "font-size:48px}"
                    ),
                )
            )["passed"]
        )
        self.assertTrue(
            prove(
                product_document(
                    valid_action,
                    styles=(
                        ".product_title::after{content:'';position:absolute;"
                        "width:4px;height:4px;z-index:2;background:#111}"
                    ),
                )
            )["passed"]
        )
        transparent_blocker = covered_product.replace(
            "background:white",
            "background:transparent;pointer-events:auto",
        )
        self.assertFalse(prove(transparent_blocker)["passed"])
        self.assertFalse(
            prove(
                product_document(
                    valid_action,
                    styles="form.cart{position:absolute;left:200vw}",
                )
            )["passed"]
        )
        self.assertFalse(
            prove(
                product_document(
                    valid_action,
                    styles=".product{opacity:.1}.summary{opacity:.1}",
                )
            )["passed"]
        )
        self.assertTrue(
            prove(
                product_document(
                    valid_action,
                    styles=(
                        "@keyframes tint{from{color:#111}to{color:#333}}"
                        ".product_title{animation:tint 1s infinite}"
                    ),
                )
            )["passed"]
        )
        self.assertFalse(
            prove(
                product_document(
                    valid_action,
                    styles="form.cart{position:absolute;top:-10000px}",
                )
            )["passed"]
        )

        shop = (
            "<!doctype html><html><head><style>"
            "li,a,span{display:block}a,span{width:8rem;height:2rem}"
            "</style></head><body><ul class=\"products\">"
            '<li class="product"><a href="/product/one/">One</a></li>'
            '<li class="product"><span>Missing link</span></li>'
            "</ul></body></html>"
        )
        self.assertFalse(
            prove(
                shop,
                mode="shop",
                expected_path="/shop/",
            )["passed"]
        )

    def test_browser_commerce_proof_requires_canonical_route_controls(self):
        chrome = verify.find_commerce_chrome()
        if chrome is None:
            self.skipTest("Chrome is not installed for the browser proof.")

        def document(body, *, styles=""):
            return (
                "<!doctype html><html><head><style>"
                "form,.cart_item,input,button{display:block}"
                "input,button{width:12rem;height:2rem}"
                + styles
                + "</style></head><body>"
                + body
                + "</body></html>"
            )

        def prove(mode, path, body, *, styles=""):
            return verify.commerce_browser_proof(
                mode=mode,
                expected_path=path,
                html=document(body, styles=styles),
                product_id=0,
                chrome_path=chrome,
            )

        account = (
            '<form class="woocommerce-form-login" method="post" action="">'
            '<input type="hidden" name="woocommerce-login-nonce" '
            'value="a1b2c3d4e5">'
            '<input name="username"><input type="password" name="password">'
            '<button type="submit" name="login" value="Log in">'
            "Log in</button></form>"
        )
        self.assertTrue(prove("account", "/my-account/", account)["passed"])
        self.assertFalse(
            prove(
                "account",
                "/my-account/",
                account.replace(' name="login"', ""),
            )["passed"]
        )
        self.assertFalse(
            prove(
                "account",
                "/my-account/",
                account.replace('<input name="username"', (
                    '<input name="username" readonly'
                )),
            )["passed"]
        )
        self.assertFalse(
            prove(
                "account",
                "/my-account/",
                account,
                styles=(
                    "input[name=username],input[name=password]{"
                    "appearance:none;border:0;outline:0;background:#fff}"
                ),
            )["passed"]
        )
        self.assertFalse(
            prove(
                "account",
                "/my-account/",
                account,
                styles="input[name=username]:focus{display:none}",
            )["passed"]
        )

        cart = (
            '<form class="woocommerce-cart-form" method="post" action="/cart/">'
            '<input type="hidden" name="woocommerce-cart-nonce" '
            'value="a1b2c3d4e5">'
            '<div class="cart_item">'
            '<input type="number" name="cart[abc][qty]" value="1"></div>'
            '<button type="submit" name="update_cart" value="Update cart">'
            "Update cart</button></form>"
        )
        self.assertTrue(prove("cart", "/cart/", cart)["passed"])
        self.assertFalse(
            prove(
                "cart",
                "/cart/",
                cart.replace(' class="cart_item"', ""),
            )["passed"]
        )
        self.assertFalse(
            prove(
                "cart",
                "/cart/",
                cart.replace(' name="update_cart"', ""),
            )["passed"]
        )

        checkout_fields = (
            '<input name="billing_first_name">'
            '<input name="billing_last_name">'
            '<input name="billing_address_1">'
            '<input name="billing_city">'
            '<input name="billing_postcode">'
            '<input type="email" name="billing_email">'
        )
        checkout = (
            '<form class="checkout" method="post" action="/checkout/">'
            '<input type="hidden" '
            'name="woocommerce-process-checkout-nonce" '
            'value="a1b2c3d4e5">'
            + checkout_fields
            + '<button type="submit" id="place_order" '
            'name="woocommerce_checkout_place_order" value="Place order">'
            "Place order</button></form>"
        )
        self.assertTrue(prove("checkout", "/checkout/", checkout)["passed"])
        self.assertFalse(
            prove(
                "checkout",
                "/checkout/",
                checkout.replace(
                    checkout_fields,
                    '<input name="order_comments">',
                ),
            )["passed"]
        )
        self.assertFalse(
            prove(
                "checkout",
                "/checkout/",
                checkout.replace(' id="place_order"', ""),
            )["passed"]
        )

    def test_browser_commerce_helper_cleans_profiles_on_failures(self):
        chrome = verify.find_commerce_chrome()
        if chrome is None:
            self.skipTest("Chrome is not installed for the browser proof.")
        helper = ROOT / "tools" / "qa" / "verify-commerce-dom.mjs"
        node = verify.shutil.which("node")
        self.assertIsNotNone(node)
        payload = json.dumps(
            {
                "mode": "account",
                "html": (
                    "<!doctype html><html><body>"
                    '<form class="woocommerce-form-login" '
                    'method="post" action="">'
                    '<input name="username">'
                    '<input type="password" name="password">'
                    '<button type="submit">Log in</button>'
                    "</form></body></html>"
                ),
                "expectedOrigin": "https://robbottx.com",
                "expectedPath": "/my-account/",
            }
        )

        with tempfile.TemporaryDirectory() as temporary:
            profile_root = Path(temporary)
            environment = {
                **os.environ,
                "NODE_ENV": "test",
                "ROBBOTTX_COMMERCE_PROOF_PROFILE_ROOT": str(profile_root),
            }
            launch_failure = subprocess.run(
                [
                    node,
                    str(helper),
                    "--chrome",
                    sys.executable,
                ],
                input=payload,
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=environment,
                timeout=30,
                check=False,
            )
            self.assertEqual(launch_failure.returncode, 1)
            self.assertFalse(json.loads(launch_failure.stdout)["operational"])
            self.assertEqual(list(profile_root.iterdir()), [])

            with tempfile.TemporaryDirectory(
                prefix=verify.COMMERCE_BROWSER_PROFILE_PREFIX,
                dir=profile_root.parent,
            ) as unsafe_profile:
                unsafe_profile_path = Path(unsafe_profile).resolve()
                unsafe_profile_result = subprocess.run(
                    [
                        node,
                        str(helper),
                        "--chrome",
                        str(chrome),
                        "--profile",
                        str(unsafe_profile_path),
                    ],
                    input=payload,
                    text=True,
                    encoding="utf-8",
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    env=environment,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(unsafe_profile_result.returncode, 1)
                self.assertEqual(
                    json.loads(
                        unsafe_profile_result.stdout
                    )["failureCodes"],
                    ["invalid_arguments"],
                )
                self.assertTrue(unsafe_profile_path.is_dir())

            environment[
                "ROBBOTTX_COMMERCE_PROOF_TEST_DELAY_MS"
            ] = "1000"
            forced_timeout = subprocess.run(
                [
                    node,
                    str(helper),
                    "--chrome",
                    str(chrome),
                    "--operation-timeout-ms",
                    "50",
                ],
                input=payload,
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=environment,
                timeout=30,
                check=False,
            )
            forced_payload = json.loads(forced_timeout.stdout)
            self.assertEqual(forced_timeout.returncode, 1)
            self.assertIn(
                "operation_timeout",
                forced_payload["failureCodes"],
            )
            self.assertEqual(list(profile_root.iterdir()), [])

    def test_browser_commerce_outer_watchdog_removes_owned_profile(self):
        chrome = verify.find_commerce_chrome()
        if chrome is None:
            self.skipTest("Chrome is not installed for the browser proof.")
        profile = Path(
            tempfile.mkdtemp(
                prefix=verify.COMMERCE_BROWSER_PROFILE_PREFIX,
            )
        ).resolve()
        environment = verify.commerce_browser_helper_environment()
        environment.update(
            {
                "NODE_ENV": "test",
                "ROBBOTTX_COMMERCE_PROOF_TEST_DELAY_MS": "30000",
            }
        )
        payload = json.dumps(
            {
                "mode": "account",
                "html": (
                    "<!doctype html><html><body>"
                    '<form class="woocommerce-form-login" '
                    'method="post" action="">'
                    '<input type="hidden" '
                    'name="woocommerce-login-nonce" '
                    'value="a1b2c3d4e5">'
                    '<input name="username">'
                    '<input type="password" name="password">'
                    '<button type="submit">Log in</button>'
                    "</form></body></html>"
                ),
                "expectedOrigin": "https://robbottx.com",
                "expectedPath": "/my-account/",
            }
        )
        try:
            with (
                patch.object(
                    verify.tempfile,
                    "mkdtemp",
                    return_value=str(profile),
                ),
                patch.object(
                    verify,
                    "commerce_browser_helper_environment",
                    return_value=environment,
                ),
                patch.object(
                    verify,
                    "COMMERCE_BROWSER_TIMEOUT_SECONDS",
                    2,
                ),
            ):
                result = verify._run_commerce_browser_helper(
                    mode="account",
                    source="fixture",
                    expected_path="/my-account/",
                    input_json=payload,
                    chrome_path=str(chrome),
                )
            self.assertFalse(result["operational"])
            self.assertEqual(result["failureCodes"], ["operation_timeout"])
            self.assertFalse(profile.exists())
        finally:
            if profile.exists():
                verify.remove_owned_commerce_browser_profile(profile)

    def test_browser_commerce_result_schema_bounds_checkout_redirect(self):
        redirect_result = {
            "schemaVersion": "1.0",
            "operational": True,
            "passed": True,
            "mode": "checkout",
            "source": "live",
            "routeUi": "empty_cart_redirect",
            "failureCodes": [],
            "navigation": {
                "status": 200,
                "redirectStatus": 302,
                "finalOrigin": "https://robbottx.com",
                "finalPath": "/cart/",
                "redirectCount": 1,
            },
            "stylesheets": {
                "externalCount": 13,
                "loadedCount": 13,
                "failedCount": 0,
                "blockedCount": 0,
            },
            "dom": {
                "cartFormCount": 0,
                "dataInputCount": 0,
                "submitCount": 0,
            },
        }
        self.assertTrue(
            verify.valid_commerce_browser_result(
                redirect_result,
                mode="checkout",
                source="live",
                expected_path="/checkout/",
            )
        )

        wrong_redirect = json.loads(json.dumps(redirect_result))
        wrong_redirect["navigation"]["redirectStatus"] = 301
        self.assertFalse(
            verify.valid_commerce_browser_result(
                wrong_redirect,
                mode="checkout",
                source="live",
                expected_path="/checkout/",
            )
        )

        leaked_body = json.loads(json.dumps(redirect_result))
        leaked_body["body"] = "<html>not allowlisted</html>"
        self.assertFalse(
            verify.valid_commerce_browser_result(
                leaked_body,
                mode="checkout",
                source="live",
                expected_path="/checkout/",
            )
        )

    def _active_commerce_rejects_duplicate_checkout_locations(self):
        def fake_fetch(url, **kwargs):
            path = verify.urllib.parse.urlsplit(url).path
            if path.startswith("/wp-content/plugins/woocommerce/"):
                return self.http_result(
                    200,
                    "body{display:block}",
                    content_type="text/css; charset=UTF-8",
                    final_url=url,
                )
            if path == "/checkout/":
                return self.http_result(
                    302,
                    headers={
                        "location": ["/cart/", "/cart/?second=1"]
                    },
                    content_type="text/html; charset=UTF-8",
                    final_url=url,
                )
            body_class = {
                "/shop/": "woocommerce-shop",
                "/cart/": "woocommerce-cart",
                "/my-account/": "woocommerce-account",
            }[path]
            robots = (
                ""
                if path == "/shop/"
                else '<meta name="robots" content="noindex, follow">'
            )
            ui = {
                "/shop/": (
                    '<p class="woocommerce-info">'
                    "No products were found matching your selection.</p>"
                ),
                "/cart/": (
                    '<p class="cart-empty">Your cart is currently empty.'
                    '</p><p class="return-to-shop">'
                    '<a href="/shop/">Return</a></p>'
                ),
                "/my-account/": (
                    '<form class="woocommerce-form-login" action="">'
                    '<input name="username"><input name="password">'
                    '<button type="submit">Log in</button></form>'
                ),
            }[path]
            return self.http_result(
                200,
                (
                    '<html lang="en-US"><head><title>Commerce</title>'
                    + robots
                    + '<link rel="stylesheet" href="/wp-content/plugins/'
                    'woocommerce/assets/store.css"></head><body class="'
                    + body_class
                    + '"><main><h1>Commerce</h1>'
                    + ui
                    + "</main></body></html>"
                ),
                content_type="text/html; charset=UTF-8",
                final_url=url,
            )

        report = verify.Report(
            plugin_version="0.1.5",
            previous_plugin_version="0.1.4",
            theme_version="0.1.4",
            record_hash="a" * 64,
            expect_fallback_favicon=True,
        )
        with (
            patch.object(verify, "fetch", side_effect=fake_fetch),
            patch.object(
                verify,
                "commerce_browser_proof",
                return_value={
                    "passed": True,
                    "routeUi": "empty_cart_redirect",
                },
            ),
        ):
            verify.verify_commerce(report)
        self.assertEqual(report.checks[-1].status, "fail")

    def test_robots_checks_major_crawlers_and_every_advertised_sitemap(self):
        sitemap = (
            '<?xml version="1.0"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://robbottx.com/</loc></url></urlset>"
        )

        def status_for(robots_text):
            def fake_fetch(url, **kwargs):
                path = verify.urllib.parse.urlsplit(url).path
                if path == "/robots.txt":
                    return self.http_result(
                        200,
                        robots_text,
                        content_type="text/plain; charset=UTF-8",
                        final_url=url,
                    )
                if path == "/wp-sitemap.xml":
                    return self.http_result(
                        200,
                        sitemap,
                        content_type="application/xml; charset=UTF-8",
                        final_url=url,
                    )
                return self.http_result(
                    404,
                    "missing",
                    content_type="text/plain; charset=UTF-8",
                    final_url=url,
                )

            report = verify.Report(
                plugin_version="0.1.5",
                previous_plugin_version="0.1.4",
                theme_version="0.1.4",
                record_hash="a" * 64,
                expect_fallback_favicon=True,
            )
            with patch.object(verify, "fetch", side_effect=fake_fetch):
                verify.verify_robots(report)
            return report.checks[-1].status

        allowed = (
            "User-agent: *\nDisallow:\n"
            "Sitemap: https://robbottx.com/wp-sitemap.xml\n"
        )
        self.assertEqual(status_for(allowed), "pass")
        for crawler in verify.SEARCH_CRAWLERS:
            if crawler == "*":
                continue
            with self.subTest(crawler=crawler):
                self.assertEqual(
                    status_for(
                        "User-agent: *\nDisallow:\n"
                        f"User-agent: {crawler}\nDisallow: /\n"
                        "Sitemap: https://robbottx.com/wp-sitemap.xml\n"
                    ),
                    "fail",
                )
        self.assertEqual(
            status_for(
                allowed
                + "Sitemap: https://robbottx.com/missing-sitemap.xml\n"
            ),
            "fail",
        )
        for public_path in ("/shop/", "/product/"):
            with self.subTest(public_path=public_path):
                self.assertEqual(
                    status_for(
                        "User-agent: *\n"
                        "Allow: /\n"
                        f"Disallow: {public_path}\n"
                        "Sitemap: "
                        "https://robbottx.com/wp-sitemap.xml\n"
                    ),
                    "fail",
                )

    def test_warm_cache_identity_rejects_stale_rendered_release(self):
        def identity_status(marker):
            html = (
                '<html lang="en-US"><head><title>'
                + verify.HOME_DOCUMENT_TITLE
                + "</title></head><body><main><h1>RobbottX</h1></main>"
                + f"<!-- robbottx-core:{marker} -->"
                + "</body></html>"
            )
            response = self.http_result(
                200,
                html,
                content_type="text/html; charset=UTF-8",
                final_url="https://robbottx.com/",
            )
            report = verify.Report(
                plugin_version="0.1.5",
                previous_plugin_version="0.1.4",
                theme_version="0.1.4",
                record_hash="a" * 64,
                expect_fallback_favicon=True,
            )
            with patch.object(verify, "fetch", return_value=response):
                verify.verify_performance(report, 3)
            return next(
                item.status
                for item in report.checks
                if item.check_id == "runtime.warm_cache_identity"
            )

        self.assertEqual(identity_status("0.1.5"), "pass")
        self.assertEqual(identity_status("0.1.4"), "fail")

    def test_report_distinguishes_hard_failures_and_warnings(self):
        report = verify.Report(
            plugin_version="0.1.5",
            previous_plugin_version="0.1.4",
            theme_version="0.1.4",
            record_hash="a" * 64,
            expect_fallback_favicon=True,
        )
        report.add("pass", True, "passed")
        report.add("warning", False, "warning", warning=True)
        warning_payload = report.payload()
        self.assertEqual(
            warning_payload["status"],
            "BLOCKED_BY_WARNINGS",
        )
        accepted_payload = report.payload(
            {
                "warning": {
                    "owner": "Release owner",
                    "decision": "Accept this measured release variance.",
                }
            }
        )
        self.assertEqual(
            accepted_payload["status"],
            "PASS_WITH_ACCEPTED_WARNINGS",
        )

        report.add("failure", False, "failed")
        failed_payload = report.payload()
        self.assertEqual(failed_payload["status"], "FAIL")
        self.assertEqual(failed_payload["summary"]["failed"], 1)

    def test_json_output_contains_no_response_body_field(self):
        report = verify.Report(
            plugin_version="0.1.5",
            previous_plugin_version="0.1.4",
            theme_version="0.1.4",
            record_hash="a" * 64,
            expect_fallback_favicon=True,
        )
        report.add(
            "safe",
            True,
            "safe evidence",
            evidence={"http_status": 200},
        )
        encoded = json.dumps(report.payload())
        self.assertNotIn('"body"', encoded)

    def test_atomic_output_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receipt.json"
            verify.write_new_atomic(output, '{"status":"PASS"}\n')
            self.assertEqual(
                output.read_text(encoding="utf-8"),
                '{"status":"PASS"}\n',
            )
            with self.assertRaises(FileExistsError):
                verify.write_new_atomic(output, "replacement")


if __name__ == "__main__":
    unittest.main()
