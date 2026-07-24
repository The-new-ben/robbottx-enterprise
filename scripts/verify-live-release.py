#!/usr/bin/env python3
"""Verify a published RobbottX release through unauthenticated HTTPS."""

from __future__ import annotations

import argparse
import functools
import io
import json
import math
import os
import re
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

try:
    from PIL import Image as PillowImage
except ImportError:
    PillowImage = None


EXPECTED_ORIGIN = "https://robbottx.com"
USER_AGENT = "RobbottX-Live-Verification/0.1"
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
HOME_DESCRIPTION = (
    "Explore robotics systems, components, software, compatibility records, "
    "and technical documents with RobbottX."
)
HOME_SOCIAL_TITLE = "RobbottX: Robotics systems mapped to evidence"
HOME_DOCUMENT_TITLE = "RobbottX \u2013 Robotics systems mapped to evidence"
EXPECTED_RECORD_ID = "RBTX:E:019f8f7d-9588-7709-b78b-a1b135c09915"
EXPECTED_REVIEW_DATE = "2026-07-23"
EXPECTED_CONFIGURATION_NAME = (
    "TurtleBot3 Waffle Pi + OpenMANIPULATOR-X"
)
EXPECTED_SPECIFICATION_COUNT = 9
EXPECTED_SOURCE_COUNT = 5
SITEMAP_NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"
SEARCH_CRAWLERS = (
    "*",
    "amazonbot",
    "amzn-searchbot",
    "amzn-user",
    "applebot",
    "applebot-extended",
    "baiduspider",
    "bingbot",
    "chatgpt-user",
    "claudebot",
    "claude-searchbot",
    "claude-user",
    "duckduckbot",
    "google-cloudvertexbot",
    "google-extended",
    "google-inspectiontool",
    "googlebot",
    "googlebot-image",
    "googlebot-news",
    "googlebot-video",
    "googleother",
    "googleother-image",
    "googleother-video",
    "gptbot",
    "oai-adsbot",
    "oai-searchbot",
    "perplexitybot",
    "perplexity-user",
    "storebot-google",
    "yandexbot",
)
PUBLIC_ROBOTS_PATHS = ("/", "/shop/", "/product/")
COMMERCE_BROWSER_SCHEMA_VERSION = "1.0"
COMMERCE_BROWSER_PROFILE_PREFIX = "robbottx-commerce-browser-"
# The helper owns a 45-second operation deadline and a 15-second cleanup
# deadline. Keep a 15-second caller margin so Node can always run its finally
# cleanup before the process-tree fallback is used.
COMMERCE_BROWSER_TIMEOUT_SECONDS = 75
CLASSIC_JAVASCRIPT_MIME_TYPES = frozenset(
    {
        "",
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
    }
)
JAVASCRIPT_RESPONSE_MEDIA_TYPES = CLASSIC_JAVASCRIPT_MIME_TYPES - {""}
COMMERCE_BROWSER_FAILURE_CODES = frozenset(
    {
        "account_surface",
        "browser_error",
        "cart_surface",
        "checkout_surface",
        "cleanup_failed",
        "evaluation_timeout",
        "fixture_external_stylesheet",
        "fixture_timeout",
        "input_too_large",
        "invalid_arguments",
        "invalid_fixture_html",
        "invalid_input",
        "invalid_live_url",
        "invalid_product_id",
        "invalid_result",
        "invalid_source",
        "navigation",
        "navigation_timeout",
        "operation_timeout",
        "product_action",
        "product_surface",
        "shop_surface",
        "stylesheet_blocked",
        "stylesheet_failed",
        "unexpected_product_id",
    }
)
COMMERCE_BROWSER_DOM_KEYS = frozenset(
    {
        "actionFormCount",
        "addToCartCount",
        "cartFormCount",
        "checkoutFormCount",
        "dataInputCount",
        "identifierCount",
        "loginFormCount",
        "offerEvidenceCount",
        "passwordCount",
        "primaryActionCount",
        "primarySurfaceCount",
        "positiveStockCount",
        "productCardCount",
        "productLinkCount",
        "stockCount",
        "submitCount",
        "titleCount",
        "usernameCount",
        "validOfferEvidenceCount",
    }
)

LEGACY_HTML_PATHS = (
    "/hello-world/",
    "/sample-page/",
    "/robots-catalog/",
    "/robots/",
    "/category/uncategorized/",
    "/author/robojcht_admin/",
    "/robot/optimusa%c2%80%c2%91v5-tesla/",
    "/robot/homematea-x-samsung-robotics/",
    "/robot/sophiaa-2035-hanson-robotics/",
    "/robot/agrobota-alpha-agrotech-dynamics/",
    "/robot/knightscopea-k50-knightscope/",
    "/robot/marsrovera-quantum-nasaa-jpl/",
)

LEGACY_REST_DETAILS = (
    "/wp-json/wp/v2/robot/8",
    "/wp-json/wp/v2/robot/9",
    "/wp-json/wp/v2/robot/10",
    "/wp-json/wp/v2/robot/11",
    "/wp-json/wp/v2/robot/12",
    "/wp-json/wp/v2/robot/13",
    "/wp-json/wp/v2/posts/1",
    "/wp-json/wp/v2/pages/2",
    "/wp-json/wp/v2/pages/25",
    "/wp-json/wp/v2/pages/29",
    "/wp-json/wp/v2/pages/30",
    "/wp-json/wp/v2/pages/31",
    "/wp-json/wp/v2/pages/32",
    "/wp-json/wp/v2/categories/1",
    "/wp-json/wp/v2/users/1",
)

LEGACY_REST_COLLECTIONS = (
    "/wp-json/wp/v2/robot?per_page=100&_fields=id,slug,link",
    "/wp-json/wp/v2/posts?slug=hello-world&_fields=id,slug,link",
    "/wp-json/wp/v2/pages?slug=sample-page&_fields=id,slug,link",
    "/wp-json/wp/v2/pages?slug=robots-catalog&_fields=id,slug,link",
    "/wp-json/wp/v2/pages?slug=shop&_fields=id,slug,link",
    "/wp-json/wp/v2/pages?slug=cart&_fields=id,slug,link",
    "/wp-json/wp/v2/pages?slug=checkout&_fields=id,slug,link",
    "/wp-json/wp/v2/pages?slug=my-account&_fields=id,slug,link",
    "/wp-json/wp/v2/product?per_page=100&_fields=id,slug,link",
    "/wp-json/wp/v2/categories?slug=uncategorized&_fields=id,slug,link",
    "/wp-json/wp/v2/users?per_page=100&_fields=id,slug,link",
)

COMMERCE_PATHS = (
    ("/shop/", (200,)),
    ("/cart/", (200,)),
    ("/my-account/", (200,)),
    ("/checkout/", (200, 301, 302, 303, 307, 308)),
)
INACTIVE_COMMERCE_PATHS = (
    "/shop/",
    "/cart/",
    "/checkout/",
    "/my-account/",
)
INACTIVE_COMMERCE_NORMALIZED_PATHS = frozenset(
    path.rstrip("/")
    for path in INACTIVE_COMMERCE_PATHS
)
INACTIVE_STORE_API_PATH = "/wp-json/wc/store/v1/products"
INACTIVE_PRODUCT_TAXONOMY_COLLECTIONS = (
    (
        "/wp-json/wp/v2/product_cat"
        "?per_page=100&_fields=id,slug,link"
    ),
    (
        "/wp-json/wp/v2/product_tag"
        "?per_page=100&_fields=id,slug,link"
    ),
)
INACTIVE_PRODUCT_SITEMAP_MARKERS = (
    "posts-product-",
    "product-category",
    "product-sitemap",
    "product-tag",
    "product_cat-sitemap",
    "product_tag-sitemap",
    "taxonomies-product_cat",
    "taxonomies-product_tag",
)

SEARCH_TERMS = (
    "hello world",
    "sample page",
    "robots catalog",
    "optimus v5",
    "homemate x",
    "sophia 2035",
    "agrobot alpha",
    "knightscope k50",
    "marsrover quantum",
    "shop",
    "cart",
    "checkout",
    "my account",
    "product",
)

FEED_PATHS = (
    "/feed/",
    "/robots/feed/",
    "/category/uncategorized/feed/",
    "/author/robojcht_admin/feed/",
)

LEGACY_TITLE_FRAGMENTS = (
    "hello world",
    "sample page",
    "robots catalog",
    "optimus v5",
    "homemate x",
    "sophia 2035",
    "agrobot alpha",
    "knightscope k50",
    "marsrover quantum",
)

FORBIDDEN_PUBLIC_PATTERNS = (
    ("em dash", re.compile("\u2014")),
    ("golden vertical slice", re.compile(r"\bgolden vertical slice\b", re.I)),
    ("research candidate", re.compile(r"\bresearch candidate\b", re.I)),
    ("publication gate", re.compile(r"\bpublication gate\b", re.I)),
    ("projection state", re.compile(r"\bprojection state\b", re.I)),
    ("snapshot vocabulary", re.compile(r"\bsnapshot(?: id)?\b", re.I)),
    ("canonical identifier", re.compile(r"\bcanonical id\b", re.I)),
    ("assertion vocabulary", re.compile(r"\bassertions?\b", re.I)),
    ("engineering closure", re.compile(r"\bengineering closure\b", re.I)),
    ("open item vocabulary", re.compile(r"\bopen items?\b", re.I)),
    ("prompt vocabulary", re.compile(r"\bprompts?\b", re.I)),
    ("pipeline vocabulary", re.compile(r"\bdata pipeline\b", re.I)),
    (
        "unfinished platform language",
        re.compile(
            r"\b(?:beta|preview|planned|roadmap|coming soon|launching soon|"
            r"work in progress|in the works|on the horizon|"
            r"something big is brewing|evolving project)\b",
            re.I,
        ),
    ),
    (
        "formulaic generated language",
        re.compile(
            r"\b(?:at its core|in today'?s landscape|unlock|delve|"
            r"revolutionary|game-changing)\b",
            re.I,
        ),
    ),
    (
        "mixed Hebrew interface language",
        re.compile(r"[\u0590-\u05ff]"),
    ),
)


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request_object,
        file_pointer,
        code,
        message,
        headers,
        new_url,
    ):
        return None


NO_REDIRECTS = urllib.request.build_opener(NoRedirectHandler())


@dataclass(frozen=True)
class HttpResult:
    status: int
    content_type: str
    headers: dict[str, str]
    body: bytes
    final_url: str
    header_seconds: float
    total_seconds: float
    header_values: dict[str, list[str]] = field(default_factory=dict)

    def values(self, name: str) -> list[str]:
        return list(self.header_values.get(name.lower(), []))

    def single_header(self, name: str) -> str | None:
        values = self.values(name)
        if len(values) > 1:
            raise ValueError(
                f"Response contains repeated {name.lower()} headers."
            )
        return values[0] if values else None

    def text(self) -> str:
        if len(self.values("content-type")) != 1:
            raise ValueError(
                "Response must contain exactly one Content-Type header."
            )
        charset = "utf-8"
        for parameter in self.content_type.split(";")[1:]:
            name, separator, value = parameter.partition("=")
            if separator and name.strip().lower() == "charset":
                charset = value.strip().strip("\"'").lower()
        if charset in {"utf8", "utf-8"}:
            charset = "utf-8"
        elif charset in {"ascii", "us-ascii"}:
            charset = "ascii"
        else:
            raise ValueError("Response uses an unsupported character set.")
        return self.body.decode(charset, errors="strict")


@dataclass(frozen=True)
class Check:
    check_id: str
    status: str
    summary: str
    evidence: dict[str, Any]


class Report:
    def __init__(
        self,
        *,
        plugin_version: str,
        theme_version: str,
        record_hash: str,
        expect_fallback_favicon: bool,
        previous_plugin_version: str,
        configured_site_icon_urls: tuple[str, ...] = (),
    ) -> None:
        self.plugin_version = plugin_version
        self.theme_version = theme_version
        self.record_hash = record_hash.lower()
        self.expect_fallback_favicon = expect_fallback_favicon
        self.previous_plugin_version = previous_plugin_version
        self.configured_site_icon_urls = configured_site_icon_urls
        self.checks: list[Check] = []

    def add(
        self,
        check_id: str,
        passed: bool,
        summary: str,
        *,
        evidence: dict[str, Any] | None = None,
        warning: bool = False,
    ) -> None:
        status = "pass" if passed else ("warning" if warning else "fail")
        self.checks.append(
            Check(
                check_id=check_id,
                status=status,
                summary=summary,
                evidence=evidence or {},
            )
        )

    def exception(
        self,
        check_id: str,
        summary: str,
        error: Exception,
        *,
        warning: bool = False,
    ) -> None:
        self.add(
            check_id,
            False,
            summary,
            evidence={"error_type": type(error).__name__},
            warning=warning,
        )

    def payload(
        self,
        warning_decisions: dict[str, dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        warning_decisions = warning_decisions or {}
        counts = Counter(check.status for check in self.checks)
        warning_ids = {
            check.check_id
            for check in self.checks
            if check.status == "warning"
        }
        unknown_decisions = sorted(set(warning_decisions) - warning_ids)
        if unknown_decisions:
            raise ValueError(
                "Warning decisions reference checks that are not warnings."
            )
        unaccepted_warnings = sorted(
            warning_ids - set(warning_decisions)
        )
        if counts["fail"]:
            status = "FAIL"
        elif unaccepted_warnings:
            status = "BLOCKED_BY_WARNINGS"
        elif warning_ids:
            status = "PASS_WITH_ACCEPTED_WARNINGS"
        else:
            status = "PASS"
        return {
            "schema_version": "1.0",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "origin": EXPECTED_ORIGIN,
            "release": {
                "plugin_version": self.plugin_version,
                "previous_plugin_version": self.previous_plugin_version,
                "theme_version": self.theme_version,
                "record_hash": self.record_hash,
                "record_id": EXPECTED_RECORD_ID,
                "review_date": EXPECTED_REVIEW_DATE,
                "favicon_mode": (
                    "theme_fallback"
                    if self.expect_fallback_favicon
                    else "configured_site_icon"
                ),
                "configured_site_icon_urls": list(
                    self.configured_site_icon_urls
                ),
            },
            "status": status,
            "summary": {
                "passed": counts["pass"],
                "warnings": counts["warning"],
                "failed": counts["fail"],
                "unaccepted_warnings": unaccepted_warnings,
            },
            "warning_decisions": warning_decisions,
            "checks": [asdict(check) for check in self.checks],
        }


def inline_style_declarations(style: str) -> dict[str, str]:
    declarations: dict[str, str] = {}
    without_comments = re.sub(
        r"/\*.*?\*/",
        "",
        style,
        flags=re.DOTALL,
    )
    for declaration in without_comments.split(";"):
        if ":" not in declaration:
            continue
        property_name, property_value = declaration.split(":", 1)
        normalized_name = property_name.strip().lower()
        if not normalized_name:
            continue
        declarations[normalized_name] = re.sub(
            r"\s*!important\s*$",
            "",
            property_value.strip().lower(),
        )
    return declarations


def compact_css_value(value: str) -> str:
    return re.sub(r"\s+", "", value)


def css_zero_value(value: str, *, allow_percent: bool = True) -> bool:
    percentage = "%?" if allow_percent else ""
    return (
        re.fullmatch(
            rf"[+-]?(?:0+(?:\.0*)?|\.0+){percentage}",
            compact_css_value(value),
        )
        is not None
    )


def inline_style_hides_content(
    declarations: dict[str, str],
) -> bool:
    clip_value = compact_css_value(declarations.get("clip", ""))
    zero_length = r"[+-]?(?:0+(?:\.0*)?|\.0+)(?:[a-z]+|%)?"
    clipped_rectangle = (
        re.fullmatch(
            rf"rect\({zero_length},{zero_length},"
            rf"{zero_length},{zero_length}\)",
            clip_value,
        )
        is not None
    )
    clip_path = declarations.get("clip-path", "").strip()
    clipped_inset = (
        re.fullmatch(
            (
                r"inset\(\s*(?:50%|100%)"
                r"(?:\s+(?:50%|100%)){0,3}\s*\)"
            ),
            clip_path,
        )
        is not None
    )
    zero_sized = (
        css_zero_value(declarations.get("width", ""))
        and css_zero_value(declarations.get("height", ""))
    )
    transform = compact_css_value(declarations.get("transform", ""))
    zero_number = r"[+-]?(?:0+(?:\.0*)?|\.0+)%?"
    transformed_away = (
        re.search(
            (
                rf"(?:scale(?:x|y)?\({zero_number}\)"
                rf"|scale\({zero_number},[^)]+\)"
                rf"|scale\([^)]+,{zero_number}\)"
                r"|translate(?:x|y)?\(-(?:999|[1-9]\d{3,})"
                r"(?:px|rem|vw|vh|%)\))"
            ),
            transform,
        )
        is not None
    )
    positioned_offscreen = any(
        re.fullmatch(
            r"-(?:999|[1-9]\d{3,})(?:px|rem|vw|vh|%)",
            compact_css_value(declarations.get(property_name, "")),
        )
        is not None
        for property_name in ("bottom", "left", "right", "top")
    )
    return (
        compact_css_value(declarations.get("display", "")) == "none"
        or compact_css_value(
            declarations.get("content-visibility", "")
        )
        == "hidden"
        or compact_css_value(declarations.get("visibility", ""))
        in {"collapse", "hidden"}
        or css_zero_value(declarations.get("opacity", ""))
        or clipped_rectangle
        or clipped_inset
        or zero_sized
        or transformed_away
        or positioned_offscreen
    )


def hidden_simple_css_selectors(
    css: str,
) -> tuple[set[str], set[str], set[str]]:
    text = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    hidden_classes: set[str] = set()
    hidden_ids: set[str] = set()
    hidden_tags: set[str] = set()
    quote = ""
    escaped = False
    depth = 0
    prelude_start = 0
    content_start = 0
    prelude = ""
    for index, character in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            continue
        if character in {"'", '"'}:
            quote = character
            continue
        if character == "{" and depth == 0:
            prelude = text[prelude_start:index].strip()
            content_start = index + 1
            depth = 1
            continue
        if character == "{" and depth > 0:
            depth += 1
            continue
        if character == "}" and depth > 0:
            depth -= 1
            if depth != 0:
                continue
            content = text[content_start:index]
            if (
                prelude
                and not prelude.startswith("@")
                and "{" not in content
                and inline_style_hides_content(
                    inline_style_declarations(content)
                )
            ):
                for selector in prelude.split(","):
                    normalized = selector.strip()
                    class_match = re.fullmatch(
                        r"\.([A-Za-z_][\w-]*)",
                        normalized,
                    )
                    id_match = re.fullmatch(
                        r"#([A-Za-z_][\w-]*)",
                        normalized,
                    )
                    tag_match = re.fullmatch(
                        r"[A-Za-z][A-Za-z0-9-]*",
                        normalized,
                    )
                    if class_match:
                        hidden_classes.add(class_match.group(1))
                    elif id_match:
                        hidden_ids.add(id_match.group(1))
                    elif tag_match:
                        hidden_tags.add(normalized.lower())
            prelude_start = index + 1
            continue
        if character == ";" and depth == 0:
            prelude_start = index + 1
    return hidden_classes, hidden_ids, hidden_tags


class HtmlFacts(HTMLParser):
    VOID_ELEMENTS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.html_language = ""
        self.title_parts: list[str] = []
        self.h1_text_parts: list[list[str]] = []
        self.body_text_parts: list[str] = []
        self.comments: list[str] = []
        self.body_comments: list[str] = []
        self.metas: dict[str, list[str]] = defaultdict(list)
        self.meta_refresh_values: list[str] = []
        self.links: list[dict[str, str]] = []
        self.base_hrefs: list[str] = []
        self.scripts: list[dict[str, str]] = []
        self.styles: list[str] = []
        self.inline_event_handler_count = 0
        self.body_hrefs: list[str] = []
        self.all_body_hrefs: list[str] = []
        self.image_sources: list[str] = []
        self.visible_attributes: list[str] = []
        self.element_ids: set[str] = set()
        self.class_counts: Counter[str] = Counter()
        self.class_tag_counts: Counter[tuple[str, str]] = Counter()
        self.descendant_class_counts: Counter[tuple[str, str]] = Counter()
        self.descendant_class_tag_counts: Counter[
            tuple[str, str, str]
        ] = Counter()
        self.descendant_tag_counts: Counter[tuple[str, str]] = Counter()
        self.class_text_parts: dict[str, list[str]] = defaultdict(list)
        self.input_names_by_class: dict[str, set[str]] = defaultdict(set)
        self.link_hrefs_by_class: dict[str, list[str]] = defaultdict(list)
        self.form_actions_by_class: dict[str, list[str]] = defaultdict(list)
        self.form_methods_by_class: dict[str, list[str]] = defaultdict(list)
        self.submit_controls_by_class: Counter[str] = Counter()
        self.submit_controls_by_class_tag: Counter[
            tuple[str, str]
        ] = Counter()
        self.submit_control_names_by_class: dict[
            str, set[str]
        ] = defaultdict(set)
        self.tag_counts: Counter[str] = Counter()
        self.body_classes: set[str] = set()
        self.input_names: set[str] = set()
        self.form_actions: list[str] = []
        self.structure_errors: list[str] = []
        self.html_count = 0
        self.head_count = 0
        self.body_count = 0
        self.title_count = 0
        self.h1_count = 0
        self.main_count = 0
        self.specification_count = 0
        self.source_count = 0
        self._stack: list[tuple[str, frozenset[str]]] = []
        self._in_title = False
        self._body_closed = False
        self._head_closed = False
        self._document_closed = False
        self._script_type = ""
        self._script_source = ""
        self._script_parts: list[str] = []
        self._script_in_head = False
        self._style_parts: list[str] = []
        self._hidden_css_classes: set[str] = set()
        self._hidden_css_ids: set[str] = set()
        self._hidden_css_tags: set[str] = set()
        self._hidden_depth = 0
        self._hidden_stack: list[bool] = []
        self.elements: list[dict[str, Any]] = []
        self._element_stack: list[int | None] = []

    def _inside(self, tag: str) -> bool:
        return any(frame_tag == tag for frame_tag, _classes in self._stack)

    def _inside_class(self, tag: str, class_name: str) -> bool:
        return any(
            frame_tag == tag and class_name in classes
            for frame_tag, classes in self._stack
        )

    def _close_frame(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag == "script":
            self.scripts.append(
                {
                    "type": self._script_type,
                    "src": self._script_source,
                    "content": "".join(self._script_parts),
                    "in_head": self._script_in_head,
                }
            )
            self._script_type = ""
            self._script_source = ""
            self._script_parts = []
            self._script_in_head = False
        if tag == "style":
            style_text = "".join(self._style_parts)
            if style_text.strip():
                self.styles.append(style_text)
            hidden_classes, hidden_ids, hidden_tags = (
                hidden_simple_css_selectors(
                    style_text
                )
            )
            self._hidden_css_classes.update(hidden_classes)
            self._hidden_css_ids.update(hidden_ids)
            self._hidden_css_tags.update(hidden_tags)
            self._style_parts = []
        if tag == "head":
            self._head_closed = True
        if tag == "body":
            self._body_closed = True
        if tag == "html":
            self._document_closed = True

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        tag = tag.lower()
        lowered_names = [name.lower() for name, _value in attrs]
        if len(lowered_names) != len(set(lowered_names)):
            self.structure_errors.append("duplicate_attribute")
        values = {name.lower(): value or "" for name, value in attrs}
        attribute_names = set(lowered_names)
        self.inline_event_handler_count += sum(
            1
            for name, value in values.items()
            if name.startswith("on") and bool(value.strip())
        )
        classes = frozenset(values.get("class", "").split())
        normalized_classes = {
            class_name.strip().lower()
            for class_name in classes
        }
        style_declarations = inline_style_declarations(
            values.get("style", "")
        )
        ancestor_classes = {
            class_name
            for _frame_tag, frame_classes in self._stack
            for class_name in frame_classes
        }

        if self._document_closed:
            self.structure_errors.append("element_after_html")
        if tag == "html":
            self.html_count += 1
            if self.html_count == 1 and not self._stack and not self._document_closed:
                self.html_language = values.get("lang", "")
            else:
                self.structure_errors.append("duplicate_html")
        elif not self._stack:
            self.structure_errors.append("element_outside_html")

        if tag == "head":
            self.head_count += 1
            if (
                self.head_count != 1
                or [frame[0] for frame in self._stack] != ["html"]
                or self.body_count
                or self._head_closed
            ):
                self.structure_errors.append("invalid_head")
        if tag == "body":
            self.body_count += 1
            if (
                self.body_count != 1
                or [frame[0] for frame in self._stack] != ["html"]
                or not self._head_closed
            ):
                self.structure_errors.append("invalid_body")
            self.body_classes.update(values.get("class", "").split())

        in_head_before = self._inside("head")
        in_body_before = self._inside("body")
        in_head = in_head_before or tag == "head"
        in_body = in_body_before or tag == "body"
        nested_form = tag == "form" and self._inside("form")
        class_hides_content = any(
            class_name
            in {
                "a11y-hidden",
                "elementor-screen-only",
                "hidden",
                "is-hidden",
                "offscreen",
                "sr-only",
                "u-hidden",
                "visually-hidden",
            }
            or "screen-reader" in class_name
            or class_name.endswith("__hidden")
            for class_name in normalized_classes
        )
        stylesheet_hides_content = (
            tag in self._hidden_css_tags
            or values.get("id", "") in self._hidden_css_ids
            or bool(classes & self._hidden_css_classes)
        )
        hides_element = in_body and (
            tag in {
                "datalist",
                "noscript",
                "script",
                "style",
                "template",
            }
            or (tag in {"details", "dialog"} and "open" not in attribute_names)
            or "popover" in attribute_names
            or class_hides_content
            or stylesheet_hides_content
            or "hidden" in attribute_names
            or "inert" in attribute_names
            or values.get("aria-hidden", "").strip().lower() == "true"
            or inline_style_hides_content(style_declarations)
        )
        hides_descendants = hides_element or (in_body and tag == "select")
        ancestor_visible = in_body and self._hidden_depth == 0
        visible_in_body = ancestor_visible and not hides_element
        if tag == "body" and hides_element:
            self.structure_errors.append("hidden_body")
        parent_element_id = next(
            (
                element_id
                for element_id in reversed(self._element_stack)
                if element_id is not None
            ),
            None,
        )
        element_id: int | None = None
        if ancestor_visible:
            element_id = len(self.elements)
            self.elements.append(
                {
                    "attribute_names": frozenset(attribute_names),
                    "attrs": dict(values),
                    "classes": classes,
                    "id": element_id,
                    "parent_id": parent_element_id,
                    "rendered": (
                        visible_in_body
                        and not (
                            tag == "input"
                            and values.get("type", "").lower() == "hidden"
                        )
                    ),
                    "tag": tag,
                    "text_parts": [],
                }
            )
        if tag not in self.VOID_ELEMENTS:
            self._stack.append((tag, classes))
            self._hidden_stack.append(hides_descendants)
            self._element_stack.append(element_id)
            if hides_descendants:
                self._hidden_depth += 1

        if tag == "title":
            self.title_count += 1
            if not in_head or self.title_count != 1:
                self.structure_errors.append("invalid_title")
            self._in_title = in_head
        if tag == "base" and in_head:
            self.base_hrefs.append(values.get("href", ""))

        if (
            tag == "dt"
            and visible_in_body
            and self._inside_class("dl", "rbtx-spec-list")
        ):
            self.specification_count += 1
        if (
            tag == "li"
            and visible_in_body
            and self._inside_class("ol", "rbtx-source-list")
        ):
            self.source_count += 1

        if tag == "script":
            self._script_type = values.get("type", "").lower()
            self._script_source = values.get("src", "")
            self._script_parts = []
            self._script_in_head = in_head
        if tag == "style":
            self._style_parts = []
        if tag == "meta":
            http_equiv = values.get("http-equiv", "").strip().lower()
            if http_equiv == "refresh":
                self.meta_refresh_values.append(values.get("content", ""))
                self.structure_errors.append("meta_refresh")
        if tag == "meta" and in_head:
            key = (
                values.get("name")
                or values.get("property")
                or ""
            ).lower()
            if key:
                self.metas[key].append(values.get("content", ""))
        if tag == "link" and in_head:
            self.links.append(values)
        if tag == "a" and in_body:
            self.all_body_hrefs.append(values.get("href", ""))
        if tag == "a" and visible_in_body:
            self.body_hrefs.append(values.get("href", ""))
            for _frame_tag, frame_classes in self._stack:
                for class_name in frame_classes:
                    self.link_hrefs_by_class[class_name].append(
                        values.get("href", "")
                    )
        if tag == "img" and visible_in_body:
            self.image_sources.append(values.get("src", ""))
            for candidate in values.get("srcset", "").split(","):
                candidate_url = candidate.strip().split(" ", 1)[0]
                if candidate_url:
                    self.image_sources.append(candidate_url)
        if tag == "h1" and visible_in_body:
            self.h1_count += 1
            self.h1_text_parts.append([])
        if tag == "main" and visible_in_body:
            self.main_count += 1
        if visible_in_body:
            self.tag_counts[tag] += 1
            for ancestor_class in ancestor_classes:
                self.descendant_tag_counts[(ancestor_class, tag)] += 1
            if values.get("id"):
                self.element_ids.add(values["id"])
            for class_name in values.get("class", "").split():
                self.class_counts[class_name] += 1
                self.class_tag_counts[(class_name, tag)] += 1
                for ancestor_class in ancestor_classes:
                    self.descendant_class_counts[
                        (ancestor_class, class_name)
                    ] += 1
                    self.descendant_class_tag_counts[
                        (ancestor_class, class_name, tag)
                    ] += 1
            if tag == "input" and values.get("name"):
                self.input_names.add(values["name"])
                for _frame_tag, frame_classes in self._stack:
                    for class_name in frame_classes:
                        self.input_names_by_class[class_name].add(
                            values["name"]
                        )
            if tag == "form":
                if nested_form:
                    self.structure_errors.append("nested_form")
                self.form_actions.append(values.get("action", ""))
                for _frame_tag, frame_classes in self._stack:
                    for class_name in frame_classes:
                        self.form_actions_by_class[class_name].append(
                            values.get("action", "")
                        )
                        self.form_methods_by_class[class_name].append(
                            values.get("method", "get").strip().lower()
                            or "get"
                        )
            is_submit = (
                (
                    tag == "button"
                    and values.get("type", "submit").lower()
                    in {"", "submit"}
                )
                or (
                    tag == "input"
                    and values.get("type", "").lower()
                    in {"image", "submit"}
                )
            ) and (
                "disabled" not in attribute_names
                and values.get("aria-disabled", "").strip().lower()
                != "true"
            )
            if is_submit:
                for _frame_tag, frame_classes in self._stack:
                    for class_name in frame_classes:
                        self.submit_controls_by_class[class_name] += 1
                        self.submit_controls_by_class_tag[
                            (class_name, _frame_tag)
                        ] += 1
                        if values.get("name"):
                            self.submit_control_names_by_class[
                                class_name
                            ].add(values["name"])
            for name in ("alt", "aria-label", "title", "placeholder"):
                if values.get(name):
                    self.visible_attributes.append(values[name])

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in self.VOID_ELEMENTS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.VOID_ELEMENTS:
            self.structure_errors.append("void_end_tag")
            return
        if not self._stack:
            self.structure_errors.append("unexpected_end_tag")
            return
        if self._stack[-1][0] != tag:
            self.structure_errors.append("misnested_end_tag")
            matching_index = next(
                (
                    index
                    for index in range(len(self._stack) - 1, -1, -1)
                    if self._stack[index][0] == tag
                ),
                None,
            )
            if matching_index is None:
                return
            while len(self._stack) > matching_index:
                popped_tag, _classes = self._stack.pop()
                hidden = self._hidden_stack.pop()
                self._element_stack.pop()
                if hidden:
                    self._hidden_depth = max(
                        0,
                        self._hidden_depth - 1,
                    )
                self._close_frame(popped_tag)
            return
        self._stack.pop()
        hidden = self._hidden_stack.pop()
        self._element_stack.pop()
        if hidden:
            self._hidden_depth = max(0, self._hidden_depth - 1)
        self._close_frame(tag)

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        in_body = self._inside("body")
        if self._document_closed and stripped:
            self.structure_errors.append("visible_text_after_html")
        elif self._body_closed and stripped:
            self.structure_errors.append("visible_text_after_body")
        elif not self._stack and stripped:
            self.structure_errors.append("visible_text_before_html")
        elif (
            stripped
            and not in_body
            and not self._inside("head")
        ):
            self.structure_errors.append(
                "visible_text_outside_document_regions"
            )
        if self._in_title:
            self.title_parts.append(data)
        if self._inside("script"):
            self._script_parts.append(data)
        if self._inside("style"):
            self._style_parts.append(data)
        hidden = self._hidden_depth > 0
        if in_body and not hidden and stripped:
            self.body_text_parts.append(stripped)
            for element_id in self._element_stack:
                if element_id is not None:
                    self.elements[element_id]["text_parts"].append(stripped)
            for _frame_tag, frame_classes in self._stack:
                for class_name in frame_classes:
                    self.class_text_parts[class_name].append(stripped)
            if self._inside("h1") and self.h1_text_parts:
                self.h1_text_parts[-1].append(stripped)

    def handle_comment(self, data: str) -> None:
        data = data.strip()
        self.comments.append(data)
        if self._inside("body"):
            self.body_comments.append(data)

    def close(self) -> None:
        super().close()
        if self._stack:
            self.structure_errors.append("unclosed_elements")
        if not self._document_closed:
            self.structure_errors.append("unclosed_html")

    @property
    def title(self) -> str:
        return " ".join(" ".join(self.title_parts).split())

    @property
    def h1_texts(self) -> list[str]:
        return [
            " ".join(" ".join(parts).split())
            for parts in self.h1_text_parts
        ]

    @property
    def body_text(self) -> str:
        return " ".join(self.body_text_parts)

    def meta_values(self, key: str) -> list[str]:
        return self.metas.get(key.lower(), [])

    def class_text(self, class_name: str) -> str:
        return " ".join(self.class_text_parts.get(class_name, []))

    def asset_urls(self) -> list[str]:
        urls = [link.get("href", "") for link in self.links]
        urls.extend(script.get("src", "") for script in self.scripts)
        return [url for url in urls if url]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify the public evidence for a RobbottX release."
    )
    parser.add_argument("--plugin-version", required=True)
    parser.add_argument("--theme-version", required=True)
    parser.add_argument("--record-hash", required=True)
    parser.add_argument("--previous-plugin-version", required=True)
    parser.add_argument(
        "--expect-fallback-favicon",
        action=argparse.BooleanOptionalAction,
        required=True,
        help=(
            "Require the versioned theme fallback favicon, or use the "
            "negative form for a configured same-origin WordPress site icon."
        ),
    )
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--configured-site-icon-url",
        action="append",
        default=[],
        help=(
            "Authenticated preflight-proven public site-icon URL. Repeat for "
            "every configured icon emitted in the public head."
        ),
    )
    parser.add_argument(
        "--warning-decision",
        action="append",
        default=[],
        metavar="CHECK_ID=OWNER|DECISION",
        help=(
            "Record an explicit owner and decision for one warning. "
            "Repeat for each accepted warning."
        ),
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    for name in (
        "plugin_version",
        "theme_version",
        "previous_plugin_version",
    ):
        if re.fullmatch(r"\d+\.\d+\.\d+", getattr(args, name)) is None:
            raise ValueError(f"{name} must be a three-part numeric version.")
    if re.fullmatch(r"[0-9a-fA-F]{64}", args.record_hash) is None:
        raise ValueError("record_hash must be a 64-character hexadecimal value.")
    if args.plugin_version == args.previous_plugin_version:
        raise ValueError(
            "previous_plugin_version must differ from plugin_version."
        )
    configured_icons = tuple(args.configured_site_icon_url)
    if args.expect_fallback_favicon and configured_icons:
        raise ValueError(
            "Fallback favicon mode cannot include configured icon URLs."
        )
    if not args.expect_fallback_favicon and not configured_icons:
        raise ValueError(
            "Configured favicon mode requires authenticated icon URLs."
        )
    if len(configured_icons) != len(set(configured_icons)):
        raise ValueError("Configured site-icon URLs must be unique.")
    for icon_url in configured_icons:
        validate_canonical_url(icon_url)
    if args.samples < 3 or args.samples > 9:
        raise ValueError("samples must be between 3 and 9.")
    if args.output.exists():
        raise FileExistsError(
            "Refusing to overwrite an existing verification record."
        )
    parse_warning_decisions(args.warning_decision)


def parse_warning_decisions(
    values: list[str],
) -> dict[str, dict[str, str]]:
    decisions: dict[str, dict[str, str]] = {}
    for value in values:
        check_id, separator, remainder = value.partition("=")
        owner, owner_separator, decision = remainder.partition("|")
        if (
            not separator
            or not owner_separator
            or re.fullmatch(r"[a-z0-9_.-]+", check_id) is None
            or len(owner.strip()) < 2
            or len(decision.strip()) < 10
            or check_id in decisions
        ):
            raise ValueError(
                "warning_decision must be unique "
                "CHECK_ID=OWNER|DECISION text."
            )
        decisions[check_id] = {
            "owner": owner.strip(),
            "decision": decision.strip(),
        }
    return decisions


def build_url(path: str, *, cache_buster: bool = True) -> str:
    url = urllib.parse.urljoin(EXPECTED_ORIGIN + "/", path.lstrip("/"))
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != urllib.parse.urlsplit(EXPECTED_ORIGIN).netloc
    ):
        raise ValueError("Verification URL left the canonical origin.")
    if not cache_buster:
        return url
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query.append(("rbtxverify", str(time.time_ns())))
    return urllib.parse.urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urllib.parse.urlencode(query),
            "",
        )
    )


def validate_canonical_url(url: str) -> urllib.parse.SplitResult:
    parsed = urllib.parse.urlsplit(url)
    expected = urllib.parse.urlsplit(EXPECTED_ORIGIN)
    if (
        parsed.scheme != "https"
        or parsed.netloc != expected.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.fragment
        or not parsed.path.startswith("/")
    ):
        raise ValueError(
            "Verification URL must remain on the exact canonical HTTPS origin."
        )
    return parsed


def media_type(content_type: str) -> str:
    return content_type.split(";", 1)[0].strip().lower()


def is_json_media_type(content_type: str) -> bool:
    return media_type(content_type) == "application/json"


def is_html_media_type(content_type: str) -> bool:
    return media_type(content_type) == "text/html"


def is_xml_media_type(content_type: str) -> bool:
    return media_type(content_type) in {
        "application/atom+xml",
        "application/rss+xml",
        "application/xml",
        "text/xml",
    }


def validate_content_type(
    response: HttpResult,
    *,
    allowed_media_types: set[str],
    allowed_charsets: set[str | None],
) -> str:
    value = response.single_header("content-type")
    if value is None or value != response.content_type:
        raise ValueError("Response has no unambiguous Content-Type header.")
    parts = [part.strip() for part in value.split(";")]
    actual_media_type = parts[0].lower()
    if actual_media_type not in allowed_media_types:
        raise ValueError("Response uses an unexpected media type.")
    charset: str | None = None
    seen_parameters: set[str] = set()
    for parameter in parts[1:]:
        name, separator, raw_value = parameter.partition("=")
        name = name.strip().lower()
        if (
            not separator
            or not name
            or name in seen_parameters
            or name != "charset"
        ):
            raise ValueError("Response uses unexpected media parameters.")
        seen_parameters.add(name)
        charset = raw_value.strip().strip("\"'").lower()
        if charset == "utf8":
            charset = "utf-8"
        if charset == "us-ascii":
            charset = "ascii"
    if charset not in allowed_charsets:
        raise ValueError("Response uses an unsupported character set.")
    return actual_media_type


def valid_image_payload(
    response: HttpResult,
    actual_media_type: str,
) -> bool:
    body = response.body
    if not body:
        return False
    if actual_media_type == "image/svg+xml":
        try:
            root = ET.fromstring(response.text())
        except (ET.ParseError, UnicodeDecodeError, ValueError):
            return False
        return root.tag.rsplit("}", 1)[-1].lower() == "svg"
    expected_formats = {
        "image/avif": "AVIF",
        "image/gif": "GIF",
        "image/jpeg": "JPEG",
        "image/png": "PNG",
        "image/webp": "WEBP",
    }
    expected_format = expected_formats.get(actual_media_type)
    if expected_format is None or PillowImage is None:
        return False
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            with PillowImage.open(io.BytesIO(body)) as image:
                width, height = image.size
                if (
                    image.format != expected_format
                    or width <= 0
                    or height <= 0
                    or width > 8192
                    or height > 8192
                ):
                    return False
                image.verify()
            with PillowImage.open(io.BytesIO(body)) as image:
                image.load()
    except Exception:
        return False
    return True


def has_unquoted_html_tag(text: str) -> bool:
    quote = ""
    escaped = False
    in_comment = False
    index = 0
    while index < len(text):
        character = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if in_comment:
            if character == "*" and following == "/":
                in_comment = False
                index += 2
                continue
            index += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            index += 1
            continue
        if character == "/" and following == "*":
            in_comment = True
            index += 2
            continue
        if character in {"'", '"'}:
            quote = character
            index += 1
            continue
        if character == "<" and re.match(
            r"<\s*(?:!doctype\b|/?[a-z][a-z0-9:-]*"
            r"(?:\s+[^<>]*?)?\s*/?>)",
            text[index:],
            re.I,
        ):
            return True
        index += 1
    return False


def css_has_usable_declaration(text: str) -> bool:
    property_pattern = re.compile(r"(?:--|-?)[a-z_][a-z0-9_-]*$", re.I)
    frames: list[dict[str, Any]] = []
    quote = ""
    escaped = False
    in_comment = False
    parenthesis_depth = 0
    bracket_depth = 0
    usable = False
    index = 0

    def reset(frame: dict[str, Any]) -> None:
        frame["segment"] = []
        frame["property"] = False
        frame["value"] = False

    def finish(frame: dict[str, Any]) -> None:
        nonlocal usable
        if frame["property"] and frame["value"]:
            usable = True
        reset(frame)

    while index < len(text):
        character = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if in_comment:
            if character == "*" and following == "/":
                in_comment = False
                index += 2
                continue
            index += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            index += 1
            continue
        if character == "/" and following == "*":
            in_comment = True
            index += 2
            continue
        if character in {"'", '"'}:
            quote = character
            if frames and frames[-1]["property"]:
                frames[-1]["value"] = True
            index += 1
            continue
        if character == "{":
            if frames:
                reset(frames[-1])
            frames.append(
                {
                    "segment": [],
                    "property": False,
                    "value": False,
                }
            )
            index += 1
            continue
        if character == "}":
            if frames:
                finish(frames[-1])
                frames.pop()
            parenthesis_depth = 0
            bracket_depth = 0
            index += 1
            continue
        if not frames:
            index += 1
            continue

        frame = frames[-1]
        if character == "(":
            parenthesis_depth += 1
        elif character == ")":
            parenthesis_depth = max(0, parenthesis_depth - 1)
        elif character == "[":
            bracket_depth += 1
        elif character == "]":
            bracket_depth = max(0, bracket_depth - 1)

        if (
            character == ";"
            and parenthesis_depth == 0
            and bracket_depth == 0
        ):
            finish(frame)
        elif (
            character == ":"
            and not frame["property"]
            and property_pattern.fullmatch(
                "".join(frame["segment"]).strip()
            )
        ):
            frame["property"] = True
            frame["segment"] = []
        elif frame["property"]:
            if not character.isspace():
                frame["value"] = True
        else:
            frame["segment"].append(character)
        index += 1

    return usable


def css_delimiters_balanced(text: str) -> bool:
    quote = ""
    escaped = False
    in_comment = False
    brace_depth = 0
    parenthesis_depth = 0
    bracket_depth = 0
    index = 0
    while index < len(text):
        character = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if in_comment:
            if character == "*" and following == "/":
                in_comment = False
                index += 2
                continue
            index += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            index += 1
            continue
        if character == "/" and following == "*":
            in_comment = True
            index += 2
            continue
        if character in {"'", '"'}:
            quote = character
        elif character == "{":
            brace_depth += 1
        elif character == "}":
            brace_depth -= 1
        elif character == "(":
            parenthesis_depth += 1
        elif character == ")":
            parenthesis_depth -= 1
        elif character == "[":
            bracket_depth += 1
        elif character == "]":
            bracket_depth -= 1
        if min(brace_depth, parenthesis_depth, bracket_depth) < 0:
            return False
        if ord(character) < 32 and character not in "\t\n\r\f":
            return False
        index += 1
    return (
        quote == ""
        and not escaped
        and not in_comment
        and brace_depth == 0
        and parenthesis_depth == 0
        and bracket_depth == 0
    )


def normalized_asset_words(text: str) -> str:
    expanded = re.sub(
        r"(?<=[a-z0-9])(?=[A-Z])",
        " ",
        text,
    )
    expanded = re.sub(
        r"(?<=[A-Z])(?=[A-Z][a-z])",
        " ",
        expanded,
    )
    expanded = re.sub(
        r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])",
        " ",
        expanded,
    )
    return " ".join(
        re.sub(r"[^a-z0-9]+", " ", expanded.lower()).split()
    )


def asset_has_denial_semantics(text: str) -> bool:
    normalized = normalized_asset_words(text)
    if any(
        re.search(pattern, normalized) is not None
        for pattern in (
            r"\baccess (?:is )?denied\b",
            r"\baccessdenied\b",
            r"\bpermission denied\b",
            r"\bforbidden\b",
            r"\bunauthori[sz]ed\b",
            r"\brequest (?:was )?(?:blocked|denied|rejected)\b",
            r"\bweb application firewall\b",
            r"\bcloudflare ray id\b",
            (
                r"\b(?:error(?: code)?|http|response code|"
                r"status(?: code)?) (?:401|403)\b"
            ),
            (
                r"\b(?:401|403) (?:access denied|error|forbidden|"
                r"unauthori[sz]ed)\b"
            ),
        )
    ):
        return True
    tokens = set(normalized.split())
    return (
        "403" in tokens
        and tokens.issubset(
            {
                "403",
                "code",
                "default",
                "error",
                "export",
                "http",
                "message",
                "new",
                "response",
                "status",
                "throw",
                "void",
            }
        )
    )


def javascript_lexical_view(
    text: str,
    *,
    keep_literals: bool,
) -> str:
    output: list[str] = []
    quote = ""
    escaped = False
    in_block_comment = False
    in_line_comment = False
    index = 0
    while index < len(text):
        character = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if in_block_comment:
            if character == "*" and following == "/":
                in_block_comment = False
                index += 2
            else:
                index += 1
            continue
        if in_line_comment:
            if character in "\r\n":
                in_line_comment = False
                output.append(character)
            index += 1
            continue
        if quote:
            if keep_literals:
                output.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            index += 1
            continue
        if character == "/" and following == "*":
            in_block_comment = True
            output.append(" ")
            index += 2
            continue
        if character == "/" and following == "/":
            in_line_comment = True
            output.append(" ")
            index += 2
            continue
        if character in {"'", '"', "`"}:
            quote = character
            if keep_literals:
                output.append(character)
            else:
                output.append(" ")
            index += 1
            continue
        output.append(character)
        index += 1
    return "".join(output)


def javascript_is_denial_payload(text: str) -> bool:
    commentless = javascript_lexical_view(
        text,
        keep_literals=True,
    )
    if not commentless.strip():
        return True
    normalized_tokens = set(normalized_asset_words(text).split())
    if (
        not asset_has_denial_semantics(text)
        and normalized_tokens.isdisjoint({"401", "403"})
    ):
        return False
    skeleton = javascript_lexical_view(
        text,
        keep_literals=False,
    )
    inert_tokens = {
        "401",
        "403",
        "access",
        "blocked",
        "body",
        "cloudflare",
        "code",
        "console",
        "content",
        "default",
        "denied",
        "document",
        "error",
        "errors",
        "export",
        "false",
        "forbidden",
        "global",
        "http",
        "https",
        "id",
        "inner",
        "innerhtml",
        "innertext",
        "insert",
        "adjacent",
        "append",
        "children",
        "element",
        "elements",
        "get",
        "by",
        "tag",
        "name",
        "query",
        "selector",
        "replace",
        "is",
        "message",
        "new",
        "nginx",
        "null",
        "permission",
        "ray",
        "request",
        "response",
        "security",
        "service",
        "status",
        "self",
        "text",
        "textcontent",
        "this",
        "throw",
        "true",
        "unauthorised",
        "unauthorized",
        "undefined",
        "void",
        "waf",
        "window",
        "write",
        "writeln",
    }
    tokens = normalized_asset_words(skeleton).split()
    return all(token in inert_tokens for token in tokens)


def valid_css_payload(text: str) -> bool:
    if (
        not text.strip()
        or "\x00" in text
        or has_unquoted_html_tag(text)
        or not css_delimiters_balanced(text)
    ):
        return False
    node_path = shutil.which("node")
    validator = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "qa"
        / "validate-css-stdin.mjs"
    )
    if node_path is None or not validator.is_file():
        return False
    try:
        completed = subprocess.run(
            [node_path, str(validator)],
            input=text,
            text=True,
            encoding="utf-8",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def valid_javascript_payload(text: str, *, module: bool = False) -> bool:
    if (
        not text.strip()
        or "\x00" in text
        or javascript_is_denial_payload(text)
    ):
        return False
    node_path = shutil.which("node")
    validator = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "qa"
        / "validate-javascript-stdin.mjs"
    )
    if node_path is None or not validator.is_file():
        return False
    try:
        command = [node_path, str(validator)]
        if module:
            command.append("--module")
        completed = subprocess.run(
            command,
            input=text,
            text=True,
            encoding="utf-8",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def find_commerce_chrome() -> Path | None:
    candidates = [
        os.environ.get("CHROME_PATH", ""),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        str(
            Path(os.environ.get("LOCALAPPDATA", ""))
            / "Google"
            / "Chrome"
            / "Application"
            / "chrome.exe"
        )
        if os.environ.get("LOCALAPPDATA")
        else "",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ]
    for command_name in (
        "chrome",
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
    ):
        resolved = shutil.which(command_name)
        if resolved:
            candidates.append(resolved)
    for candidate in candidates:
        if not candidate:
            continue
        executable = Path(candidate).expanduser().resolve()
        if executable.is_file():
            return executable
    return None


def commerce_browser_helper_environment() -> dict[str, str]:
    allowed_names = (
        "COMSPEC",
        "HOME",
        "HOMEDRIVE",
        "HOMEPATH",
        "LANG",
        "LC_ALL",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TZ",
        "USERPROFILE",
        "WINDIR",
        "XDG_RUNTIME_DIR",
    )
    return {
        name: os.environ[name]
        for name in allowed_names
        if name in os.environ
    }


def remove_owned_commerce_browser_profile(profile: Path) -> bool:
    temporary_root = Path(tempfile.gettempdir()).resolve()
    candidate = profile.resolve(strict=False)
    if (
        candidate.parent != temporary_root
        or not candidate.name.startswith(COMMERCE_BROWSER_PROFILE_PREFIX)
        or len(candidate.name) <= len(COMMERCE_BROWSER_PROFILE_PREFIX)
    ):
        return False
    for attempt in range(5):
        try:
            if candidate.exists():
                shutil.rmtree(candidate)
            return not candidate.exists()
        except OSError:
            if attempt == 4:
                return False
            time.sleep(0.1)
    return False


def commerce_browser_failure(
    *,
    mode: str,
    source: str,
    code: str,
) -> dict[str, Any]:
    return {
        "schemaVersion": COMMERCE_BROWSER_SCHEMA_VERSION,
        "operational": False,
        "passed": False,
        "mode": mode,
        "source": source,
        "routeUi": "",
        "failureCodes": [code],
        "navigation": {
            "status": None,
            "redirectStatus": None,
            "finalOrigin": "",
            "finalPath": "",
            "redirectCount": 0,
        },
        "stylesheets": {
            "externalCount": 0,
            "loadedCount": 0,
            "failedCount": 0,
            "blockedCount": 0,
        },
        "dom": {},
    }


def terminate_owned_browser_helper_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                [
                    "taskkill.exe",
                    "/PID",
                    str(process.pid),
                    "/T",
                    "/F",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
                creationflags=getattr(
                    subprocess,
                    "CREATE_NO_WINDOW",
                    0,
                ),
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        try:
            process.kill()
        except OSError:
            pass


def valid_commerce_browser_result(
    value: Any,
    *,
    mode: str,
    source: str,
    expected_path: str,
) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "schemaVersion",
        "operational",
        "passed",
        "mode",
        "source",
        "routeUi",
        "failureCodes",
        "navigation",
        "stylesheets",
        "dom",
    }:
        return False
    if (
        value.get("schemaVersion") != COMMERCE_BROWSER_SCHEMA_VERSION
        or type(value.get("operational")) is not bool
        or type(value.get("passed")) is not bool
        or value.get("mode") != mode
        or value.get("source") != source
        or value.get("routeUi")
        not in {
            "",
            "cart",
            "checkout",
            "empty_cart_redirect",
            "login_form",
            "product",
            "product_catalog",
            "reviewed_empty_state",
        }
        or not isinstance(value.get("failureCodes"), list)
        or len(value["failureCodes"]) > 32
        or len(value["failureCodes"]) != len(set(value["failureCodes"]))
        or any(
            not isinstance(code, str)
            or code not in COMMERCE_BROWSER_FAILURE_CODES
            for code in value["failureCodes"]
        )
    ):
        return False
    navigation = value.get("navigation")
    stylesheets = value.get("stylesheets")
    dom = value.get("dom")
    if (
        not isinstance(navigation, dict)
        or set(navigation) != {
            "status",
            "redirectStatus",
            "finalOrigin",
            "finalPath",
            "redirectCount",
        }
        or not isinstance(stylesheets, dict)
        or set(stylesheets) != {
            "externalCount",
            "loadedCount",
            "failedCount",
            "blockedCount",
        }
        or not isinstance(dom, dict)
        or len(dom) > 16
        or not set(dom).issubset(COMMERCE_BROWSER_DOM_KEYS)
    ):
        return False
    counts = [
        navigation.get("redirectCount"),
        *stylesheets.values(),
        *dom.values(),
    ]
    if any(
        type(count) is not int or count < 0 or count > 10_000
        for count in counts
    ):
        return False
    for status_name in ("status", "redirectStatus"):
        if (
            navigation.get(status_name) is not None
            and (
                type(navigation[status_name]) is not int
                or navigation[status_name] < 100
                or navigation[status_name] > 599
            )
        ):
            return False
    if (
        not isinstance(navigation.get("finalOrigin"), str)
        or not isinstance(navigation.get("finalPath"), str)
        or any(
            not isinstance(key, str)
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", key)
            for key in dom
        )
    ):
        return False
    if value["passed"]:
        expected_ui = {
            "account": {"login_form"},
            "cart": {"cart", "reviewed_empty_state"},
            "checkout": {"checkout", "empty_cart_redirect"},
            "product": {"product"},
            "shop": {"product_catalog"},
        }[mode]
        if (
            not value["operational"]
            or value["failureCodes"]
            or value["routeUi"] not in expected_ui
            or stylesheets["failedCount"] != 0
            or stylesheets["blockedCount"] != 0
        ):
            return False
        if source == "live":
            direct_navigation = (
                navigation["status"] == 200
                and navigation["redirectStatus"] is None
                and navigation["finalOrigin"] == EXPECTED_ORIGIN
                and navigation["finalPath"] == expected_path
                and navigation["redirectCount"] == 0
                and value["routeUi"] != "empty_cart_redirect"
            )
            checkout_redirect = (
                mode == "checkout"
                and value["routeUi"] == "empty_cart_redirect"
                and navigation["status"] == 200
                and navigation["redirectStatus"] == 302
                and navigation["finalOrigin"] == EXPECTED_ORIGIN
                and navigation["finalPath"] == "/cart/"
                and navigation["redirectCount"] == 1
            )
            if (
                not (direct_navigation or checkout_redirect)
                or stylesheets["loadedCount"]
                != stylesheets["externalCount"]
            ):
                return False
        else:
            if (
                navigation["status"] is not None
                or navigation["redirectStatus"] is not None
                or navigation["finalOrigin"] != EXPECTED_ORIGIN
                or navigation["finalPath"] != expected_path
                or navigation["redirectCount"] != 0
                or stylesheets["externalCount"] != 0
                or stylesheets["loadedCount"] != 0
            ):
                return False
        expected_dom_keys = {
            ("account", "login_form"): {
                "loginFormCount",
                "passwordCount",
                "submitCount",
                "usernameCount",
            },
            ("cart", "cart"): {
                "cartFormCount",
                "dataInputCount",
                "submitCount",
            },
            ("cart", "reviewed_empty_state"): {
                "cartFormCount",
                "dataInputCount",
                "submitCount",
            },
            ("checkout", "checkout"): {
                "checkoutFormCount",
                "dataInputCount",
                "submitCount",
            },
            ("checkout", "empty_cart_redirect"): {
                "cartFormCount",
                "dataInputCount",
                "submitCount",
            },
            ("product", "product"): {
                "actionFormCount",
                "addToCartCount",
                "identifierCount",
                "offerEvidenceCount",
                "positiveStockCount",
                "primaryActionCount",
                "primarySurfaceCount",
                "productCardCount",
                "stockCount",
                "submitCount",
                "titleCount",
                "validOfferEvidenceCount",
            },
            ("shop", "product_catalog"): {
                "productCardCount",
                "productLinkCount",
            },
        }[(mode, value["routeUi"])]
        if set(dom) != expected_dom_keys:
            return False
        if value["routeUi"] == "product" and (
            dom["primaryActionCount"] != 1
            or dom["primarySurfaceCount"] != 1
            or dom["addToCartCount"] < 1
            or dom["identifierCount"] < 1
            or dom["offerEvidenceCount"] != 1
            or dom["positiveStockCount"] != 1
            or dom["stockCount"] != 1
            or dom["submitCount"] < 1
            or dom["titleCount"] != 1
            or dom["validOfferEvidenceCount"] != 1
        ):
            return False
        if value["routeUi"] == "product_catalog" and (
            dom["productCardCount"] < 1
            or dom["productLinkCount"] < dom["productCardCount"]
        ):
            return False
        if value["routeUi"] == "login_form" and (
            dom["loginFormCount"] != 1
            or dom["usernameCount"] != 1
            or dom["passwordCount"] != 1
            or dom["submitCount"] < 1
        ):
            return False
        if value["routeUi"] in {"cart", "checkout"} and (
            dom[
                "cartFormCount"
                if value["routeUi"] == "cart"
                else "checkoutFormCount"
            ]
            != 1
            or dom["dataInputCount"] < 1
            or dom["submitCount"] < 1
        ):
            return False
        if value["routeUi"] in {
            "empty_cart_redirect",
            "reviewed_empty_state",
        } and mode in {"cart", "checkout"} and any(dom.values()):
            return False
    return True


def _run_commerce_browser_helper(
    *,
    mode: str,
    source: str,
    expected_path: str,
    input_json: str,
    chrome_path: str,
) -> dict[str, Any]:
    node_path = shutil.which("node")
    helper = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "qa"
        / "verify-commerce-dom.mjs"
    )
    if (
        node_path is None
        or not helper.is_file()
        or not Path(chrome_path).is_file()
    ):
        return commerce_browser_failure(
            mode=mode,
            source=source,
            code="browser_error",
        )
    creation_flags = 0
    popen_arguments: dict[str, Any] = {}
    if os.name == "nt":
        creation_flags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    else:
        popen_arguments["start_new_session"] = True
    profile = Path(
        tempfile.mkdtemp(prefix=COMMERCE_BROWSER_PROFILE_PREFIX)
    ).resolve()
    try:
        process = subprocess.Popen(
            [
                node_path,
                str(helper),
                "--chrome",
                chrome_path,
                "--profile",
                str(profile),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            cwd=str(Path(__file__).resolve().parents[1]),
            creationflags=creation_flags,
            env=commerce_browser_helper_environment(),
            **popen_arguments,
        )
    except OSError:
        remove_owned_commerce_browser_profile(profile)
        return commerce_browser_failure(
            mode=mode,
            source=source,
            code="browser_error",
        )
    try:
        output, _ = process.communicate(
            input=input_json,
            timeout=COMMERCE_BROWSER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        terminate_owned_browser_helper_tree(process)
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            terminate_owned_browser_helper_tree(process)
        remove_owned_commerce_browser_profile(profile)
        return commerce_browser_failure(
            mode=mode,
            source=source,
            code="operation_timeout",
        )
    if not remove_owned_commerce_browser_profile(profile):
        return commerce_browser_failure(
            mode=mode,
            source=source,
            code="cleanup_failed",
        )
    if len(output.encode("utf-8")) > 32 * 1024:
        return commerce_browser_failure(
            mode=mode,
            source=source,
            code="browser_error",
        )
    try:
        value = json.loads(output)
    except (json.JSONDecodeError, UnicodeError):
        return commerce_browser_failure(
            mode=mode,
            source=source,
            code="browser_error",
        )
    if not valid_commerce_browser_result(
        value,
        mode=mode,
        source=source,
        expected_path=expected_path,
    ):
        return commerce_browser_failure(
            mode=mode,
            source=source,
            code="invalid_result",
        )
    if process.returncode not in {0, 1}:
        return commerce_browser_failure(
            mode=mode,
            source=source,
            code="browser_error",
        )
    if value["operational"] and process.returncode != 0:
        return commerce_browser_failure(
            mode=mode,
            source=source,
            code="invalid_result",
        )
    if not value["operational"] and process.returncode != 1:
        return commerce_browser_failure(
            mode=mode,
            source=source,
            code="invalid_result",
        )
    return value


@functools.lru_cache(maxsize=128)
def _commerce_browser_proof_cached(
    mode: str,
    url: str,
    html: str,
    expected_path: str,
    product_id: int,
    chrome_path: str,
) -> dict[str, Any]:
    source = "live" if url else "fixture"
    payload: dict[str, Any] = {
        "mode": mode,
        "expectedOrigin": EXPECTED_ORIGIN,
        "expectedPath": expected_path,
    }
    if url:
        payload["url"] = url
    else:
        payload["html"] = html
    if mode == "product":
        payload["productId"] = product_id
    return _run_commerce_browser_helper(
        mode=mode,
        source=source,
        expected_path=expected_path,
        input_json=json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        chrome_path=chrome_path,
    )


def commerce_browser_proof(
    *,
    mode: str,
    expected_path: str,
    url: str = "",
    html: str = "",
    product_id: int = 0,
    chrome_path: Path | None = None,
) -> dict[str, Any]:
    source = "live" if url else "fixture"
    if (
        mode not in {"account", "cart", "checkout", "product", "shop"}
        or bool(url) == bool(html)
        or not expected_path.startswith("/")
        or "?" in expected_path
        or "#" in expected_path
        or (mode == "product" and product_id < 1)
        or (mode != "product" and product_id != 0)
    ):
        return commerce_browser_failure(
            mode=mode,
            source=source,
            code="invalid_input",
        )
    executable = chrome_path or find_commerce_chrome()
    if executable is None:
        return commerce_browser_failure(
            mode=mode,
            source=source,
            code="browser_error",
        )
    if url:
        try:
            parsed = validate_canonical_url(url)
        except ValueError:
            return commerce_browser_failure(
                mode=mode,
                source=source,
                code="invalid_live_url",
            )
        if (
            parsed.path != expected_path
            or not parsed.query
        ):
            return commerce_browser_failure(
                mode=mode,
                source=source,
                code="invalid_live_url",
            )
    return json.loads(
        json.dumps(
            _commerce_browser_proof_cached(
                mode,
                url,
                html,
                expected_path,
                product_id,
                str(executable),
            ),
            ensure_ascii=False,
        )
    )


def fetch(
    url: str,
    *,
    accept: str = "*/*",
    follow_redirects: bool = False,
    method: str = "GET",
    timeout: int = 45,
    no_cache: bool = True,
) -> HttpResult:
    validate_canonical_url(url)
    if follow_redirects:
        raise ValueError("Acceptance requests must not follow redirects.")
    if method not in {"GET", "HEAD"}:
        raise ValueError("Verification method must be GET or HEAD.")
    headers = {
        "Accept": accept,
        "User-Agent": USER_AGENT,
    }
    if no_cache:
        headers["Cache-Control"] = "no-cache"
    request = urllib.request.Request(url, headers=headers, method=method)
    started = time.perf_counter()
    try:
        response = NO_REDIRECTS.open(request, timeout=timeout)
        header_seconds = time.perf_counter() - started
        with response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            status = response.status
            response_headers = dict(response.headers.items())
            header_values = {
                key.lower(): response.headers.get_all(key) or []
                for key in response.headers.keys()
            }
            final_url = response.geturl()
    except urllib.error.HTTPError as error:
        header_seconds = time.perf_counter() - started
        body = error.read(MAX_RESPONSE_BYTES + 1)
        status = error.code
        response_headers = dict(error.headers.items())
        header_values = {
            key.lower(): error.headers.get_all(key) or []
            for key in error.headers.keys()
        }
        final_url = error.geturl()
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("Response exceeded the verification size limit.")
    if header_values.get("refresh"):
        raise ValueError(
            "Acceptance response contains a client-side Refresh header."
        )
    if final_url != url:
        raise ValueError("Response final URL differs from the requested URL.")
    total_seconds = time.perf_counter() - started
    lowered_headers = {key.lower(): value for key, value in response_headers.items()}
    content_type_values = header_values.get("content-type", [])
    content_type = (
        content_type_values[0]
        if len(content_type_values) == 1
        else ""
    )
    return HttpResult(
        status=status,
        content_type=content_type,
        headers=lowered_headers,
        body=body,
        final_url=final_url,
        header_seconds=header_seconds,
        total_seconds=total_seconds,
        header_values=header_values,
    )


def parse_html(text: str) -> HtmlFacts:
    facts = HtmlFacts()
    facts.feed(text)
    facts.close()
    return facts


def valid_html_document(facts: HtmlFacts) -> bool:
    return (
        facts.html_count == 1
        and facts.head_count == 1
        and facts.body_count == 1
        and facts.structure_errors == []
        and facts.base_hrefs == []
    )


def body_markup(text: str) -> str:
    lowered = text.lower()
    start = lowered.find("<body")
    if start < 0:
        raise ValueError("HTML has no body element.")
    start = lowered.find(">", start)
    end = lowered.find("</body>", start)
    if start < 0 or end < 0:
        raise ValueError("HTML body is not closed.")
    return text[start + 1 : end]


def relation_tokens(link: dict[str, str]) -> set[str]:
    return {token.lower() for token in link.get("rel", "").split()}


def directive_tokens(
    values: Iterable[str],
) -> set[str]:
    return {
        token.strip().lower()
        for value in values
        for token in value.split(",")
        if token.strip()
    }


def robots_directives_by_scope(
    facts: HtmlFacts,
    header_values: Iterable[str] = (),
) -> dict[str, set[str]]:
    crawler_names = set(SEARCH_CRAWLERS) - {"*"}
    scoped: dict[str, set[str]] = {
        crawler: set()
        for crawler in SEARCH_CRAWLERS
    }
    scoped["*"].update(directive_tokens(facts.meta_values("robots")))
    for crawler in crawler_names:
        scoped[crawler].update(
            directive_tokens(facts.meta_values(crawler))
        )

    for value in header_values:
        current_scope = "*"
        for raw_token in value.split(","):
            token = raw_token.strip().lower()
            token_prefix, token_separator, token_remainder = (
                token.partition(":")
            )
            if (
                token_separator
                and token_prefix.strip() in crawler_names
            ):
                if (
                    not token_remainder.strip()
                    or token_remainder.lstrip().startswith(":")
                ):
                    raise ValueError(
                        "Malformed crawler-scoped X-Robots-Tag directive."
                    )
                current_scope = token_prefix.strip()
                scoped[current_scope].update(
                    directive_tokens([token_remainder])
                )
            elif token:
                scoped[current_scope].add(token)
    return scoped


def effective_robots_directives(
    scoped: dict[str, set[str]],
    crawler: str,
) -> set[str]:
    return set(scoped.get("*", set())) | set(scoped.get(crawler, set()))


def all_effective_robots_directives(
    scoped: dict[str, set[str]],
) -> dict[str, set[str]]:
    return {
        crawler: effective_robots_directives(scoped, crawler)
        for crawler in SEARCH_CRAWLERS
        if crawler != "*"
    }


def directives_allow_indexing(directives: set[str]) -> bool:
    if not directives.isdisjoint({"noindex", "nofollow", "none"}):
        return False
    return not any(
        token.partition(":")[0].strip()
        in {"unavailable_after", "unavailable-after"}
        for token in directives
    )


def robots_directives(
    facts: HtmlFacts,
    header_values: Iterable[str] = (),
) -> set[str]:
    scoped = robots_directives_by_scope(facts, header_values)
    return set().union(*scoped.values())


def uncached_response_evidence(
    response: HttpResult,
) -> tuple[bool, dict[str, Any]]:
    cache_control_values = response.values("cache-control")
    directives = directive_tokens(cache_control_values)
    conflicting_directives = sorted(
        directive
        for directive in directives
        if (
            directive in {"immutable", "public"}
            or (
                directive.startswith(("max-age=", "s-maxage="))
                and directive not in {"max-age=0", "s-maxage=0"}
            )
        )
    )
    age_values = response.values("age")
    ages_valid = all(
        re.fullmatch(r"\d+", value.strip()) is not None
        and int(value.strip()) == 0
        for value in age_values
    )
    cache_status_values = [
        value
        for name in (
            "cf-cache-status",
            "x-cache",
            "x-litespeed-cache",
        )
        for value in response.values(name)
    ]
    cache_hits = sorted(
        value
        for value in cache_status_values
        if re.search(r"\bhit\b", value, re.I) is not None
    )
    passed = (
        {"max-age=0", "no-cache", "no-store"}.issubset(directives)
        and conflicting_directives == []
        and ages_valid
        and cache_hits == []
    )
    return passed, {
        "age": age_values,
        "cache_control": cache_control_values,
        "cache_directives": sorted(directives),
        "cache_hits": cache_hits,
        "conflicting_cache_directives": conflicting_directives,
    }


def noindex_response_evidence(
    facts: HtmlFacts,
    response: HttpResult,
) -> tuple[bool, dict[str, Any]]:
    scoped = robots_directives_by_scope(
        facts,
        response.values("x-robots-tag"),
    )
    effective = all_effective_robots_directives(scoped)
    disallowed = {"index", "nofollow", "none"}
    passed = (
        "noindex" in scoped["*"]
        and scoped["*"].isdisjoint(disallowed)
        and all(
            "noindex" in directives
            and directives.isdisjoint(disallowed)
            for directives in effective.values()
        )
    )
    return passed, {
        "global": sorted(scoped["*"]),
        "effective": {
            crawler: sorted(directives)
            for crawler, directives in effective.items()
        },
    }


def public_language_findings(facts: HtmlFacts) -> list[str]:
    surface = " ".join(
        [
            facts.title,
            facts.body_text,
            *facts.visible_attributes,
            *[
                value
                for values in facts.metas.values()
                for value in values
            ],
            *[
                script["content"]
                for script in facts.scripts
                if script["type"] == "application/ld+json"
            ],
        ]
    )
    return [
        label
        for label, pattern in FORBIDDEN_PUBLIC_PATTERNS
        if pattern.search(surface)
    ]


def value_language_findings(value: Any) -> list[str]:
    strings: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, str):
            strings.append(item)
        elif isinstance(item, dict):
            for key, child in item.items():
                strings.append(str(key))
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    surface = " ".join(strings)
    return [
        label
        for label, pattern in FORBIDDEN_PUBLIC_PATTERNS
        if pattern.search(surface)
    ]


def legacy_text_findings(value: Any) -> list[str]:
    strings: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, str):
            strings.append(item)
        elif isinstance(item, dict):
            for key, child in item.items():
                strings.append(str(key))
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    normalized = " ".join(" ".join(strings).lower().split())
    return [
        fragment
        for fragment in LEGACY_TITLE_FRAGMENTS
        if fragment in normalized
    ]


def matches_versioned_asset(
    url: str,
    *,
    expected_path: str,
    expected_version: str,
) -> bool:
    parsed = urllib.parse.urlsplit(url)
    expected_origin = urllib.parse.urlsplit(EXPECTED_ORIGIN)
    if parsed.fragment:
        return False
    if (
        parsed.scheme
        and (
            parsed.scheme.lower() != expected_origin.scheme.lower()
            or parsed.netloc.lower() != expected_origin.netloc.lower()
        )
    ):
        return False
    if parsed.netloc and not parsed.scheme:
        if parsed.netloc.lower() != expected_origin.netloc.lower():
            return False
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    return (
        parsed.path == expected_path
        and set(query) == {"ver"}
        and query.get("ver") == [expected_version]
    )


def json_ld_documents(
    facts: HtmlFacts,
) -> tuple[list[dict[str, Any]], list[str]]:
    documents: list[dict[str, Any]] = []
    errors: list[str] = []
    for script in facts.scripts:
        if (
            script["type"] != "application/ld+json"
            or not script.get("in_head")
        ):
            continue
        try:
            document = json.loads(script["content"])
        except json.JSONDecodeError:
            errors.append("invalid_json")
            continue
        if not isinstance(document, dict):
            errors.append("non_object_document")
            continue
        documents.append(document)
    return documents, errors


def json_ld_entities(
    facts: HtmlFacts,
) -> tuple[list[dict[str, Any]], int]:
    entities: list[dict[str, Any]] = []
    documents, document_errors = json_ld_documents(facts)
    for document in documents:
        graph = document.get("@graph")
        if isinstance(graph, list):
            entities.extend(
                entity
                for entity in graph
                if isinstance(entity, dict)
            )
    return entities, len(document_errors)


def entity_types(entity: dict[str, Any]) -> set[str]:
    value = entity.get("@type")
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {str(item) for item in value}
    return set()


def json_ld_types(facts: HtmlFacts) -> set[str]:
    entities, invalid_documents = json_ld_entities(facts)
    types = {
        item_type
        for entity in entities
        for item_type in entity_types(entity)
    }
    if invalid_documents:
        types.add("__INVALID_JSON_LD__")
    return types


def validate_home_schema(facts: HtmlFacts) -> list[str]:
    documents, document_errors = json_ld_documents(facts)
    errors: list[str] = []
    errors.extend(document_errors)
    if len(documents) != 1:
        errors.append("document_count")
        entities: list[dict[str, Any]] = []
    else:
        document = documents[0]
        if set(document) != {"@context", "@graph"}:
            errors.append("document_properties")
        if document.get("@context") != "https://schema.org":
            errors.append("document_context")
        graph = document.get("@graph")
        if (
            not isinstance(graph, list)
            or len(graph) != 2
            or any(not isinstance(item, dict) for item in graph)
        ):
            errors.append("document_graph")
            entities = []
        else:
            entities = graph

    websites = [
        entity
        for entity in entities
        if "WebSite" in entity_types(entity)
    ]
    webpages = [
        entity
        for entity in entities
        if "WebPage" in entity_types(entity)
    ]
    if len(websites) != 1:
        errors.append("website_count")
    if len(webpages) != 1:
        errors.append("webpage_count")

    website_id = EXPECTED_ORIGIN + "/#website"
    webpage_id = EXPECTED_ORIGIN + "/#webpage"
    if len(websites) == 1:
        website = websites[0]
        allowed_website_properties = {
            "@id",
            "@type",
            "description",
            "inLanguage",
            "name",
            "url",
        }
        if set(website) != allowed_website_properties:
            errors.append("website_properties")
        if website.get("@type") != "WebSite":
            errors.append("website_type")
        website_expected = {
            "@id": website_id,
            "url": EXPECTED_ORIGIN + "/",
            "name": "RobbottX",
            "description": HOME_DESCRIPTION,
            "inLanguage": "en-US",
        }
        for key, expected in website_expected.items():
            if website.get(key) != expected:
                errors.append(f"website_{key}")
    if len(webpages) == 1:
        webpage = webpages[0]
        allowed_webpage_properties = {
            "@id",
            "@type",
            "description",
            "inLanguage",
            "isPartOf",
            "name",
            "url",
        }
        if set(webpage) != allowed_webpage_properties:
            errors.append("webpage_properties")
        if webpage.get("@type") != "WebPage":
            errors.append("webpage_type")
        webpage_expected = {
            "@id": webpage_id,
            "url": EXPECTED_ORIGIN + "/",
            "name": HOME_SOCIAL_TITLE,
            "description": HOME_DESCRIPTION,
            "inLanguage": "en-US",
        }
        for key, expected in webpage_expected.items():
            if webpage.get(key) != expected:
                errors.append(f"webpage_{key}")
        if webpage.get("isPartOf") != {"@id": website_id}:
            errors.append("webpage_isPartOf")
    return errors


def parse_xml_locations(text: str) -> tuple[str, list[str]]:
    root = ET.fromstring(text)
    expected_prefix = "{" + SITEMAP_NAMESPACE + "}"
    if not root.tag.startswith(expected_prefix):
        raise ValueError("Sitemap uses the wrong XML namespace.")
    if root.attrib:
        raise ValueError("Sitemap root has unexpected attributes.")
    root_name = root.tag.removeprefix(expected_prefix)
    if root_name not in {"sitemapindex", "urlset"}:
        raise ValueError("Unexpected sitemap root element.")
    expected_child = "sitemap" if root_name == "sitemapindex" else "url"
    allowed_entry_children = (
        {"loc", "lastmod"}
        if root_name == "sitemapindex"
        else {"loc", "lastmod", "changefreq", "priority"}
    )
    locations: list[str] = []
    for child in list(root):
        if child.tag != expected_prefix + expected_child:
            raise ValueError("Sitemap has an unexpected direct child.")
        if child.attrib:
            raise ValueError("Sitemap entry has unexpected attributes.")
        for element in list(child):
            if (
                not element.tag.startswith(expected_prefix)
                or element.tag.removeprefix(expected_prefix)
                not in allowed_entry_children
                or list(element)
            ):
                raise ValueError("Sitemap entry has an unexpected child.")
        locs = [
            element
            for element in list(child)
            if element.tag == expected_prefix + "loc"
        ]
        if (
            len(locs) != 1
            or not isinstance(locs[0].text, str)
            or not locs[0].text.strip()
        ):
            raise ValueError("Sitemap entry lacks one direct location.")
        locations.append(locs[0].text.strip())
    if not locations:
        raise ValueError("Sitemap contains no entries.")
    if len(locations) != len(set(locations)):
        raise ValueError("Sitemap contains duplicate locations.")
    return root_name, locations


def feed_legacy_evidence(root: ET.Element) -> list[dict[str, str]]:
    leaks: list[dict[str, str]] = []
    for element in root.iter():
        name = element.tag.rsplit("}", 1)[-1].lower()
        values: list[str] = []
        if name in {"link", "guid", "id"}:
            if isinstance(element.text, str) and element.text.strip():
                values.append(element.text.strip())
            href = element.attrib.get("href", "").strip()
            if href:
                values.append(href)
            for value in values:
                if legacy_url(value):
                    leaks.append({"kind": name, "value": value})
        if name == "title" and isinstance(element.text, str):
            normalized = " ".join(element.text.lower().split())
            for fragment in LEGACY_TITLE_FRAGMENTS:
                if fragment in normalized:
                    leaks.append(
                        {"kind": "title", "value": element.text.strip()}
                    )
                    break
    return leaks


def parse_robots_policy(text: str) -> dict[str, Any]:
    groups: list[tuple[list[str], list[tuple[str, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[str, str]] = []
    sitemaps: list[str] = []

    def commit_group() -> None:
        nonlocal agents, rules
        if agents:
            groups.append((agents, rules))
        agents = []
        rules = []

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        name, value = line.split(":", 1)
        name = name.strip().lower()
        value = value.strip()
        if name == "user-agent":
            if rules:
                commit_group()
            agents.append(value.lower())
        elif name == "sitemap":
            sitemaps.append(value)
        elif agents:
            rules.append((name, value))
    commit_group()

    def pattern_matches_path(pattern: str, path: str) -> bool:
        if not pattern:
            return False
        anchored = pattern.endswith("$")
        core = pattern[:-1] if anchored else pattern
        expression = "^" + re.escape(core).replace(r"\*", ".*")
        if anchored:
            expression += "$"
        return re.match(expression, path) is not None

    def path_allowed(crawler: str, path: str) -> bool:
        matching_groups: list[
            tuple[int, list[tuple[str, str]]]
        ] = []
        for group_agents, group_rules in groups:
            matched_agents = [
                agent
                for agent in group_agents
                if agent == "*" or agent == crawler
            ]
            if not matched_agents:
                continue
            specificity = max(
                0 if agent == "*" else len(agent)
                for agent in matched_agents
            )
            matching_groups.append((specificity, group_rules))
        if not matching_groups:
            return True
        best_agent_specificity = max(
            specificity
            for specificity, _rules in matching_groups
        )
        candidate_rules: list[tuple[int, bool]] = []
        for specificity, group_rules in matching_groups:
            if specificity != best_agent_specificity:
                continue
            for name, pattern in group_rules:
                if (
                    name not in {"allow", "disallow"}
                    or not pattern_matches_path(pattern, path)
                ):
                    continue
                rule_specificity = len(
                    pattern.rstrip("$").replace("*", "")
                )
                candidate_rules.append(
                    (rule_specificity, name == "allow")
                )
        if not candidate_rules:
            return True
        best_rule_specificity = max(
            specificity
            for specificity, _allowed in candidate_rules
        )
        winners = [
            allowed
            for specificity, allowed in candidate_rules
            if specificity == best_rule_specificity
        ]
        return any(winners)

    public_path_access = {
        crawler: {
            path: path_allowed(crawler, path)
            for path in PUBLIC_ROBOTS_PATHS
        }
        for crawler in SEARCH_CRAWLERS
    }
    root_access = {
        crawler: access["/"]
        for crawler, access in public_path_access.items()
    }
    blocked_agents = sorted(
        crawler
        for crawler, allowed in root_access.items()
        if not allowed
    )
    blocked_public_paths = sorted(
        {
            path
            for access in public_path_access.values()
            for path, allowed in access.items()
            if not allowed
        }
    )
    return {
        "blocks_root": bool(blocked_agents),
        "blocked_agents": blocked_agents,
        "blocked_public_paths": blocked_public_paths,
        "public_path_access": public_path_access,
        "root_access": root_access,
        "sitemaps": list(dict.fromkeys(sitemaps)),
    }


def normalized_local_path(url: str) -> str | None:
    parsed = urllib.parse.urlsplit(url)
    expected_origin = urllib.parse.urlsplit(EXPECTED_ORIGIN)
    if parsed.netloc and parsed.netloc.lower() != expected_origin.netloc.lower():
        return None
    return "/" + "/".join(
        segment
        for segment in urllib.parse.unquote(parsed.path).lower().split("/")
        if segment
    )


def inactive_commerce_url(url: str) -> bool:
    normalized = normalized_local_path(url)
    return (
        normalized in INACTIVE_COMMERCE_NORMALIZED_PATHS
        or (
            isinstance(normalized, str)
            and (
                normalized == "/product"
                or normalized.startswith("/product/")
            )
        )
    )


def inactive_product_sitemap_url(url: str) -> bool:
    lowered = url.lower()
    return any(
        marker in lowered
        for marker in INACTIVE_PRODUCT_SITEMAP_MARKERS
    )


def legacy_url(url: str) -> bool:
    normalized = normalized_local_path(url)
    if normalized is None:
        return False
    if normalized in {
        "/hello-world",
        "/sample-page",
        "/robots-catalog",
        "/robot",
        "/robots",
        "/product",
        "/category/uncategorized",
        *INACTIVE_COMMERCE_NORMALIZED_PATHS,
    }:
        return True
    segments = normalized.strip("/").split("/")
    return (
        len(segments) == 2
        and segments[0] in {"author", "product", "robot"}
        and bool(segments[1])
    )


def verify_health(report: Report) -> None:
    try:
        health_url = build_url("/wp-json/robbottx/v1/healthcheck")
        response = fetch(
            health_url,
            accept="application/json",
        )
        validate_content_type(
            response,
            allowed_media_types={"application/json"},
            allowed_charsets={None, "utf-8"},
        )
        payload = json.loads(response.text())
        final = urllib.parse.urlsplit(response.final_url)
        expected_fields = {
            "last_reviewed",
            "record_hash",
            "record_id",
            "record_state",
            "status",
            "version",
        }
        passed = (
            response.status == 200
            and is_json_media_type(response.content_type)
            and isinstance(payload, dict)
            and set(payload) == expected_fields
            and final.scheme == "https"
            and final.netloc == urllib.parse.urlsplit(EXPECTED_ORIGIN).netloc
            and final.path == "/wp-json/robbottx/v1/healthcheck"
            and payload.get("status") == "ok"
            and payload.get("version") == report.plugin_version
            and payload.get("record_hash") == report.record_hash
            and payload.get("record_id") == EXPECTED_RECORD_ID
            and payload.get("record_state") == "documentation_reviewed"
            and payload.get("last_reviewed") == EXPECTED_REVIEW_DATE
            and value_language_findings(payload) == []
        )
        report.add(
            "runtime.healthcheck",
            passed,
            "Public healthcheck identifies the reviewed release and record.",
            evidence={
                "http_status": response.status,
                "version": payload.get("version"),
                "record_id": payload.get("record_id"),
                "record_hash": payload.get("record_hash"),
                "record_state": payload.get("record_state"),
                "last_reviewed": payload.get("last_reviewed"),
                "content_type": response.content_type,
                "final_path": final.path,
            },
        )
    except Exception as error:
        report.exception(
            "runtime.healthcheck",
            "Public healthcheck could not be verified.",
            error,
        )


def verify_home(report: Report, previous_plugin_version: str) -> None:
    try:
        response = fetch(
            build_url("/"),
            accept="text/html",
        )
        validate_content_type(
            response,
            allowed_media_types={"text/html"},
            allowed_charsets={None, "utf-8"},
        )
        text = response.text()
        facts = parse_html(text)
    except Exception as error:
        report.exception(
            "home.fetch",
            "Homepage could not be parsed.",
            error,
        )
        return

    report.add(
        "home.http",
        response.status == 200 and is_html_media_type(response.content_type),
        "Homepage returns HTML with HTTP 200.",
        evidence={
            "http_status": response.status,
            "content_type": response.content_type,
            "bytes": len(response.body),
        },
    )
    new_marker = f"<!-- robbottx-core:{report.plugin_version} -->"
    old_marker = f"<!-- robbottx-core:{previous_plugin_version} -->"
    marker_versions = [
        match.group(1)
        for comment in facts.body_comments
        if (
            match := re.fullmatch(
                r"robbottx-core:(\d+\.\d+\.\d+)",
                comment,
            )
        )
    ]
    report.add(
        "home.plugin_marker",
        marker_versions == [report.plugin_version]
        and new_marker.strip("<!- >") in facts.body_comments
        and old_marker.strip("<!- >") not in facts.body_comments,
        "Rendered body contains exactly one current plugin marker.",
        evidence={
            "marker_versions": marker_versions,
        },
    )

    canonical_urls = [
        link.get("href", "")
        for link in facts.links
        if "canonical" in relation_tokens(link)
    ]
    report.add(
        "home.canonical",
        canonical_urls == [EXPECTED_ORIGIN + "/"],
        "Homepage has one canonical URL.",
        evidence={"canonical_urls": canonical_urls},
    )
    report.add(
        "home.title",
        facts.title == HOME_DOCUMENT_TITLE,
        "Homepage title uses established RobbottX language.",
        evidence={"title": facts.title},
    )
    viewports = facts.meta_values("viewport")
    report.add(
        "home.document_structure",
        valid_html_document(facts)
        and facts.title_count == 1,
        "Homepage has one ordered document structure without a base override.",
        evidence={
            "html_count": facts.html_count,
            "head_count": facts.head_count,
            "body_count": facts.body_count,
            "title_count": facts.title_count,
            "base_hrefs": facts.base_hrefs,
            "structure_errors": facts.structure_errors,
        },
    )
    report.add(
        "home.document_context",
        facts.html_language == "en-US"
        and viewports == ["width=device-width, initial-scale=1"],
        "Homepage declares the English interface and mobile viewport.",
        evidence={
            "language": facts.html_language,
            "viewports": viewports,
        },
    )
    home_scoped_robots = robots_directives_by_scope(
        facts,
        response.values("x-robots-tag"),
    )
    home_effective_robots = all_effective_robots_directives(
        home_scoped_robots
    )
    report.add(
        "home.indexability",
        all(
            directives_allow_indexing(directives)
            for directives in home_effective_robots.values()
        )
        and directives_allow_indexing(home_scoped_robots["*"]),
        "Homepage remains indexable for every reviewed crawler.",
        evidence={
            "global": sorted(home_scoped_robots["*"]),
            "effective": {
                crawler: sorted(directives)
                for crawler, directives in home_effective_robots.items()
            },
        },
    )
    descriptions = facts.meta_values("description")
    report.add(
        "home.description",
        descriptions == [HOME_DESCRIPTION],
        "Homepage has one deterministic description.",
        evidence={"descriptions": descriptions},
    )

    social_expectations = {
        "og:title": HOME_SOCIAL_TITLE,
        "og:type": "website",
        "og:url": EXPECTED_ORIGIN + "/",
        "og:description": HOME_DESCRIPTION,
        "og:site_name": "RobbottX",
        "og:locale": "en_US",
        "twitter:card": "summary",
        "twitter:title": HOME_SOCIAL_TITLE,
        "twitter:description": HOME_DESCRIPTION,
    }
    social_mismatches = {
        key: facts.meta_values(key)
        for key, expected in social_expectations.items()
        if facts.meta_values(key) != [expected]
    }
    report.add(
        "home.social_metadata",
        social_mismatches == {},
        "Open Graph and summary-card metadata are deterministic.",
        evidence={"mismatches": social_mismatches},
    )

    schema_types = json_ld_types(facts)
    schema_errors = validate_home_schema(facts)
    report.add(
        "home.structured_data",
        schema_errors == [],
        "Homepage JSON-LD exactly identifies the site and page relationship.",
        evidence={
            "types": sorted(schema_types),
            "errors": schema_errors,
        },
    )

    required_text = (
        "Robotics, mapped to evidence.",
        "Featured system configuration",
        EXPECTED_CONFIGURATION_NAME,
        "Documentation reviewed",
        "Source documents 5",
        "Sourced technical claims 13",
        "System relationships 6",
        f"Last reviewed {EXPECTED_REVIEW_DATE}",
        "Manufacturer-published specifications",
        "Requires application validation",
        "Compatibility across 10 technical areas.",
        "Technical documents and sources",
        EXPECTED_RECORD_ID,
    )
    missing_text = [value for value in required_text if value not in facts.body_text]
    report.add(
        "home.golden_slice",
        missing_text == []
        and facts.specification_count == EXPECTED_SPECIFICATION_COUNT
        and facts.source_count == EXPECTED_SOURCE_COUNT
        and facts.class_counts["rbtx-compatibility-card"] == 10
        and facts.class_counts["rbtx-state--conditional"] == 1
        and facts.class_counts["rbtx-state--conflicting_evidence"] == 1
        and (
            facts.class_counts[
                "rbtx-state--engineering_review_required"
            ]
            == 2
        )
        and facts.class_counts["rbtx-state--not_applicable"] == 1
        and facts.class_counts["rbtx-state--unverified"] == 4
        and facts.class_counts["rbtx-state--version_constrained"] == 1,
        "The complete featured configuration renders in the public body.",
        evidence={
            "missing_text": missing_text,
            "specifications": facts.specification_count,
            "sources": facts.source_count,
            "compatibility_cards": facts.class_counts[
                "rbtx-compatibility-card"
            ],
            "compatibility_states": {
                "conditional": facts.class_counts[
                    "rbtx-state--conditional"
                ],
                "conflicting_evidence": facts.class_counts[
                    "rbtx-state--conflicting_evidence"
                ],
                "engineering_review_required": facts.class_counts[
                    "rbtx-state--engineering_review_required"
                ],
                "not_applicable": facts.class_counts[
                    "rbtx-state--not_applicable"
                ],
                "unverified": facts.class_counts[
                    "rbtx-state--unverified"
                ],
                "version_constrained": facts.class_counts[
                    "rbtx-state--version_constrained"
                ],
            },
        },
    )

    report.add(
        "home.landmarks",
        facts.h1_count == 1
        and facts.main_count == 1
        and "main-content" in facts.element_ids
        and "#main-content" in facts.body_hrefs,
        "Homepage has one H1, one main landmark, and a working skip target.",
        evidence={
            "h1_count": facts.h1_count,
            "main_count": facts.main_count,
            "main_target_present": "main-content" in facts.element_ids,
            "skip_href_present": "#main-content" in facts.body_hrefs,
        },
    )

    home_language_findings = public_language_findings(facts)
    report.add(
        "home.public_language",
        home_language_findings == [],
        "Rendered public copy passes the established-language boundary.",
        evidence={"findings": home_language_findings},
    )

    theme_styles = [
        link.get("href", "")
        for link in facts.links
        if "stylesheet" in relation_tokens(link)
        and "/wp-content/themes/robbottx/style.css" in link.get("href", "")
    ]
    icon_records = [
        link
        for link in facts.links
        if relation_tokens(link)
        & {"icon", "apple-touch-icon", "mask-icon"}
        and link.get("href", "")
    ]
    all_icon_links = [link["href"] for link in icon_records]
    fallback_records = [
        link
        for link in icon_records
        if urllib.parse.urlsplit(link["href"]).path
        == "/wp-content/themes/robbottx/assets/favicon.svg"
    ]
    favicon_links = [link["href"] for link in fallback_records]
    expected_origin = urllib.parse.urlsplit(EXPECTED_ORIGIN)
    configured_records: list[dict[str, str]] = []
    configured_icon_links: list[str] = []
    for link in icon_records:
        icon_url = link["href"]
        resolved_url = urllib.parse.urljoin(EXPECTED_ORIGIN + "/", icon_url)
        try:
            resolved_icon = validate_canonical_url(resolved_url)
        except ValueError:
            continue
        if (
            resolved_icon.netloc == expected_origin.netloc
            and resolved_icon.path
            != "/wp-content/themes/robbottx/assets/favicon.svg"
        ):
            configured_records.append(link)
            configured_icon_links.append(resolved_url)
    fallback_icon_valid = (
        len(favicon_links) == 1
        and matches_versioned_asset(
            favicon_links[0],
            expected_path="/wp-content/themes/robbottx/assets/favicon.svg",
            expected_version=report.theme_version,
        )
        and all_icon_links == favicon_links
    )
    configured_icon_valid = (
        favicon_links == []
        and configured_icon_links != []
        and len(configured_icon_links) == len(icon_records)
        and set(configured_icon_links)
        == set(report.configured_site_icon_urls)
        and len(configured_icon_links)
        == len(report.configured_site_icon_urls)
    )
    favicon_valid = (
        fallback_icon_valid
        if report.expect_fallback_favicon
        else configured_icon_valid
    )
    stylesheet_valid = (
        len(theme_styles) == 1
        and matches_versioned_asset(
            theme_styles[0],
            expected_path="/wp-content/themes/robbottx/style.css",
            expected_version=report.theme_version,
        )
    )
    selected_icon_records = (
        fallback_records
        if report.expect_fallback_favicon
        else configured_records
    )
    asset_fetches: list[dict[str, Any]] = []
    assets_load = stylesheet_valid and favicon_valid
    if assets_load:
        for asset_kind, asset_url in [
            ("stylesheet", theme_styles[0]),
            *[
                ("icon", icon["href"])
                for icon in selected_icon_records
            ],
        ]:
            resolved_url = urllib.parse.urljoin(
                EXPECTED_ORIGIN + "/",
                asset_url,
            )
            try:
                asset_response = fetch(
                    resolved_url,
                    accept=(
                        "text/css"
                        if asset_kind == "stylesheet"
                        else (
                            "image/avif, image/webp, image/png, image/jpeg, "
                            "image/gif, image/svg+xml"
                        )
                    ),
                    timeout=30,
                )
                if asset_kind == "stylesheet":
                    actual_media = validate_content_type(
                        asset_response,
                        allowed_media_types={"text/css"},
                        allowed_charsets={None, "utf-8"},
                    )
                    media_valid = actual_media == "text/css"
                    declared_type = ""
                else:
                    actual_media = validate_content_type(
                        asset_response,
                        allowed_media_types={
                            "image/avif",
                            "image/gif",
                            "image/jpeg",
                            "image/png",
                            "image/svg+xml",
                            "image/webp",
                        },
                        allowed_charsets=(
                            {None, "utf-8"}
                            if media_type(asset_response.content_type)
                            == "image/svg+xml"
                            else {None}
                        ),
                    )
                    selected_record = next(
                        icon
                        for icon in selected_icon_records
                        if icon["href"] == asset_url
                    )
                    declared_type = selected_record.get("type", "").lower()
                    media_valid = (
                        not declared_type
                        or declared_type == actual_media
                    )
                    media_valid = (
                        media_valid
                        and valid_image_payload(
                            asset_response,
                            actual_media,
                        )
                    )
                loaded = (
                    asset_response.status == 200
                    and asset_response.final_url == resolved_url
                    and media_valid
                )
                assets_load = assets_load and loaded
                asset_fetches.append(
                    {
                        "kind": asset_kind,
                        "url": resolved_url,
                        "status": asset_response.status,
                        "content_type": asset_response.content_type,
                        "declared_type": declared_type,
                        "final_url": asset_response.final_url,
                    }
                )
            except Exception as error:
                assets_load = False
                asset_fetches.append(
                    {
                        "kind": asset_kind,
                        "url": resolved_url,
                        "error_type": type(error).__name__,
                    }
                )
    report.add(
        "home.theme_assets",
        stylesheet_valid and favicon_valid and assets_load,
        "Theme stylesheet and the selected favicon mode match the release.",
        evidence={
            "stylesheets": theme_styles,
            "all_icons": all_icon_links,
            "configured_icons": configured_icon_links,
            "expected_configured_icons": list(
                report.configured_site_icon_urls
            ),
            "fallback_icons": favicon_links,
            "fetches": asset_fetches,
            "favicon_mode": (
                "theme_fallback"
                if report.expect_fallback_favicon
                else "configured_site_icon"
            ),
        },
    )

    asset_urls = facts.asset_urls()
    commerce_assets = [
        url
        for url in asset_urls
        if any(
            token in url.lower()
            for token in ("woocommerce", "wc-block", "site-reviews")
        )
    ]
    expected_asset_origin = urllib.parse.urlsplit(EXPECTED_ORIGIN)
    remote_assets = [
        url
        for url in asset_urls
        if (
            (resolved := urllib.parse.urlsplit(
                urllib.parse.urljoin(EXPECTED_ORIGIN + "/", url)
            )).scheme != "https"
            or resolved.netloc != expected_asset_origin.netloc
        )
    ]
    report.add(
        "home.asset_discipline",
        commerce_assets == [] and remote_assets == [],
        "Homepage omits unused commerce assets and remote dependencies.",
        evidence={
            "unexpected_assets": commerce_assets,
            "remote_assets": remote_assets,
        },
    )

    broken_images: list[dict[str, Any]] = []
    expected_origin = urllib.parse.urlsplit(EXPECTED_ORIGIN)
    if len(facts.image_sources) > 100:
        broken_images.append(
            {
                "error": "image_bound_exceeded",
                "count": len(facts.image_sources),
            }
        )
    for source in facts.image_sources[:100]:
        try:
            if not source:
                broken_images.append({"url": "", "error": "empty_source"})
                continue
            image_url = urllib.parse.urljoin(EXPECTED_ORIGIN + "/", source)
            parsed_image = urllib.parse.urlsplit(image_url)
            if (
                parsed_image.scheme != "https"
                or parsed_image.netloc != expected_origin.netloc
            ):
                broken_images.append(
                    {"url": source, "error": "external_origin"}
                )
                continue
            image = fetch(
                image_url,
                accept=(
                    "image/avif, image/webp, image/png, image/jpeg, "
                    "image/gif, image/svg+xml"
                ),
                timeout=30,
                no_cache=False,
            )
            image_media = validate_content_type(
                image,
                allowed_media_types={
                    "image/avif",
                    "image/gif",
                    "image/jpeg",
                    "image/png",
                    "image/svg+xml",
                    "image/webp",
                },
                allowed_charsets=(
                    {None, "utf-8"}
                    if media_type(image.content_type) == "image/svg+xml"
                    else {None}
                ),
            )
            if (
                image.status != 200
                or image.final_url != image_url
                or not image_media.startswith("image/")
            ):
                broken_images.append(
                    {
                        "url": image_url,
                        "status": image.status,
                        "content_type": image.content_type,
                    }
                )
        except Exception as error:
            broken_images.append(
                {"url": source, "error_type": type(error).__name__}
            )
    report.add(
        "home.images",
        broken_images == [],
        "Homepage image references are either absent or load successfully.",
        evidence={
            "image_count": len(facts.image_sources),
            "broken": broken_images,
        },
    )


def verify_route_inventory(report: Report) -> None:
    try:
        response = fetch(
            build_url("/wp-json/"),
            accept="application/json",
        )
        validate_content_type(
            response,
            allowed_media_types={"application/json"},
            allowed_charsets={None, "utf-8"},
        )
        payload = json.loads(response.text())
        routes = payload.get("routes", {})
        route_names = list(routes) if isinstance(routes, dict) else []
        temporary = [
            route
            for route in route_names
            if route.startswith("/agentdeploy/v1/")
            or route.startswith("/agenttheme/v1/")
            or route.startswith("/agentconfigure/v1/")
        ]
        report.add(
            "runtime.route_cleanup",
            response.status == 200
            and is_json_media_type(response.content_type)
            and isinstance(routes, dict)
            and temporary == []
            and "/robbottx/v1/healthcheck" in routes,
            "Temporary deploy routes are absent and the public health route remains.",
            evidence={
                "http_status": response.status,
                "temporary_routes": temporary,
                "health_route_present": "/robbottx/v1/healthcheck" in route_names,
            },
        )
    except Exception as error:
        report.exception(
            "runtime.route_cleanup",
            "REST route cleanup could not be proven.",
            error,
        )


def verify_rest(report: Report) -> None:
    collection_results: list[dict[str, Any]] = []
    collection_passed = True
    for path in LEGACY_REST_COLLECTIONS:
        try:
            response = fetch(
                build_url(path),
                accept="application/json",
            )
            validate_content_type(
                response,
                allowed_media_types={"application/json"},
                allowed_charsets={None, "utf-8"},
            )
            payload = json.loads(response.text())
            total = response.single_header("x-wp-total")
            passed = (
                response.status == 200
                and is_json_media_type(response.content_type)
                and payload == []
                and total == "0"
            )
            collection_passed = collection_passed and passed
            collection_results.append(
                {
                    "path": urllib.parse.urlsplit(path).path,
                    "status": response.status,
                    "records": len(payload) if isinstance(payload, list) else None,
                    "total": total,
                    "content_type": response.content_type,
                }
            )
        except Exception as error:
            collection_passed = False
            collection_results.append(
                {"path": path, "error_type": type(error).__name__}
            )
    report.add(
        "discovery.rest_collections",
        collection_passed,
        "Unauthenticated REST collections do not disclose inherited or inactive commerce records.",
        evidence={"endpoints": collection_results},
    )

    taxonomy_results: list[dict[str, Any]] = []
    taxonomies_passed = True
    for path in INACTIVE_PRODUCT_TAXONOMY_COLLECTIONS:
        try:
            response = fetch(
                build_url(path),
                accept="application/json",
            )
            validate_content_type(
                response,
                allowed_media_types={"application/json"},
                allowed_charsets={None, "utf-8"},
            )
            payload = json.loads(response.text())
            language_findings = value_language_findings(payload)
            inherited_findings = legacy_text_findings(payload)
            if response.status == 200:
                total = response.single_header("x-wp-total")
                endpoint_passed = (
                    payload == []
                    and total == "0"
                )
                code = None
            else:
                total = None
                endpoint_passed = (
                    response.status == 404
                    and isinstance(payload, dict)
                    and payload.get("code") == "rest_no_route"
                    and payload.get("data", {}).get("status") == 404
                )
                code = (
                    payload.get("code")
                    if isinstance(payload, dict)
                    else None
                )
            endpoint_passed = (
                endpoint_passed
                and language_findings == []
                and inherited_findings == []
            )
            taxonomies_passed = (
                taxonomies_passed
                and endpoint_passed
            )
            taxonomy_results.append(
                {
                    "path": urllib.parse.urlsplit(path).path,
                    "status": response.status,
                    "records": (
                        len(payload)
                        if isinstance(payload, list)
                        else None
                    ),
                    "total": total,
                    "code": code,
                    "language_findings": language_findings,
                    "inherited_text_findings": inherited_findings,
                }
            )
        except Exception as error:
            taxonomies_passed = False
            taxonomy_results.append(
                {"path": path, "error_type": type(error).__name__}
            )
    report.add(
        "discovery.rest_product_taxonomies",
        taxonomies_passed,
        (
            "Product taxonomy collections are empty or their WordPress "
            "REST routes are not registered."
        ),
        evidence={"endpoints": taxonomy_results},
    )

    detail_results: list[dict[str, Any]] = []
    details_passed = True
    for path in LEGACY_REST_DETAILS:
        try:
            for method in ("GET", "HEAD"):
                response = fetch(
                    build_url(path),
                    accept="application/json",
                    method=method,
                )
                validate_content_type(
                    response,
                    allowed_media_types={"application/json"},
                    allowed_charsets={None, "utf-8"},
                )
                if method == "GET":
                    payload = json.loads(response.text())
                    language_findings = value_language_findings(payload)
                    passed = (
                        response.status == 404
                        and is_json_media_type(response.content_type)
                        and isinstance(payload, dict)
                        and payload.get("code") == "rest_not_found"
                        and payload.get("data", {}).get("status") == 404
                        and language_findings == []
                        and legacy_text_findings(payload) == []
                    )
                    code = (
                        payload.get("code")
                        if isinstance(payload, dict)
                        else None
                    )
                else:
                    passed = response.status == 404
                    code = None
                    language_findings = []
                details_passed = details_passed and passed
                detail_results.append(
                    {
                        "method": method,
                        "path": path,
                        "status": response.status,
                        "code": code,
                        "language_findings": language_findings,
                    }
                )
        except Exception as error:
            details_passed = False
            detail_results.append(
                {"path": path, "error_type": type(error).__name__}
            )
    report.add(
        "discovery.rest_details",
        details_passed,
        "Unauthenticated direct REST requests return the generic hidden-record 404.",
        evidence={"endpoints": detail_results},
    )

    store_api_results: list[dict[str, Any]] = []
    store_api_passed = True
    for method in ("GET", "HEAD"):
        try:
            response = fetch(
                build_url(INACTIVE_STORE_API_PATH),
                accept="application/json",
                method=method,
            )
            validate_content_type(
                response,
                allowed_media_types={"application/json"},
                allowed_charsets={None, "utf-8"},
            )
            if method == "GET":
                payload = json.loads(response.text())
                language_findings = value_language_findings(payload)
                inherited_findings = legacy_text_findings(payload)
                code = (
                    payload.get("code")
                    if isinstance(payload, dict)
                    else None
                )
                endpoint_passed = (
                    response.status == 404
                    and isinstance(payload, dict)
                    and code in {"rest_no_route", "rest_not_found"}
                    and payload.get("data", {}).get("status") == 404
                    and language_findings == []
                    and inherited_findings == []
                )
            else:
                code = None
                language_findings = []
                inherited_findings = []
                endpoint_passed = response.status == 404
            store_api_passed = store_api_passed and endpoint_passed
            store_api_results.append(
                {
                    "method": method,
                    "path": INACTIVE_STORE_API_PATH,
                    "status": response.status,
                    "code": code,
                    "language_findings": language_findings,
                    "inherited_text_findings": inherited_findings,
                }
            )
        except Exception as error:
            store_api_passed = False
            store_api_results.append(
                {
                    "method": method,
                    "path": INACTIVE_STORE_API_PATH,
                    "error_type": type(error).__name__,
                }
            )
    report.add(
        "discovery.store_api_products",
        store_api_passed,
        "The unauthenticated Store API product collection returns a generic JSON 404.",
        evidence={"endpoints": store_api_results},
    )

    search_results: list[dict[str, Any]] = []
    search_passed = True
    for term in SEARCH_TERMS:
        try:
            query = urllib.parse.urlencode(
                {
                    "search": term,
                    "_fields": "id,title,url,subtype",
                    "per_page": 100,
                }
            )
            response = fetch(
                build_url(f"/wp-json/wp/v2/search?{query}"),
                accept="application/json",
            )
            validate_content_type(
                response,
                allowed_media_types={"application/json"},
                allowed_charsets={None, "utf-8"},
            )
            payload = json.loads(response.text())
            leaks = [
                item
                for item in payload
                if isinstance(item, dict)
                and (
                    item.get("subtype") == "robot"
                    or legacy_url(str(item.get("url", "")))
                )
            ] if isinstance(payload, list) else ["unexpected payload"]
            legacy_findings = legacy_text_findings(payload)
            endpoint_passed = (
                response.status == 200
                and is_json_media_type(response.content_type)
                and isinstance(payload, list)
                and payload == []
                and response.single_header("x-wp-total") == "0"
                and leaks == []
                and value_language_findings(payload) == []
                and legacy_findings == []
            )
            search_passed = search_passed and endpoint_passed
            search_results.append(
                {
                    "term": term,
                    "status": response.status,
                    "result_count": (
                        len(payload) if isinstance(payload, list) else None
                    ),
                    "leaks": leaks,
                    "legacy_findings": legacy_findings,
                    "language_findings": value_language_findings(payload),
                }
            )
        except Exception as error:
            search_passed = False
            search_results.append(
                {"term": term, "error_type": type(error).__name__}
            )
    report.add(
        "discovery.rest_search",
        search_passed,
        "Public REST searches exclude inherited and inactive commerce records.",
        evidence={"queries": search_results},
    )


def verify_sitemap_document(
    url: str,
    *,
    depth: int,
    visited: set[str],
    sitemap_urls: list[str],
    content_urls: list[str],
    initial_response: HttpResult | None = None,
) -> None:
    if depth > 2:
        raise ValueError("Sitemap nesting exceeds the verification bound.")
    if url in visited:
        return
    parsed_url = validate_canonical_url(url)
    if parsed_url.query:
        raise ValueError("Sitemap URL must not contain a query.")
    visited.add(url)
    response = initial_response or fetch(
        build_url(url),
        accept=(
            "application/xml, text/xml, "
            "application/rss+xml, application/atom+xml"
        ),
    )
    if response.status != 200:
        raise ValueError(f"Sitemap returned HTTP {response.status}.")
    validate_content_type(
        response,
        allowed_media_types={"application/xml", "text/xml"},
        allowed_charsets={None, "utf-8"},
    )
    root_name, locations = parse_xml_locations(response.text())
    if root_name == "sitemapindex":
        if len(locations) > 50:
            raise ValueError("Sitemap index exceeds the verification bound.")
        for location in locations:
            sitemap_urls.append(location)
            verify_sitemap_document(
                location,
                depth=depth + 1,
                visited=visited,
                sitemap_urls=sitemap_urls,
                content_urls=content_urls,
            )
    elif root_name == "urlset":
        expected_origin = urllib.parse.urlsplit(EXPECTED_ORIGIN)
        for location in locations:
            parsed_location = validate_canonical_url(location)
            if (
                parsed_location.netloc != expected_origin.netloc
                or parsed_location.query
            ):
                raise ValueError("Sitemap contains a noncanonical URL.")
        content_urls.extend(locations)
    else:
        raise ValueError("Unexpected sitemap root element.")


def verify_sitemaps(report: Report) -> None:
    providers: list[dict[str, Any]] = []
    all_sitemap_urls: list[str] = []
    all_content_urls: list[str] = []
    hard_passed = True

    for path, required in (
        ("/wp-sitemap.xml", True),
        ("/sitemap_index.xml", False),
        ("/sitemap.xml", False),
    ):
        active = False
        try:
            response = fetch(
                build_url(path),
                accept="application/xml, text/xml",
            )
            if response.status == 200:
                active = True
                sitemap_urls: list[str] = []
                content_urls: list[str] = []
                verify_sitemap_document(
                    urllib.parse.urljoin(EXPECTED_ORIGIN, path),
                    depth=0,
                    visited=set(),
                    sitemap_urls=sitemap_urls,
                    content_urls=content_urls,
                    initial_response=response,
                )
                all_sitemap_urls.extend(sitemap_urls)
                all_content_urls.extend(content_urls)
                providers.append(
                    {
                        "path": path,
                        "status": response.status,
                        "sitemaps": len(sitemap_urls),
                        "urls": len(content_urls),
                    }
                )
            elif required:
                hard_passed = False
                providers.append({"path": path, "status": response.status})
            elif response.status not in {404, 410}:
                hard_passed = False
                providers.append(
                    {
                        "path": path,
                        "status": response.status,
                        "active": "unhealthy",
                    }
                )
            else:
                providers.append(
                    {"path": path, "status": response.status, "active": False}
                )
        except Exception as error:
            hard_passed = False
            providers.append(
                {
                    "path": path,
                    "error_type": type(error).__name__,
                    "required": required,
                    "active": active,
                }
            )

    unique_sitemap_urls = sorted(set(all_sitemap_urls))
    unique_content_urls = sorted(set(all_content_urls))
    forbidden_sitemaps = [
        url
        for url in unique_sitemap_urls
        if (
            "posts-robot-" in url
            or "sitemap-users-" in url
            or inactive_product_sitemap_url(url)
        )
    ]
    forbidden_content = [
        url for url in unique_content_urls if legacy_url(url)
    ]
    report.add(
        "discovery.sitemaps",
        hard_passed
        and forbidden_sitemaps == []
        and forbidden_content == []
        and EXPECTED_ORIGIN + "/" in unique_content_urls,
        (
            "Known WordPress and SEO sitemap endpoints exclude inherited "
            "and inactive commerce records."
        ),
        evidence={
            "providers": providers,
            "forbidden_sitemaps": forbidden_sitemaps,
            "forbidden_content": forbidden_content,
            "content_url_count": len(unique_content_urls),
            "homepage_present": EXPECTED_ORIGIN + "/" in unique_content_urls,
        },
    )


def verify_legacy_html(report: Report) -> None:
    results: list[dict[str, Any]] = []
    passed = True
    for path in LEGACY_HTML_PATHS:
        try:
            response = fetch(
                build_url(path),
                accept="text/html",
            )
            validate_content_type(
                response,
                allowed_media_types={"text/html"},
                allowed_charsets={None, "utf-8"},
            )
            facts = parse_html(response.text())
            language_findings = public_language_findings(facts)
            retired_findings = legacy_text_findings(
                [facts.title, facts.body_text, facts.visible_attributes]
            )
            legacy_links = [
                href for href in facts.body_hrefs if legacy_url(href)
            ]
            directives = robots_directives(
                facts,
                response.values("x-robots-tag"),
            )
            endpoint_passed = (
                response.status == 410
                and valid_html_document(facts)
                and facts.html_language == "en-US"
                and facts.h1_count == 1
                and facts.main_count == 1
                and language_findings == []
                and retired_findings == []
                and legacy_links == []
                and "index" not in directives
                and "nofollow" not in directives
                and "none" not in directives
            )
            passed = passed and endpoint_passed
            results.append(
                {
                    "path": path,
                    "status": response.status,
                    "robots": sorted(directives),
                    "language": facts.html_language,
                    "structure_errors": facts.structure_errors,
                    "language_findings": language_findings,
                    "retired_text_findings": retired_findings,
                    "legacy_links": legacy_links,
                }
            )
        except Exception as error:
            passed = False
            results.append(
                {"path": path, "error_type": type(error).__name__}
            )
    report.add(
        "discovery.direct_html",
        passed,
        "Inherited public HTML URLs are explicitly gone and render the established error surface.",
        evidence={"endpoints": results},
    )


def verify_search_and_feed(report: Report) -> None:
    no_results_text = (
        "No results found. Try another search term or return to the atlas."
    )
    html_results: list[dict[str, Any]] = []
    html_passed = True
    for term in SEARCH_TERMS:
        try:
            query = urllib.parse.urlencode({"s": term})
            response = fetch(
                build_url(f"/?{query}"),
                accept="text/html",
            )
            validate_content_type(
                response,
                allowed_media_types={"text/html"},
                allowed_charsets={None, "utf-8"},
            )
            facts = parse_html(response.text())
            leaked_links = [
                href for href in facts.body_hrefs if legacy_url(href)
            ]
            language_findings = public_language_findings(facts)
            surface_without_query = re.sub(
                re.escape(term),
                "",
                f"{facts.title} {facts.body_text}",
                flags=re.I,
            )
            retired_findings = legacy_text_findings(surface_without_query)
            result_markup_count = (
                facts.class_counts["wp-block-post-title"]
                + facts.class_counts["wp-block-post-excerpt"]
                + facts.class_counts["type-robot"]
            )
            endpoint_passed = (
                response.status == 200
                and valid_html_document(facts)
                and facts.html_language == "en-US"
                and facts.main_count == 1
                and facts.body_text.count(no_results_text) == 1
                and result_markup_count == 0
                and leaked_links == []
                and language_findings == []
                and retired_findings == []
            )
            html_passed = html_passed and endpoint_passed
            html_results.append(
                {
                    "term": term,
                    "status": response.status,
                    "leaked_links": leaked_links,
                    "language_findings": language_findings,
                    "retired_text_findings": retired_findings,
                    "result_markup_count": result_markup_count,
                    "no_results_count": facts.body_text.count(
                        no_results_text
                    ),
                }
            )
        except Exception as error:
            html_passed = False
            html_results.append(
                {"term": term, "error_type": type(error).__name__}
            )
    report.add(
        "discovery.html_search",
        html_passed,
        (
            "Public HTML searches return the reviewed empty-results surface "
            "without inherited or inactive commerce records."
        ),
        evidence={"queries": html_results},
    )

    feed_results: list[dict[str, Any]] = []
    feed_passed = True
    for path in FEED_PATHS:
        try:
            response = fetch(
                build_url(path),
                accept=(
                    "application/rss+xml, application/atom+xml;q=0.9, "
                    "application/xml;q=0.8, text/xml;q=0.7"
                ),
            )
            endpoint_passed = response.status in {404, 410}
            leaks: list[dict[str, str]] = []
            root_name: str | None = None
            language_findings: list[str] = []
            retired_findings: list[str] = []
            gone_structure_errors: list[str] = []
            if response.status == 200:
                validate_content_type(
                    response,
                    allowed_media_types={
                        "application/atom+xml",
                        "application/rss+xml",
                        "application/xml",
                        "text/xml",
                    },
                    allowed_charsets={None, "utf-8"},
                )
                text = response.text()
                root = ET.fromstring(text)
                root_name = root.tag.rsplit("}", 1)[-1].lower()
                leaks = feed_legacy_evidence(root)
                language_findings = value_language_findings(text)
                retired_findings = legacy_text_findings(text)
                endpoint_passed = (
                    root_name in {"rss", "feed"}
                    and leaks == []
                    and language_findings == []
                    and retired_findings == []
                )
            elif response.status in {404, 410}:
                validate_content_type(
                    response,
                    allowed_media_types={"text/html"},
                    allowed_charsets={None, "utf-8"},
                )
                facts = parse_html(response.text())
                language_findings = public_language_findings(facts)
                retired_findings = legacy_text_findings(
                    [facts.title, facts.body_text, facts.visible_attributes]
                )
                gone_structure_errors = facts.structure_errors
                leaks = [
                    {"kind": "link", "value": href}
                    for href in facts.body_hrefs
                    if legacy_url(href)
                ]
                endpoint_passed = (
                    valid_html_document(facts)
                    and facts.html_language == "en-US"
                    and language_findings == []
                    and retired_findings == []
                    and leaks == []
                )
            feed_passed = feed_passed and endpoint_passed
            feed_results.append(
                {
                    "path": path,
                    "status": response.status,
                    "root": root_name,
                    "leaks": leaks,
                    "language_findings": language_findings,
                    "retired_text_findings": retired_findings,
                    "gone_structure_errors": gone_structure_errors,
                }
            )
        except Exception as error:
            feed_passed = False
            feed_results.append(
                {"path": path, "error_type": type(error).__name__}
            )
    report.add(
        "discovery.feed",
        feed_passed,
        "Public and retired feed surfaces exclude inherited records.",
        evidence={"endpoints": feed_results},
    )


def verify_error_page(report: Report) -> None:
    try:
        response = fetch(
            build_url("/rbtx-verification-record-not-found/"),
            accept="text/html",
        )
        validate_content_type(
            response,
            allowed_media_types={"text/html"},
            allowed_charsets={None, "utf-8"},
        )
        facts = parse_html(response.text())
        findings = public_language_findings(facts)
        retired_findings = legacy_text_findings(
            [facts.title, facts.body_text, facts.visible_attributes]
        )
        legacy_links = [
            href for href in facts.body_hrefs if legacy_url(href)
        ]
        directives = robots_directives(
            facts,
            response.values("x-robots-tag"),
        )
        report.add(
            "public.error_page",
            response.status == 404
            and valid_html_document(facts)
            and facts.html_language == "en-US"
            and facts.h1_count == 1
            and facts.main_count == 1
            and "main-content" in facts.element_ids
            and findings == []
            and retired_findings == []
            and legacy_links == []
            and "index" not in directives
            and "nofollow" not in directives
            and "none" not in directives,
            "Public 404 page is usable and follows the language boundary.",
            evidence={
                "http_status": response.status,
                "language": facts.html_language,
                "h1_count": facts.h1_count,
                "main_count": facts.main_count,
                "language_findings": findings,
                "retired_text_findings": retired_findings,
                "legacy_links": legacy_links,
                "robots": sorted(directives),
            },
        )
    except Exception as error:
        report.exception(
            "public.error_page",
            "Public 404 page could not be verified.",
            error,
        )


def safe_commerce_href(
    href: str,
    *,
    expected_path: str | None = None,
    required_path_prefix: str | None = None,
    allow_empty: bool = False,
) -> bool:
    if not href:
        return allow_empty
    try:
        parsed = validate_canonical_url(
            urllib.parse.urljoin(EXPECTED_ORIGIN + "/", href)
        )
    except ValueError:
        return False
    if parsed.query:
        return False
    if expected_path is not None and parsed.path != expected_path:
        return False
    if (
        required_path_prefix is not None
        and not parsed.path.startswith(required_path_prefix)
    ):
        return False
    return True


def element_index(facts: HtmlFacts) -> dict[int, dict[str, Any]]:
    return {
        element["id"]: element
        for element in facts.elements
    }


def element_ancestors(
    element: dict[str, Any],
    by_id: dict[int, dict[str, Any]],
) -> Iterable[dict[str, Any]]:
    parent_id = element["parent_id"]
    reviewed = 0
    while parent_id is not None and reviewed <= len(by_id):
        parent = by_id[parent_id]
        yield parent
        parent_id = parent["parent_id"]
        reviewed += 1


def element_is_descendant(
    element: dict[str, Any],
    ancestor_id: int,
    by_id: dict[int, dict[str, Any]],
) -> bool:
    return any(
        parent["id"] == ancestor_id
        for parent in element_ancestors(element, by_id)
    )


def element_or_ancestor_has_inline_handler(
    element: dict[str, Any],
    by_id: dict[int, dict[str, Any]],
) -> bool:
    return any(
        any(name.lower().startswith("on") for name in candidate["attribute_names"])
        for candidate in [element, *element_ancestors(element, by_id)]
    )


def nearest_element(
    element: dict[str, Any],
    by_id: dict[int, dict[str, Any]],
    *,
    tag: str | None = None,
    class_name: str | None = None,
) -> dict[str, Any] | None:
    for parent in element_ancestors(element, by_id):
        if tag is not None and parent["tag"] != tag:
            continue
        if (
            class_name is not None
            and class_name not in parent["classes"]
        ):
            continue
        return parent
    return None


def element_text(element: dict[str, Any]) -> str:
    return " ".join(" ".join(element["text_parts"]).split())


def element_is_effectively_enabled(
    element: dict[str, Any],
    by_id: dict[int, dict[str, Any]],
) -> bool:
    if (
        "disabled" in element["attribute_names"]
        or element["attrs"].get("aria-disabled", "").strip().lower()
        == "true"
    ):
        return False
    for fieldset in (
        ancestor
        for ancestor in element_ancestors(element, by_id)
        if ancestor["tag"] == "fieldset"
        and "disabled" in ancestor["attribute_names"]
    ):
        legends = sorted(
            (
                candidate
                for candidate in by_id.values()
                if candidate["tag"] == "legend"
                and candidate["parent_id"] == fieldset["id"]
            ),
            key=lambda candidate: candidate["id"],
        )
        if legends and (
            element["id"] == legends[0]["id"]
            or element_is_descendant(
                element,
                legends[0]["id"],
                by_id,
            )
        ):
            continue
        return False
    return True


def element_is_submit_control(element: dict[str, Any]) -> bool:
    if element["tag"] == "button":
        return (
            element["attrs"].get("type", "submit").strip().lower()
            in {"", "submit"}
        )
    return (
        element["tag"] == "input"
        and element["attrs"].get("type", "").strip().lower()
        in {"image", "submit"}
    )


def inline_handler_blocks_action(
    element: dict[str, Any],
    attribute_name: str,
) -> bool:
    handler = element["attrs"].get(attribute_name, "")
    return (
        re.search(
            r"\breturn\s+(?:false|0|!1)\b",
            handler,
            flags=re.IGNORECASE,
        )
        is not None
        or re.search(
            r"\.prevent\s*default\s*\(",
            handler,
            flags=re.IGNORECASE,
        )
        is not None
        or re.search(
            r"\.\s*returnValue\s*=\s*(?:false|0|!1)\b",
            handler,
            flags=re.IGNORECASE,
        )
        is not None
    )


def form_allows_submission(form: dict[str, Any]) -> bool:
    return (
        not inline_handler_blocks_action(form, "onsubmit")
        and not any(
            name.lower().startswith("on")
            for name in form["attribute_names"]
        )
        and form["attrs"].get(
            "enctype",
            "application/x-www-form-urlencoded",
        ).strip().lower()
        in {
            "application/x-www-form-urlencoded",
            "multipart/form-data",
        }
        and form["attrs"].get("target", "").strip().lower()
        in {"", "_self"}
    )


def submitter_allows_form(
    control: dict[str, Any],
    form: dict[str, Any],
    *,
    expected_path: str,
    allow_empty: bool = False,
) -> bool:
    action = control["attrs"].get("formaction")
    method = control["attrs"].get(
        "formmethod",
        form["attrs"].get("method", "get"),
    ).strip().lower() or "get"
    enctype = control["attrs"].get(
        "formenctype",
        form["attrs"].get(
            "enctype",
            "application/x-www-form-urlencoded",
        ),
    ).strip().lower()
    target = control["attrs"].get(
        "formtarget",
        form["attrs"].get("target", ""),
    ).strip().lower()
    return (
        method == "post"
        and enctype
        in {
            "application/x-www-form-urlencoded",
            "multipart/form-data",
        }
        and target in {"", "_self"}
        and (
            action is None
            or safe_commerce_href(
                action,
                expected_path=expected_path,
                allow_empty=allow_empty,
            )
        )
    )


def element_is_visible_data_input(
    element: dict[str, Any],
    by_id: dict[int, dict[str, Any]],
) -> bool:
    return (
        element["tag"] == "input"
        and element["rendered"]
        and element_is_effectively_enabled(element, by_id)
        and not element_or_ancestor_has_inline_handler(element, by_id)
        and "readonly" not in element["attribute_names"]
        and element["attrs"].get(
            "aria-readonly",
            "",
        ).strip().lower()
        != "true"
        and element["attrs"].get("type", "text").strip().lower()
        in {
            "",
            "checkbox",
            "date",
            "datetime-local",
            "email",
            "month",
            "number",
            "password",
            "radio",
            "range",
            "search",
            "tel",
            "text",
            "time",
            "url",
            "week",
        }
    )


def form_owner(
    element: dict[str, Any],
    by_id: dict[int, dict[str, Any]],
) -> dict[str, Any] | None:
    if "form" in element["attribute_names"]:
        target = element["attrs"].get("form", "")
        matches = [
            candidate
            for candidate in by_id.values()
            if candidate["tag"] == "form"
            and candidate["attrs"].get("id", "") == target
            and target
        ]
        return matches[0] if len(matches) == 1 else None
    return nearest_element(element, by_id, tag="form")


def owned_form_controls(
    facts: HtmlFacts,
    form: dict[str, Any],
    by_id: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        element
        for element in facts.elements
        if element["tag"] in {"button", "input"}
        and form_owner(element, by_id) == form
        and element_is_descendant(element, form["id"], by_id)
    ]


def visible_enabled_submit_controls(
    controls: Iterable[dict[str, Any]],
    by_id: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        control
        for control in controls
        if control["rendered"]
        and element_is_effectively_enabled(control, by_id)
        and element_is_submit_control(control)
        and not element_or_ancestor_has_inline_handler(control, by_id)
        and not inline_handler_blocks_action(control, "onclick")
    ]


def control_visible_label(element: dict[str, Any]) -> str:
    if element["tag"] == "button":
        return element_text(element)
    if element["tag"] != "input":
        return ""
    if element["attrs"].get("type", "").strip().lower() == "image":
        return element["attrs"].get("alt", "").strip()
    return element["attrs"].get("value", "").strip()


def route_submit_controls(
    controls: Iterable[dict[str, Any]],
    by_id: dict[int, dict[str, Any]],
    route: str,
) -> list[dict[str, Any]]:
    patterns = {
        "account": re.compile(r"\b(?:log in|login|sign in)\b", re.IGNORECASE),
        "cart": re.compile(
            r"\b(?:checkout|proceed|update cart)\b",
            re.IGNORECASE,
        ),
        "checkout": re.compile(
            r"\b(?:complete purchase|pay|place order|submit order)\b",
            re.IGNORECASE,
        ),
        "product": re.compile(
            r"\b(?:add to cart|buy|order|purchase)\b",
            re.IGNORECASE,
        ),
    }
    return [
        control
        for control in visible_enabled_submit_controls(controls, by_id)
        if patterns[route].search(control_visible_label(control)) is not None
        and (
            route == "product"
            or (
                route == "account"
                and control["attrs"].get("name", "") == "login"
            )
            or (
                route == "cart"
                and (
                    control["attrs"].get("name", "").strip().lower()
                    == "update_cart"
                    or (
                        nearest_element(
                            control,
                            by_id,
                            class_name="wc-block-cart",
                        )
                        is not None
                        and "wc-block-components-button"
                        in control["classes"]
                    )
                )
            )
            or (
                route == "checkout"
                and (
                    (
                        control["attrs"].get("id", "") == "place_order"
                        and control["attrs"].get("name", "")
                        == "woocommerce_checkout_place_order"
                    )
                    or (
                        "wc-block-components-checkout-place-order-button"
                        in control["classes"]
                        and nearest_element(
                            control,
                            by_id,
                            class_name="wc-block-checkout",
                        )
                        is not None
                    )
                )
            )
        )
    ]


def route_data_inputs(
    controls: Iterable[dict[str, Any]],
    by_id: dict[int, dict[str, Any]],
    route: str,
) -> list[dict[str, Any]]:
    candidates = [
        control
        for control in controls
        if element_is_visible_data_input(control, by_id)
    ]
    if route == "cart":
        return [
            control
            for control in candidates
            if re.fullmatch(
                r"cart\[[^\]]+\]\[qty\]",
                control["attrs"].get("name", "").strip().lower(),
            )
            is not None
            and nearest_element(
                control,
                by_id,
                class_name="cart_item",
            )
            is not None
            or (
                (
                    control["attrs"].get("name", "").strip().lower()
                    in {"qty", "quantity"}
                    or "qty" in control["classes"]
                )
                and nearest_element(
                    control,
                    by_id,
                    class_name="wc-block-cart-item",
                )
                is not None
            )
        ]
    return [
        control
        for control in candidates
        if control["attrs"].get("name", "").strip().lower()
        in {
            "billing_address_1",
            "billing_address_2",
            "billing_city",
            "billing_company",
            "billing_country",
            "billing_email",
            "billing_first_name",
            "billing_last_name",
            "billing_phone",
            "billing_postcode",
            "billing_state",
            "email",
            "order_comments",
            "payment_method",
            "shipping_address_1",
            "shipping_address_2",
            "shipping_city",
            "shipping_company",
            "shipping_country",
            "shipping_first_name",
            "shipping_last_name",
            "shipping_phone",
            "shipping_postcode",
            "shipping_state",
        }
        or control["attrs"].get("autocomplete", "").strip().lower()
        in {
            "billing address-level1",
            "billing address-level2",
            "billing address-line1",
            "billing address-line2",
            "billing country",
            "billing email",
            "billing family-name",
            "billing given-name",
            "billing name",
            "billing postal-code",
            "billing tel",
            "shipping address-level1",
            "shipping address-level2",
            "shipping address-line1",
            "shipping address-line2",
            "shipping country",
            "shipping email",
            "shipping family-name",
            "shipping given-name",
            "shipping name",
            "shipping postal-code",
            "shipping tel",
        }
    ]


def checkout_data_is_coherent(
    controls: Iterable[dict[str, Any]],
    by_id: dict[int, dict[str, Any]],
    *,
    block_checkout: bool,
) -> bool:
    candidates = route_data_inputs(controls, by_id, "checkout")
    names = {
        control["attrs"].get("name", "").strip().lower()
        for control in candidates
    }
    autocomplete_tokens = [
        set(
            control["attrs"].get(
                "autocomplete",
                "",
            ).strip().lower().split()
        )
        for control in candidates
    ]

    def has_autocomplete(scope: str, field_name: str) -> bool:
        return any(
            field_name in tokens
            and (
                scope in tokens
                or (
                    block_checkout
                    and bool(tokens & {"billing", "shipping"})
                )
            )
            for tokens in autocomplete_tokens
        )

    def has_named(
        classic_name: str,
        *block_alternates: str,
    ) -> bool:
        return (
            classic_name in names
            or (
                block_checkout
                and any(name in names for name in block_alternates)
            )
        )

    return (
        (
            has_named("billing_first_name", "shipping_first_name")
            or has_autocomplete("billing", "given-name")
        )
        and (
            has_named("billing_last_name", "shipping_last_name")
            or has_autocomplete("billing", "family-name")
        )
        and (
            has_named("billing_address_1", "shipping_address_1")
            or has_autocomplete("billing", "address-line1")
        )
        and (
            has_named("billing_city", "shipping_city")
            or has_autocomplete("billing", "address-level2")
        )
        and (
            has_named("billing_postcode", "shipping_postcode")
            or has_autocomplete("billing", "postal-code")
        )
        and (
            has_named("billing_email", "email", "shipping_email")
            or has_autocomplete("billing", "email")
        )
    )


def owned_hidden_nonce(
    controls: Iterable[dict[str, Any]],
    by_id: dict[int, dict[str, Any]],
    name: str,
) -> bool:
    matches = [
        control
        for control in controls
        if control["tag"] == "input"
        and control["attrs"].get("type", "").strip().lower() == "hidden"
        and control["attrs"].get("name", "") == name
        and element_is_effectively_enabled(control, by_id)
        and re.fullmatch(
            r"[A-Za-z0-9]{10}",
            control["attrs"].get("value", "").strip(),
        )
        is not None
    ]
    return len(matches) == 1


def rendered_elements_with_class(
    facts: HtmlFacts,
    *,
    class_name: str,
    tag: str | None = None,
) -> list[dict[str, Any]]:
    return [
        element
        for element in facts.elements
        if element["rendered"]
        and class_name in element["classes"]
        and (tag is None or element["tag"] == tag)
    ]


def rendered_scope_controls(
    facts: HtmlFacts,
    scope: dict[str, Any],
    by_id: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        element
        for element in facts.elements
        if element["tag"] in {"button", "input"}
        and element_is_descendant(element, scope["id"], by_id)
    ]


def stock_text_supports_purchase(value: str) -> bool:
    normalized = " ".join(value.lower().split())
    return (
        bool(re.search(r"[A-Za-z]", value))
        and normalized not in {"availability", "status", "stock"}
        and re.search(
            (
                r"\b(?:out of stock|sold out|unavailable|not available|"
                r"not in stock|discontinued|no longer available|"
                r"cannot be purchased)\b"
            ),
            normalized,
        )
        is None
    )


def successful_product_identifier_control(
    control: dict[str, Any],
    submit_controls: Iterable[dict[str, Any]],
) -> bool:
    return (
        (
            control["tag"] == "input"
            and control["attrs"].get(
                "type",
                "text",
            ).strip().lower()
            == "hidden"
        )
        or (
            control in submit_controls
            and (
                control["tag"] == "button"
                or (
                    control["tag"] == "input"
                    and control["attrs"].get(
                        "type",
                        "",
                    ).strip().lower()
                    == "submit"
                )
            )
        )
    )


def product_surface_and_action(
    facts: HtmlFacts,
    *,
    product_url: str,
    product_id: int,
) -> tuple[bool, bool, dict[str, Any]]:
    by_id = element_index(facts)
    rendered = [
        element
        for element in facts.elements
        if element["rendered"]
    ]
    products = [
        element
        for element in rendered
        if "product" in element["classes"]
        and element["tag"] in {"article", "div", "section"}
    ]
    surface_contexts: list[dict[str, Any]] = []
    action_contexts: list[dict[str, Any]] = []
    expected_identifier = str(product_id)
    expected_path = urllib.parse.urlsplit(product_url).path
    cart_forms = rendered_elements_with_class(
        facts,
        class_name="cart",
        tag="form",
    )
    form_controls = {
        form["id"]: owned_form_controls(facts, form, by_id)
        for form in cart_forms
    }
    submit_controls = {
        form["id"]: route_submit_controls(
            form_controls[form["id"]],
            by_id,
            "product",
        )
        for form in cart_forms
    }
    action_bearing_forms = [
        form
        for form in cart_forms
        if submit_controls[form["id"]]
    ]

    for form in action_bearing_forms:
        summary = nearest_element(
            form,
            by_id,
            class_name="summary",
        )
        product = nearest_element(
            form,
            by_id,
            class_name="product",
        )
        if (
            summary is None
            or product is None
            or product not in products
            or nearest_element(
                summary,
                by_id,
                class_name="product",
            )
            != product
        ):
            continue
        summaries = [
            element
            for element in rendered
            if "summary" in element["classes"]
            and element_is_descendant(element, product["id"], by_id)
            and nearest_element(
                element,
                by_id,
                class_name="product",
            )
            == product
        ]
        titles = [
            element
            for element in rendered
            if element["tag"] == "h1"
            and "product_title" in element["classes"]
            and element_is_descendant(element, summary["id"], by_id)
            and nearest_element(
                element,
                by_id,
                class_name="summary",
            )
            == summary
            and nearest_element(
                element,
                by_id,
                class_name="product",
            )
            == product
            and not element_or_ancestor_has_inline_handler(
                element,
                by_id,
            )
            and any(
                character.isalnum()
                for character in element_text(element)
            )
        ]
        stock_elements = [
            element
            for element in rendered
            if "stock" in element["classes"]
            and element_is_descendant(element, summary["id"], by_id)
            and nearest_element(
                element,
                by_id,
                class_name="summary",
            )
            == summary
            and nearest_element(
                element,
                by_id,
                class_name="product",
            )
            == product
            and not element_or_ancestor_has_inline_handler(
                element,
                by_id,
            )
        ]
        stock_states = [
            element
            for element in stock_elements
            if (
                not (
                    {
                        "out-of-stock",
                        "outofstock",
                        "unavailable",
                    }
                    & {
                        class_name.strip().lower()
                        for class_name in element["classes"]
                    }
                )
                and element["attrs"].get(
                    "data-stock-status",
                    "",
                ).strip().lower()
                not in {
                    "out-of-stock",
                    "outofstock",
                    "unavailable",
                }
                and
                (
                    {
                        "available-on-backorder",
                        "in-stock",
                    }
                    & {
                        class_name.strip().lower()
                        for class_name in element["classes"]
                    }
                    or element["attrs"].get(
                        "data-stock-status",
                        "",
                    ).strip().lower()
                    in {
                        "available-on-backorder",
                        "in-stock",
                        "instock",
                        "onbackorder",
                    }
                )
                and stock_text_supports_purchase(element_text(element))
            )
        ]
        if not titles:
            continue
        surface_context = {
            "form_element": form["id"],
            "product_element": product["id"],
            "positive_stock_count": len(stock_states),
            "stock_count": len(stock_elements),
            "summary_count": len(summaries),
            "summary_element": summary["id"],
            "title_count": len(titles),
        }
        surface_contexts.append(surface_context)
        controls = form_controls[form["id"]]
        identifier_controls = [
            control
            for control in controls
            if control["attrs"].get("name", "")
            in {"add-to-cart", "product_id"}
            and (
                element_is_effectively_enabled(control, by_id)
                or "disabled" in control["attribute_names"]
                or control["attrs"].get(
                    "aria-disabled",
                    "",
                ).strip().lower()
                == "true"
            )
        ]
        identifiers_valid = (
            bool(identifier_controls)
            and all(
                element_is_effectively_enabled(control, by_id)
                and control["attrs"].get("value", "").strip()
                == expected_identifier
                and successful_product_identifier_control(
                    control,
                    submit_controls[form["id"]],
                )
                for control in identifier_controls
            )
        )
        add_to_cart_controls = [
            control
            for control in identifier_controls
            if control["attrs"].get("name", "") == "add-to-cart"
            and control["attrs"].get("value", "").strip()
            == expected_identifier
            and successful_product_identifier_control(
                control,
                submit_controls[form["id"]],
            )
        ]
        action = form["attrs"].get("action", "")
        method = (
            form["attrs"].get("method", "get").strip().lower()
            or "get"
        )
        context_passed = (
            len(summaries) == 1
            and len(titles) == 1
            and len(stock_elements) == 1
            and len(stock_states) == 1
            and method == "post"
            and safe_commerce_href(
                action,
                expected_path=expected_path,
                allow_empty=True,
            )
            and form_allows_submission(form)
            and len(submit_controls[form["id"]]) == 1
            and all(
                submitter_allows_form(
                    control,
                    form,
                    expected_path=expected_path,
                    allow_empty=True,
                )
                for control in submit_controls[form["id"]]
            )
            and identifiers_valid
            and bool(add_to_cart_controls)
        )
        if context_passed:
            action_contexts.append(
                {
                    **surface_context,
                    "add_to_cart_count": len(add_to_cart_controls),
                    "identifier_count": len(identifier_controls),
                    "submit_count": len(submit_controls[form["id"]]),
                }
            )

    surface_passed = (
        len(surface_contexts) == 1
        and surface_contexts[0]["summary_count"] == 1
        and surface_contexts[0]["title_count"] == 1
        and surface_contexts[0]["stock_count"] == 1
        and surface_contexts[0]["positive_stock_count"] == 1
    )
    action_passed = (
        surface_passed
        and len(action_bearing_forms) == 1
        and len(action_contexts) == 1
    )
    return (
        surface_passed,
        action_passed,
        {
            "action_contexts": action_contexts,
            "action_form_count": len(action_bearing_forms),
            "product_candidates": len(products),
            "surface_contexts": surface_contexts,
        },
    )


def product_catalog_card_links(
    facts: HtmlFacts,
) -> tuple[bool, list[str]]:
    by_id = element_index(facts)
    card_classes = {
        "product",
        "wc-block-grid__product",
        "wc-block-product",
    }
    container_classes = {
        "products",
        "wc-block-grid__products",
        "wc-block-product-template",
    }
    cards = [
        element
        for element in facts.elements
        if element["rendered"]
        and bool(card_classes & element["classes"])
        and any(
            nearest_element(
                element,
                by_id,
                class_name=container_class,
            )
            is not None
            for container_class in container_classes
        )
    ]
    hrefs: list[str] = []
    for card in cards:
        links = [
            element
            for element in facts.elements
            if element["rendered"]
            and element["tag"] == "a"
            and element_is_descendant(element, card["id"], by_id)
            and next(
                (
                    ancestor
                    for ancestor in element_ancestors(element, by_id)
                    if bool(card_classes & ancestor["classes"])
                ),
                None,
            )
            == card
            and safe_commerce_href(
                element["attrs"].get("href", ""),
                required_path_prefix="/product/",
            )
            and not element_or_ancestor_has_inline_handler(
                element,
                by_id,
            )
        ]
        meaningful_links = []
        for link in links:
            meaningful_text = any(
                character.isalnum()
                for character in element_text(link)
            )
            meaningful_image = any(
                image["tag"] == "img"
                and image["rendered"]
                and element_is_descendant(image, link["id"], by_id)
                and bool(image["attrs"].get("src", "").strip())
                and any(
                    character.isalnum()
                    for character in image["attrs"].get("alt", "")
                )
                for image in facts.elements
            )
            if meaningful_text or meaningful_image:
                meaningful_links.append(link)
        if not meaningful_links:
            return False, []
        hrefs.extend(
            link["attrs"].get("href", "")
            for link in meaningful_links
        )
    return bool(cards), hrefs


def verify_product_catalog_links(
    hrefs: Iterable[str],
) -> tuple[bool, list[dict[str, Any]]]:
    urls = sorted(
        {
            urllib.parse.urljoin(EXPECTED_ORIGIN + "/", href)
            for href in hrefs
            if safe_commerce_href(
                href,
                required_path_prefix="/product/",
            )
        }
    )
    if not urls or len(urls) > 40:
        return False, [
            {
                "error": "product_link_count",
                "reviewed_count": len(urls),
            }
        ]

    passed = True
    results: list[dict[str, Any]] = []
    for url in urls:
        try:
            product_path = urllib.parse.urlsplit(url).path
            product_request_url = build_url(product_path)
            slug = urllib.parse.unquote(
                product_path.rstrip("/").rsplit("/", 1)[-1]
            )
            record_url = build_url(
                "/wp-json/wp/v2/product?"
                + urllib.parse.urlencode(
                    {
                        "_fields": "id,slug,link,status,type",
                        "slug": slug,
                        "status": "publish",
                    }
                )
            )
            record_response = fetch(
                record_url,
                accept="application/json",
                timeout=30,
            )
            validate_content_type(
                record_response,
                allowed_media_types={"application/json"},
                allowed_charsets={None, "utf-8"},
            )
            record_payload = json.loads(record_response.text())
            record = (
                record_payload[0]
                if isinstance(record_payload, list)
                and len(record_payload) == 1
                and isinstance(record_payload[0], dict)
                else {}
            )
            record_passed = (
                record_response.status == 200
                and record_response.final_url == record_url
                and type(record.get("id")) is int
                and record["id"] > 0
                and record.get("slug") == slug
                and record.get("link") == url
                and record.get("status") == "publish"
                and record.get("type") == "product"
                and value_language_findings(record_payload) == []
                and legacy_text_findings(record_payload) == []
            )
            response = fetch(
                product_request_url,
                accept="text/html",
                timeout=30,
            )
            validate_content_type(
                response,
                allowed_media_types={"text/html"},
                allowed_charsets={None, "utf-8"},
            )
            facts = parse_html(response.text())
            (
                executable_scripts_valid,
                executable_script_results,
            ) = verify_executable_scripts(facts)
            scoped_directives = robots_directives_by_scope(
                facts,
                response.values("x-robots-tag"),
            )
            effective_directives = all_effective_robots_directives(
                scoped_directives
            )
            coming_soon_classes = sorted(
                class_name
                for class_name in facts.class_counts
                if "coming-soon" in class_name.lower()
            )
            (
                product_surface,
                commercial_action,
                product_context,
            ) = product_surface_and_action(
                facts,
                product_url=product_request_url,
                product_id=(
                    record.get("id")
                    if type(record.get("id")) is int
                    else 0
                ),
            )
            browser_proof = commerce_browser_proof(
                mode="product",
                expected_path=product_path,
                url=product_request_url,
                product_id=(
                    record.get("id")
                    if type(record.get("id")) is int
                    else 0
                ),
            )
            normalized_text = " ".join(
                f"{facts.title} {facts.body_text}".lower().split()
            )
            soft_error = any(
                re.search(pattern, normalized_text) is not None
                for pattern in (
                    r"\b404\b",
                    r"\bnothing (?:could be |was )?found\b",
                    (
                        r"\b(?:item|page|product|record|requested item|"
                        r"resource)\b.{0,60}\b(?:cannot|could not|"
                        r"does not|not|was not)\b.{0,20}\b(?:exist|"
                        r"found|located|available)\b"
                    ),
                    r"\bunable to (?:find|locate)\b",
                )
            )
            page_passed = (
                response.status == 200
                and record_passed
                and response.final_url == product_request_url
                and valid_html_document(facts)
                and facts.html_language == "en-US"
                and facts.h1_count == 1
                and facts.main_count == 1
                and "single-product" in facts.body_classes
                and product_surface
                and commercial_action
                and browser_proof["passed"]
                and browser_proof["routeUi"] == "product"
                and not soft_error
                and coming_soon_classes == []
                and executable_scripts_valid
                and public_language_findings(facts) == []
                and all(
                    directives_allow_indexing(crawler_directives)
                    for crawler_directives in effective_directives.values()
                )
            )
            passed = passed and page_passed
            results.append(
                {
                    "coming_soon_classes": coming_soon_classes,
                    "final_url": response.final_url,
                    "h1_count": facts.h1_count,
                    "language": facts.html_language,
                    "loaded": page_passed,
                    "main_count": facts.main_count,
                    "commercial_action": commercial_action,
                    "browser_proof": browser_proof,
                    "executable_scripts": executable_script_results,
                    "product_context": product_context,
                    "product_surface": product_surface,
                    "record": {
                        "id": record.get("id"),
                        "link": record.get("link"),
                        "loaded": record_passed,
                        "slug": record.get("slug"),
                        "status": record_response.status,
                        "type": record.get("type"),
                        "url": record_url,
                    },
                    "robots_by_scope": {
                        scope: sorted(values)
                        for scope, values in scoped_directives.items()
                    },
                    "status": response.status,
                    "soft_error": soft_error,
                    "url": url,
                }
            )
        except Exception as error:
            passed = False
            results.append(
                {
                    "error_type": type(error).__name__,
                    "loaded": False,
                    "url": url,
                }
            )
    return passed, results


def verify_executable_scripts(
    facts: HtmlFacts,
) -> tuple[bool, list[dict[str, Any]]]:
    candidates: list[tuple[str, str, str]] = []
    for script in facts.scripts:
        script_type = script.get("type", "").strip().lower()
        if script_type == "module":
            mode = "module"
        elif script_type in CLASSIC_JAVASCRIPT_MIME_TYPES:
            mode = "classic"
        else:
            continue
        source = script.get("src", "").strip()
        if source:
            resolved = urllib.parse.urljoin(EXPECTED_ORIGIN + "/", source)
            try:
                validate_canonical_url(resolved)
            except ValueError:
                candidates.append(("invalid_external", mode, resolved))
                continue
            candidates.append(("external", mode, resolved))
        else:
            content = script.get("content", "")
            if content.strip():
                candidates.append(("inline", mode, content))

    if len(candidates) + len(facts.styles) > 100:
        return False, [{"error": "active_content_count"}]
    results: list[dict[str, Any]] = []
    passed = facts.inline_event_handler_count == 0
    if facts.inline_event_handler_count:
        results.append(
            {
                "count": facts.inline_event_handler_count,
                "kind": "inline_event_handlers",
                "loaded": False,
            }
        )
    for index, content in enumerate(facts.styles):
        syntax_valid = valid_css_payload(content)
        loaded = (
            len(content.encode("utf-8")) <= MAX_RESPONSE_BYTES
            and syntax_valid
        )
        passed = passed and loaded
        results.append(
            {
                "bytes": len(content.encode("utf-8")),
                "index": index,
                "kind": "inline_stylesheet",
                "loaded": loaded,
                "syntax_valid": syntax_valid,
            }
        )
    for index, (kind, mode, value) in enumerate(candidates):
        if kind == "invalid_external":
            passed = False
            results.append(
                {
                    "index": index,
                    "kind": "external_script",
                    "loaded": False,
                    "script_mode": mode,
                    "url": value,
                }
            )
            continue
        if kind == "inline":
            syntax_valid = valid_javascript_payload(
                value,
                module=mode == "module",
            )
            loaded = (
                len(value.encode("utf-8")) <= MAX_RESPONSE_BYTES
                and syntax_valid
            )
            passed = passed and loaded
            results.append(
                {
                    "bytes": len(value.encode("utf-8")),
                    "index": index,
                    "kind": "inline_script",
                    "loaded": loaded,
                    "script_mode": mode,
                    "syntax_valid": syntax_valid,
                }
            )
            continue
        try:
            response = fetch(
                value,
                accept=(
                    ", ".join(sorted(JAVASCRIPT_RESPONSE_MEDIA_TYPES))
                ),
                timeout=30,
            )
            actual_media = validate_content_type(
                response,
                allowed_media_types=JAVASCRIPT_RESPONSE_MEDIA_TYPES,
                allowed_charsets={None, "utf-8", "ascii"},
            )
            content = response.text()
            syntax_valid = valid_javascript_payload(
                content,
                module=mode == "module",
            )
            loaded = (
                response.status == 200
                and response.final_url == value
                and bool(response.body)
                and syntax_valid
            )
            passed = passed and loaded
            results.append(
                {
                    "bytes": len(response.body),
                    "content_type": actual_media,
                    "kind": "same_origin_script",
                    "loaded": loaded,
                    "script_mode": mode,
                    "syntax_valid": syntax_valid,
                    "url": value,
                }
            )
        except Exception as error:
            passed = False
            results.append(
                {
                    "error_type": type(error).__name__,
                    "kind": "same_origin_script",
                    "loaded": False,
                    "script_mode": mode,
                    "url": value,
                }
            )
    return passed, results


def verify_commerce_assets(
    facts: HtmlFacts,
) -> tuple[bool, list[dict[str, Any]]]:
    candidates: set[tuple[str, str, str]] = set()
    for link in facts.links:
        if "stylesheet" not in relation_tokens(link):
            continue
        href = link.get("href", "")
        if href:
            candidates.add((href, "stylesheet", ""))
    for script in facts.scripts:
        source = script.get("src", "")
        script_type = script.get("type", "").strip().lower()
        if not source:
            continue
        if script_type == "module":
            candidates.add((source, "script", "module"))
        elif script_type in CLASSIC_JAVASCRIPT_MIME_TYPES:
            candidates.add((source, "script", "classic"))

    reviewed_assets: list[tuple[str, str, str]] = []
    for source, kind, script_mode in candidates:
        resolved = urllib.parse.urljoin(EXPECTED_ORIGIN + "/", source)
        try:
            parsed = validate_canonical_url(resolved)
        except ValueError:
            continue
        if "/wp-content/plugins/woocommerce/" in parsed.path.lower():
            reviewed_assets.append((resolved, kind, script_mode))

    (
        executable_scripts_valid,
        executable_script_results,
    ) = verify_executable_scripts(facts)
    results: list[dict[str, Any]] = []
    if not reviewed_assets or len(reviewed_assets) > 40:
        return False, results

    passed = executable_scripts_valid
    for asset_url, kind, script_mode in sorted(set(reviewed_assets)):
        try:
            response = fetch(
                asset_url,
                accept=(
                    "text/css"
                    if kind == "stylesheet"
                    else (
                        ", ".join(sorted(JAVASCRIPT_RESPONSE_MEDIA_TYPES))
                    )
                ),
                timeout=30,
            )
            actual_media = validate_content_type(
                response,
                allowed_media_types=(
                    {"text/css"}
                    if kind == "stylesheet"
                    else JAVASCRIPT_RESPONSE_MEDIA_TYPES
                ),
                allowed_charsets={None, "utf-8", "ascii"},
            )
            asset_text = response.text()
            syntax_valid = (
                valid_css_payload(asset_text)
                if kind == "stylesheet"
                else valid_javascript_payload(
                    asset_text,
                    module=script_mode == "module",
                )
            )
            loaded = (
                response.status == 200
                and response.final_url == asset_url
                and len(response.body) > 0
                and syntax_valid
            )
            passed = passed and loaded
            results.append(
                {
                    "bytes": len(response.body),
                    "content_type": actual_media,
                    "kind": kind,
                    "loaded": loaded,
                    "script_mode": script_mode or None,
                    "syntax_valid": syntax_valid,
                    "url": asset_url,
                }
            )
        except Exception as error:
            passed = False
            results.append(
                {
                    "error_type": type(error).__name__,
                    "kind": kind,
                    "loaded": False,
                    "script_mode": script_mode or None,
                    "url": asset_url,
                }
            )
    results.extend(executable_script_results)
    return passed, results


def verify_active_commerce_contract(report: Report) -> None:
    results: list[dict[str, Any]] = []
    passed = True
    required_classes = {
        "/shop/": "woocommerce-shop",
        "/cart/": "woocommerce-cart",
        "/checkout/": "woocommerce-checkout",
        "/my-account/": "woocommerce-account",
    }
    for path, allowed_statuses in COMMERCE_PATHS:
        try:
            request_url = build_url(path)
            response = fetch(
                request_url,
                accept="text/html",
            )
            endpoint_passed = response.status in allowed_statuses
            browser_proof: dict[str, Any] | None = None
            robots_values: list[str] = []
            commerce_asset_results: list[dict[str, Any]] = []
            product_link_results: list[dict[str, Any]] = []
            required_class_present = False
            coming_soon_classes: list[str] = []
            language_findings: list[str] = []
            route_ui = ""
            directives: set[str] = set()
            if response.status == 200:
                validate_content_type(
                    response,
                    allowed_media_types={"text/html"},
                    allowed_charsets={None, "utf-8"},
                )
                facts = parse_html(response.text())
                by_id = element_index(facts)
                robots_values = facts.meta_values("robots")
                language_findings = public_language_findings(facts)
                (
                    commerce_assets_valid,
                    commerce_asset_results,
                ) = verify_commerce_assets(facts)
                required_class = required_classes[path]
                required_class_present = (
                    required_class in facts.body_classes
                )
                coming_soon_classes = sorted(
                    class_name
                    for class_name in facts.class_counts
                    if "coming-soon" in class_name.lower()
                )
                endpoint_passed = (
                    endpoint_passed
                    and valid_html_document(facts)
                    and facts.html_language == "en-US"
                    and facts.h1_count == 1
                    and facts.main_count == 1
                    and commerce_assets_valid
                    and required_class_present
                    and coming_soon_classes == []
                    and language_findings == []
                )
                scoped_directives = robots_directives_by_scope(
                    facts,
                    response.values("x-robots-tag"),
                )
                effective_directives = all_effective_robots_directives(
                    scoped_directives
                )
                directives = set().union(*scoped_directives.values())
                if path == "/shop/":
                    product_structure = (
                        facts.descendant_class_counts[
                            ("products", "product")
                        ] > 0
                        or facts.descendant_class_counts[
                            (
                                "wc-block-grid__products",
                                "wc-block-grid__product",
                            )
                        ] > 0
                        or facts.descendant_class_counts[
                            (
                                "wc-block-product-template",
                                "wc-block-product",
                            )
                        ] > 0
                    )
                    (
                        meaningful_product_cards,
                        product_links,
                    ) = product_catalog_card_links(facts)
                    product_structure = (
                        product_structure
                        and meaningful_product_cards
                    )
                    (
                        product_links_valid,
                        product_link_results,
                    ) = verify_product_catalog_links(product_links)
                    product_catalog = (
                        product_structure
                        and product_links_valid
                    )
                    reviewed_empty_state = (
                        facts.class_counts["woocommerce-info"] > 0
                        and "No products were found matching your selection."
                        in facts.class_text("woocommerce-info")
                    )
                    route_ui = (
                        "product_catalog"
                        if product_catalog and not reviewed_empty_state
                        else ""
                    )
                    endpoint_passed = endpoint_passed and (
                        route_ui == "product_catalog"
                    )
                    endpoint_passed = endpoint_passed and (
                        all(
                            directives_allow_indexing(
                                crawler_directives
                            )
                            for crawler_directives
                            in effective_directives.values()
                        )
                    )
                elif path == "/cart/":
                    classic_cart_forms = rendered_elements_with_class(
                        facts,
                        class_name="woocommerce-cart-form",
                        tag="form",
                    )
                    classic_cart_controls = (
                        owned_form_controls(
                            facts,
                            classic_cart_forms[0],
                            by_id,
                        )
                        if len(classic_cart_forms) == 1
                        else []
                    )
                    classic_cart = (
                        len(classic_cart_forms) == 1
                        and safe_commerce_href(
                            classic_cart_forms[0]["attrs"].get(
                                "action",
                                "",
                            ),
                            expected_path="/cart/",
                        )
                        and form_allows_submission(
                            classic_cart_forms[0]
                        )
                        and bool(
                            route_data_inputs(
                                classic_cart_controls,
                                by_id,
                                "cart",
                            )
                        )
                        and bool(
                            route_submit_controls(
                                classic_cart_controls,
                                by_id,
                                "cart",
                            )
                        )
                        and all(
                            submitter_allows_form(
                                control,
                                classic_cart_forms[0],
                                expected_path="/cart/",
                            )
                            for control in route_submit_controls(
                                classic_cart_controls,
                                by_id,
                                "cart",
                            )
                        )
                        and owned_hidden_nonce(
                            classic_cart_controls,
                            by_id,
                            "woocommerce-cart-nonce",
                        )
                    )
                    block_cart_scopes = rendered_elements_with_class(
                        facts,
                        class_name="wc-block-cart",
                    )
                    block_cart_controls = (
                        rendered_scope_controls(
                            facts,
                            block_cart_scopes[0],
                            by_id,
                        )
                        if len(block_cart_scopes) == 1
                        else []
                    )
                    block_cart = (
                        len(block_cart_scopes) == 1
                        and (
                            facts.descendant_class_counts[
                                (
                                    "wc-block-cart",
                                    "wc-block-cart-items",
                                )
                            ] > 0
                            or bool(
                                route_data_inputs(
                                    block_cart_controls,
                                    by_id,
                                    "cart",
                                )
                            )
                        )
                        and bool(
                            route_data_inputs(
                                block_cart_controls,
                                by_id,
                                "cart",
                            )
                        )
                        and bool(
                            route_submit_controls(
                                block_cart_controls,
                                by_id,
                                "cart",
                            )
                        )
                        and all(
                            (
                                form_owner(control, by_id) is not None
                                and form_allows_submission(
                                    form_owner(control, by_id)
                                )
                                and submitter_allows_form(
                                    control,
                                    form_owner(control, by_id),
                                    expected_path="/cart/",
                                    allow_empty=True,
                                )
                            )
                            for control in route_submit_controls(
                                block_cart_controls,
                                by_id,
                                "cart",
                            )
                        )
                    )
                    cart_form = (
                        classic_cart
                        or (
                            block_cart
                        )
                    )
                    reviewed_empty_state = (
                        (
                            facts.class_counts["cart-empty"] > 0
                            and facts.class_counts["return-to-shop"] > 0
                            and any(
                                safe_commerce_href(
                                    href,
                                    expected_path="/shop/",
                                )
                                for href in facts.link_hrefs_by_class[
                                    "return-to-shop"
                                ]
                            )
                        )
                        or (
                            facts.class_counts[
                                "wp-block-woocommerce-empty-cart-block"
                            ] > 0
                        )
                    ) and "Your cart is currently empty" in (
                        facts.class_text("cart-empty")
                        + " "
                        + facts.class_text(
                            "wp-block-woocommerce-empty-cart-block"
                        )
                    )
                    route_ui = (
                        "cart"
                        if cart_form
                        else (
                            "reviewed_empty_state"
                            if reviewed_empty_state
                            else ""
                        )
                    )
                    endpoint_passed = endpoint_passed and bool(route_ui)
                elif path == "/my-account/":
                    login_forms = rendered_elements_with_class(
                        facts,
                        class_name="woocommerce-form-login",
                        tag="form",
                    )
                    login_controls = (
                        owned_form_controls(
                            facts,
                            login_forms[0],
                            by_id,
                        )
                        if len(login_forms) == 1
                        else []
                    )
                    username_controls = [
                        control
                        for control in login_controls
                        if control["tag"] == "input"
                        and control["attrs"].get("name", "") == "username"
                        and control["attrs"].get(
                            "type",
                            "text",
                        ).strip().lower()
                        in {"", "email", "text"}
                        and control["rendered"]
                        and element_is_effectively_enabled(control, by_id)
                        and "readonly" not in control["attribute_names"]
                        and control["attrs"].get(
                            "aria-readonly",
                            "",
                        ).strip().lower()
                        != "true"
                    ]
                    password_controls = [
                        control
                        for control in login_controls
                        if control["tag"] == "input"
                        and control["attrs"].get("name", "") == "password"
                        and control["attrs"].get(
                            "type",
                            "text",
                        ).strip().lower()
                        == "password"
                        and control["rendered"]
                        and element_is_effectively_enabled(control, by_id)
                        and "readonly" not in control["attribute_names"]
                        and control["attrs"].get(
                            "aria-readonly",
                            "",
                        ).strip().lower()
                        != "true"
                    ]
                    login_form = (
                        len(login_forms) == 1
                        and safe_commerce_href(
                            login_forms[0]["attrs"].get("action", ""),
                            expected_path="/my-account/",
                            allow_empty=True,
                        )
                        and form_allows_submission(login_forms[0])
                        and len(username_controls) == 1
                        and len(password_controls) == 1
                        and bool(
                            route_submit_controls(
                                login_controls,
                                by_id,
                                "account",
                            )
                        )
                        and all(
                            submitter_allows_form(
                                control,
                                login_forms[0],
                                expected_path="/my-account/",
                                allow_empty=True,
                            )
                            for control in route_submit_controls(
                                login_controls,
                                by_id,
                                "account",
                            )
                        )
                        and owned_hidden_nonce(
                            login_controls,
                            by_id,
                            "woocommerce-login-nonce",
                        )
                    )
                    route_ui = "login_form" if login_form else ""
                    endpoint_passed = endpoint_passed and login_form
                elif path == "/checkout/":
                    checkout_forms = rendered_elements_with_class(
                        facts,
                        class_name="checkout",
                        tag="form",
                    )
                    checkout_controls = (
                        owned_form_controls(
                            facts,
                            checkout_forms[0],
                            by_id,
                        )
                        if len(checkout_forms) == 1
                        else []
                    )
                    classic_checkout = (
                        len(checkout_forms) == 1
                        and safe_commerce_href(
                            checkout_forms[0]["attrs"].get("action", ""),
                            expected_path="/checkout/",
                            allow_empty=True,
                        )
                        and form_allows_submission(checkout_forms[0])
                        and bool(
                            route_data_inputs(
                                checkout_controls,
                                by_id,
                                "checkout",
                            )
                        )
                        and len(
                            route_data_inputs(
                                checkout_controls,
                                by_id,
                                "checkout",
                            )
                        )
                        >= 6
                        and checkout_data_is_coherent(
                            checkout_controls,
                            by_id,
                            block_checkout=False,
                        )
                        and bool(
                            route_submit_controls(
                                checkout_controls,
                                by_id,
                                "checkout",
                            )
                        )
                        and all(
                            submitter_allows_form(
                                control,
                                checkout_forms[0],
                                expected_path="/checkout/",
                                allow_empty=True,
                            )
                            for control in route_submit_controls(
                                checkout_controls,
                                by_id,
                                "checkout",
                            )
                        )
                        and owned_hidden_nonce(
                            checkout_controls,
                            by_id,
                            "woocommerce-process-checkout-nonce",
                        )
                    )
                    block_checkout_scopes = rendered_elements_with_class(
                        facts,
                        class_name="wc-block-checkout",
                    )
                    block_checkout_controls = (
                        rendered_scope_controls(
                            facts,
                            block_checkout_scopes[0],
                            by_id,
                        )
                        if len(block_checkout_scopes) == 1
                        else []
                    )
                    block_checkout = (
                        len(block_checkout_scopes) == 1
                        and len(
                            route_data_inputs(
                                block_checkout_controls,
                                by_id,
                                "checkout",
                            )
                        )
                        >= 6
                        and checkout_data_is_coherent(
                            block_checkout_controls,
                            by_id,
                            block_checkout=True,
                        )
                        and bool(
                            route_submit_controls(
                                block_checkout_controls,
                                by_id,
                                "checkout",
                            )
                        )
                        and all(
                            (
                                form_owner(control, by_id) is not None
                                and form_allows_submission(
                                    form_owner(control, by_id)
                                )
                                and submitter_allows_form(
                                    control,
                                    form_owner(control, by_id),
                                    expected_path="/checkout/",
                                    allow_empty=True,
                                )
                            )
                            for control in route_submit_controls(
                                block_checkout_controls,
                                by_id,
                                "checkout",
                            )
                        )
                    )
                    checkout_form = (
                        classic_checkout
                        or (
                            block_checkout
                        )
                    )
                    route_ui = "checkout" if checkout_form else ""
                    endpoint_passed = endpoint_passed and checkout_form
                if path in {"/cart/", "/checkout/", "/my-account/"}:
                    endpoint_passed = endpoint_passed and (
                        "noindex" in scoped_directives["*"]
                        and all(
                            "noindex" in crawler_directives
                            and "index" not in crawler_directives
                            and "nofollow" not in crawler_directives
                            and "none" not in crawler_directives
                            for crawler_directives
                            in effective_directives.values()
                        )
                    )
                browser_proof = commerce_browser_proof(
                    mode={
                        "/shop/": "shop",
                        "/cart/": "cart",
                        "/checkout/": "checkout",
                        "/my-account/": "account",
                    }[path],
                    expected_path=path,
                    url=request_url,
                )
                endpoint_passed = (
                    endpoint_passed
                    and browser_proof["passed"]
                    and browser_proof["routeUi"] == route_ui
                )
            if response.status in {301, 302, 303, 307, 308}:
                locations = response.values("location")
                location = locations[0] if len(locations) == 1 else ""
                destination = urllib.parse.urljoin(
                    EXPECTED_ORIGIN + "/",
                    location,
                )
                endpoint_passed = (
                    endpoint_passed
                    and path == "/checkout/"
                    and len(locations) == 1
                    and destination == EXPECTED_ORIGIN + "/cart/"
                )
                route_ui = "empty_cart_redirect" if endpoint_passed else ""
                browser_proof = commerce_browser_proof(
                    mode="checkout",
                    expected_path="/checkout/",
                    url=request_url,
                )
                endpoint_passed = (
                    endpoint_passed
                    and browser_proof["passed"]
                    and browser_proof["routeUi"] == route_ui
                )
            passed = passed and endpoint_passed
            results.append(
                {
                    "path": path,
                    "status": response.status,
                    "locations": response.values("location"),
                    "robots": robots_values,
                    "robots_by_scope": {
                        scope: sorted(values)
                        for scope, values
                        in (
                            scoped_directives.items()
                            if response.status == 200
                            else []
                        )
                    },
                    "commerce_assets": commerce_asset_results,
                    "browser_proof": browser_proof,
                    "product_links": product_link_results,
                    "required_class": required_classes[path],
                    "required_class_present": required_class_present,
                    "coming_soon_classes": coming_soon_classes,
                    "language_findings": language_findings,
                    "route_ui": route_ui,
                }
            )
        except Exception as error:
            passed = False
            results.append(
                {"path": path, "error_type": type(error).__name__}
            )
    report.add(
        "commerce.routes",
        passed,
        "Shop, cart, checkout, and account behavior remains available with commerce assets.",
        evidence={"endpoints": results},
    )


def inactive_commerce_surface_evidence(
    response: HttpResult,
    *,
    path: str,
) -> tuple[bool, dict[str, Any]]:
    validate_content_type(
        response,
        allowed_media_types={"text/html"},
        allowed_charsets={None, "utf-8"},
    )
    facts = parse_html(response.text())
    language_findings = public_language_findings(facts)
    inherited_findings = legacy_text_findings(
        [facts.title, facts.body_text, facts.visible_attributes]
    )
    inactive_links = sorted(
        {
            href
            for href in facts.all_body_hrefs
            if inactive_commerce_url(href)
        }
    )
    public_surface = " ".join(
        [facts.title, facts.body_text, *facts.visible_attributes]
    )
    inactive_text_findings = sorted(
        label
        for label, pattern in (
            ("shop", re.compile(r"\bshop\b", re.I)),
            ("cart", re.compile(r"\bcart\b", re.I)),
            ("checkout", re.compile(r"\bcheckout\b", re.I)),
            ("account", re.compile(r"\bmy account\b", re.I)),
            ("product", re.compile(r"\bproducts?\b", re.I)),
        )
        if pattern.search(public_surface)
    )
    unexpected_commerce_classes = sorted(
        class_name
        for class_name in facts.class_counts
        if (
            "woocommerce" in class_name.lower()
            or class_name.lower().startswith("wc-block")
            or class_name.lower() == "rbtx-offer-evidence"
        )
    )
    unexpected_commerce_assets = sorted(
        url
        for url in facts.asset_urls()
        if any(
            marker in url.lower()
            for marker in ("woocommerce", "wc-block")
        )
    )
    cache_passed, cache_evidence = uncached_response_evidence(response)
    noindex_passed, robots_evidence = noindex_response_evidence(
        facts,
        response,
    )
    error_copy = (
        "The address may have changed. Try another search term or "
        "return to the atlas."
    )
    passed = (
        response.status == 410
        and response.values("location") == []
        and valid_html_document(facts)
        and facts.html_language == "en-US"
        and facts.h1_count == 1
        and facts.h1_texts == ["Page not found."]
        and facts.main_count == 1
        and "main-content" in facts.element_ids
        and facts.class_counts["rbtx-content-shell"] == 1
        and facts.body_text.count(error_copy) == 1
        and language_findings == []
        and inherited_findings == []
        and inactive_links == []
        and inactive_text_findings == []
        and unexpected_commerce_classes == []
        and unexpected_commerce_assets == []
        and cache_passed
        and noindex_passed
    )
    return passed, {
        "path": path,
        "status": response.status,
        "language": facts.html_language,
        "title": facts.title,
        "h1": facts.h1_texts,
        "h1_count": facts.h1_count,
        "main_count": facts.main_count,
        "main_target_present": "main-content" in facts.element_ids,
        "error_copy_count": facts.body_text.count(error_copy),
        "structure_errors": facts.structure_errors,
        "language_findings": language_findings,
        "inherited_text_findings": inherited_findings,
        "inactive_text_findings": inactive_text_findings,
        "inactive_links": inactive_links,
        "unexpected_commerce_classes": unexpected_commerce_classes,
        "unexpected_commerce_assets": unexpected_commerce_assets,
        "cache": cache_evidence,
        "robots": robots_evidence,
        "browser_purchase_proof": "not_run_for_inactive_surface",
    }


def verify_commerce(report: Report) -> None:
    results: list[dict[str, Any]] = []
    routes_passed = True
    for path in INACTIVE_COMMERCE_PATHS:
        try:
            response = fetch(
                build_url(path),
                accept="text/html",
            )
            endpoint_passed, evidence = (
                inactive_commerce_surface_evidence(
                    response,
                    path=path,
                )
            )
            routes_passed = routes_passed and endpoint_passed
            results.append(evidence)
        except Exception as error:
            routes_passed = False
            results.append(
                {"path": path, "error_type": type(error).__name__}
            )
    report.add(
        "commerce.routes",
        routes_passed,
        (
            "Inactive commerce page addresses are uncached, "
            "noindex, and use the established error surface."
        ),
        evidence={"endpoints": results},
    )

    try:
        home_response = fetch(
            build_url("/"),
            accept="text/html",
        )
        validate_content_type(
            home_response,
            allowed_media_types={"text/html"},
            allowed_charsets={None, "utf-8"},
        )
        home_facts = parse_html(home_response.text())
        inactive_links = sorted(
            {
                href
                for href in home_facts.all_body_hrefs
                if inactive_commerce_url(href)
            }
        )
        by_id = element_index(home_facts)
        navigation_links = sorted(
            {
                element["attrs"].get("href", "")
                for element in home_facts.elements
                if (
                    element["tag"] == "a"
                    and inactive_commerce_url(
                        element["attrs"].get("href", "")
                    )
                    and any(
                        ancestor["tag"] == "nav"
                        for ancestor in element_ancestors(
                            element,
                            by_id,
                        )
                    )
                )
            }
        )
        report.add(
            "commerce.navigation",
            home_response.status == 200
            and valid_html_document(home_facts)
            and home_facts.html_language == "en-US"
            and inactive_links == []
            and navigation_links == [],
            (
                "Public navigation and homepage links omit inactive "
                "commerce and product addresses."
            ),
            evidence={
                "http_status": home_response.status,
                "inactive_links": inactive_links,
                "navigation_links": navigation_links,
            },
        )
    except Exception as error:
        report.exception(
            "commerce.navigation",
            "Inactive commerce navigation could not be verified.",
            error,
        )


def verify_robots(report: Report) -> None:
    try:
        response = fetch(
            build_url("/robots.txt"),
            accept="text/plain",
        )
        validate_content_type(
            response,
            allowed_media_types={"text/plain"},
            allowed_charsets={None, "utf-8"},
        )
        text = response.text()
        policy = parse_robots_policy(text)
        sitemap_results: list[dict[str, Any]] = []
        sitemap_passed = 0 < len(policy["sitemaps"]) <= 10
        all_sitemap_urls: list[str] = []
        all_content_urls: list[str] = []
        for sitemap_url in policy["sitemaps"]:
            try:
                validate_canonical_url(sitemap_url)
                sitemap_urls: list[str] = []
                content_urls: list[str] = []
                verify_sitemap_document(
                    sitemap_url,
                    depth=0,
                    visited=set(),
                    sitemap_urls=sitemap_urls,
                    content_urls=content_urls,
                )
                all_sitemap_urls.extend(sitemap_urls)
                all_content_urls.extend(content_urls)
                sitemap_results.append(
                    {
                        "url": sitemap_url,
                        "sitemaps": len(sitemap_urls),
                        "content_urls": len(content_urls),
                    }
                )
            except Exception as error:
                sitemap_passed = False
                sitemap_results.append(
                    {
                        "url": sitemap_url,
                        "error_type": type(error).__name__,
                    }
                )
        forbidden_sitemaps = sorted(
            {
                url
                for url in all_sitemap_urls
                if (
                    "posts-robot-" in url
                    or "sitemap-users-" in url
                    or inactive_product_sitemap_url(url)
                )
            }
        )
        forbidden_content = sorted(
            {url for url in all_content_urls if legacy_url(url)}
        )
        passed = (
            response.status == 200
            and policy["blocks_root"] is False
            and policy["blocked_agents"] == []
            and policy["blocked_public_paths"] == []
            and EXPECTED_ORIGIN + "/wp-sitemap.xml"
            in policy["sitemaps"]
            and sitemap_passed
            and forbidden_sitemaps == []
            and forbidden_content == []
            and EXPECTED_ORIGIN + "/" in set(all_content_urls)
        )
        report.add(
            "seo.root_robots",
            passed,
            "Root robots policy is reachable and does not block the public site.",
            evidence={
                "http_status": response.status,
                "sitemaps": policy["sitemaps"],
                "blocks_root": policy["blocks_root"],
                "blocked_agents": policy["blocked_agents"],
                "blocked_public_paths": policy[
                    "blocked_public_paths"
                ],
                "public_path_access": policy["public_path_access"],
                "root_access": policy["root_access"],
                "sitemap_results": sitemap_results,
                "forbidden_sitemaps": forbidden_sitemaps,
                "forbidden_content": forbidden_content,
                "homepage_present": (
                    EXPECTED_ORIGIN + "/" in set(all_content_urls)
                ),
            },
        )
    except Exception as error:
        report.exception(
            "seo.root_robots",
            "Root robots policy could not be verified.",
            error,
        )


def verify_performance(report: Report, samples: int) -> None:
    try:
        performance_url = build_url("/", cache_buster=False)
        warmup = fetch(
            performance_url,
            accept="text/html",
            no_cache=False,
        )
        timings = [warmup] + [
            fetch(
                performance_url,
                accept="text/html",
                no_cache=False,
            )
            for _ in range(samples)
        ]
        identity_results: list[dict[str, Any]] = []
        identity_passed = True
        for result in timings:
            validate_content_type(
                result,
                allowed_media_types={"text/html"},
                allowed_charsets={None, "utf-8"},
            )
            facts = parse_html(result.text())
            marker_versions = [
                match.group(1)
                for comment in facts.body_comments
                if (
                    match := re.fullmatch(
                        r"robbottx-core:(\d+\.\d+\.\d+)",
                        comment,
                    )
                )
            ]
            scoped_robots = robots_directives_by_scope(
                facts,
                result.values("x-robots-tag"),
            )
            effective_robots = all_effective_robots_directives(
                scoped_robots
            )
            indexable = all(
                directives_allow_indexing(directives)
                for directives in effective_robots.values()
            )
            sample_passed = (
                result.status == 200
                and result.final_url == performance_url
                and valid_html_document(facts)
                and marker_versions == [report.plugin_version]
                and report.previous_plugin_version not in marker_versions
                and facts.title == HOME_DOCUMENT_TITLE
                and indexable
            )
            identity_passed = identity_passed and sample_passed
            identity_results.append(
                {
                    "status": result.status,
                    "final_url": result.final_url,
                    "marker_versions": marker_versions,
                    "title": facts.title,
                    "structure_errors": facts.structure_errors,
                    "indexable": indexable,
                }
            )
        report.add(
            "runtime.warm_cache_identity",
            identity_passed,
            "Every warm homepage response is the exact current release.",
            evidence={"responses": identity_results},
        )
        measured_timings = timings[1:]
        statuses = [result.status for result in measured_timings]
        header_values = [
            result.header_seconds for result in measured_timings
        ]
        total_values = [
            result.total_seconds for result in measured_timings
        ]
        median_header = statistics.median(header_values)
        median_total = statistics.median(total_values)
        passed = (
            all(status == 200 for status in statuses)
            and median_header <= 1.5
            and median_total <= 3.0
        )
        report.add(
            "performance.warm_https",
            passed,
            "Warm unauthenticated homepage response stays within the release budget.",
            evidence={
                "samples": samples,
                "statuses": statuses,
                "header_seconds": {
                    "median": round(median_header, 4),
                    "min": round(min(header_values), 4),
                    "max": round(max(header_values), 4),
                },
                "total_seconds": {
                    "median": round(median_total, 4),
                    "min": round(min(total_values), 4),
                    "max": round(max(total_values), 4),
                },
                "server_timing": measured_timings[-1].values(
                    "server-timing"
                ),
                "budget": {
                    "median_header_seconds": 1.5,
                    "median_total_seconds": 3.0,
                },
            },
            warning=True,
        )
    except Exception as error:
        if not any(
            check.check_id == "runtime.warm_cache_identity"
            for check in report.checks
        ):
            report.exception(
                "runtime.warm_cache_identity",
                "Warm homepage release identity could not be verified.",
                error,
            )
        report.exception(
            "performance.warm_https",
            "Warm HTTPS timing could not be measured.",
            error,
            warning=True,
        )


def run(args: argparse.Namespace) -> dict[str, Any]:
    validate_args(args)
    report = Report(
        plugin_version=args.plugin_version,
        previous_plugin_version=args.previous_plugin_version,
        theme_version=args.theme_version,
        record_hash=args.record_hash,
        expect_fallback_favicon=args.expect_fallback_favicon,
        configured_site_icon_urls=tuple(args.configured_site_icon_url),
    )
    verify_health(report)
    verify_home(report, args.previous_plugin_version)
    verify_route_inventory(report)
    verify_rest(report)
    verify_sitemaps(report)
    verify_legacy_html(report)
    verify_search_and_feed(report)
    verify_error_page(report)
    verify_commerce(report)
    verify_robots(report)
    verify_performance(report, args.samples)
    return report.payload(
        parse_warning_decisions(args.warning_decision)
    )


def write_new_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    )
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    args = parse_args()
    try:
        payload = run(args)
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "ERROR",
                    "error_type": type(error).__name__,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    write_new_atomic(args.output, encoded)
    sys.stdout.write(encoded)
    return (
        0
        if payload["status"] in {"PASS", "PASS_WITH_ACCEPTED_WARNINGS"}
        else 1
    )


if __name__ == "__main__":
    sys.exit(main())
