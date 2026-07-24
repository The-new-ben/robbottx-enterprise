#!/usr/bin/env python3
"""Apply and verify the reviewed RobbottX WooCommerce visibility settings."""

from __future__ import annotations

import argparse
import datetime
import functools
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import types
import urllib.parse
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MAX_TRUSTED_GIT_EXECUTABLE_BYTES = 128 * 1024 * 1024
MAX_TRUSTED_GIT_OUTPUT_BYTES = 128 * 1024 * 1024
TRUSTED_GIT_TIMEOUT_SECONDS = 60
MAX_SHARED_OPS_BYTES = 4 * 1024 * 1024
MAX_BOUNDARY_VERIFIER_BYTES = 4 * 1024 * 1024
MAX_ROUTE_TEMPLATE_BYTES = 1024 * 1024
SHARED_OPS_MODULE_NAME = "_robbottx_commerce_indexed_wordpress_ops"
BOUNDARY_VERIFIER_MODULE_NAME = (
    "_robbottx_commerce_indexed_boundary_verifier"
)
SHARED_OPS_RELATIVE_PATH = "scripts/deploy-wordpress-theme.py"
BOUNDARY_VERIFIER_RELATIVE_PATH = "scripts/deploy-wordpress.py"
ROUTE_TEMPLATE_RELATIVE_PATH = (
    "scripts/templates/configure-commerce-route.php.txt"
)


class _BootstrapFailure(RuntimeError):
    """A failure before the reviewed shared operations module is available."""


def _posix_system_owned_path(path: Path) -> bool:
    current = path
    while True:
        try:
            metadata = current.stat()
        except OSError:
            return False
        if metadata.st_uid != 0 or metadata.st_mode & 0o022:
            return False
        if current.parent == current:
            return True
        current = current.parent


def _trusted_windows_git_roots() -> list[Path]:
    roots = [Path("C:/Program Files/Git")]
    try:
        import winreg
    except ImportError:
        return roots

    for access_mode in {
        winreg.KEY_READ,
        winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0),
        winreg.KEY_READ | getattr(winreg, "KEY_WOW64_32KEY", 0),
    }:
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\GitForWindows",
                0,
                access_mode,
            ) as key:
                install_path, value_type = winreg.QueryValueEx(
                    key,
                    "InstallPath",
                )
        except OSError:
            continue
        if (
            value_type in (winreg.REG_SZ, winreg.REG_EXPAND_SZ)
            and isinstance(install_path, str)
            and install_path
        ):
            roots.append(Path(install_path))
    return roots


def resolve_trusted_git_executable() -> Path:
    candidates: list[tuple[Path, Path | None]] = []
    if os.name == "nt":
        for root in _trusted_windows_git_roots():
            candidates.extend(
                (
                    (root / "cmd" / "git.exe", root),
                    (root / "bin" / "git.exe", root),
                )
            )
    else:
        candidates.extend(
            (Path(value), None)
            for value in (
                "/usr/bin/git",
                "/bin/git",
                "/usr/local/bin/git",
            )
        )

    seen: set[Path] = set()
    for candidate, trusted_root in candidates:
        try:
            resolved = candidate.resolve(strict=True)
            metadata = resolved.stat()
        except (OSError, RuntimeError):
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size <= 0
            or metadata.st_size > MAX_TRUSTED_GIT_EXECUTABLE_BYTES
        ):
            continue
        if trusted_root is not None:
            try:
                resolved.relative_to(trusted_root.resolve(strict=True))
            except (OSError, RuntimeError, ValueError):
                continue
        elif not _posix_system_owned_path(resolved):
            continue
        return resolved
    raise _BootstrapFailure(
        "No protected absolute Git executable is available."
    )


def _trusted_git_environment(git_executable: Path) -> dict[str, str]:
    path_entries = [str(git_executable.parent)]
    if os.name == "nt":
        git_root = git_executable.parent.parent
        path_entries.extend(
            str(path)
            for path in (
                git_root / "cmd",
                git_root / "bin",
                git_root / "mingw64" / "bin",
                Path("C:/Windows/System32"),
            )
            if path.is_dir()
        )
    else:
        path_entries.extend(("/usr/bin", "/bin"))
    return {
        "PATH": os.pathsep.join(dict.fromkeys(path_entries)),
        "LANG": "C",
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.fsmonitor",
        "GIT_CONFIG_VALUE_0": "false",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
        "GIT_TERMINAL_PROMPT": "0",
        "PAGER": "cat",
    }


def _run_trusted_git(
    repository_root: Path,
    arguments: list[str],
    *,
    text: bool,
) -> subprocess.CompletedProcess:
    git_executable = resolve_trusted_git_executable()
    completed = subprocess.run(
        [
            str(git_executable),
            "-C",
            str(repository_root),
            *arguments,
        ],
        capture_output=True,
        check=False,
        text=text,
        timeout=TRUSTED_GIT_TIMEOUT_SECONDS,
        env=_trusted_git_environment(git_executable),
    )
    for stream in (completed.stdout, completed.stderr):
        if (
            isinstance(stream, (bytes, str))
            and len(stream) > MAX_TRUSTED_GIT_OUTPUT_BYTES
        ):
            raise _BootstrapFailure(
                "Git output exceeded the bootstrap safety limit."
            )
    return completed


def read_clean_index_file(
    repository_root: Path,
    relative_path: str,
    *,
    max_bytes: int,
) -> tuple[bytes, str]:
    """Read an ordinary stage-zero blob that exactly matches HEAD.

    Worktree bytes are deliberately never opened. The later release-boundary
    scan proves that the complete repository still matches this reviewed HEAD.
    """

    try:
        resolved_root = Path(repository_root).resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise _BootstrapFailure(
            "Reviewed repository root could not be resolved."
        ) from error
    candidate = PurePosixPath(relative_path)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or "." in candidate.parts
        or ".." in candidate.parts
        or candidate.as_posix() != relative_path
        or max_bytes <= 0
    ):
        raise _BootstrapFailure("Reviewed repository path is invalid.")

    head_before_result = _run_trusted_git(
        resolved_root,
        ["rev-parse", "HEAD"],
        text=True,
    )
    head = (
        head_before_result.stdout.strip()
        if head_before_result.returncode == 0
        and isinstance(head_before_result.stdout, str)
        else ""
    )
    if re.fullmatch(r"[0-9a-f]{40}", head) is None:
        raise _BootstrapFailure("Reviewed Git HEAD could not be established.")

    index_result = _run_trusted_git(
        resolved_root,
        [
            "ls-files",
            "-z",
            "--cached",
            "--stage",
            "--",
            relative_path,
        ],
        text=False,
    )
    if (
        index_result.returncode != 0
        or not isinstance(index_result.stdout, bytes)
    ):
        raise _BootstrapFailure(
            "Reviewed Git index entry could not be read."
        )
    entries = [
        entry
        for entry in index_result.stdout.split(b"\x00")
        if entry
    ]
    if len(entries) != 1:
        raise _BootstrapFailure(
            "Reviewed file has no unique stage-zero Git index entry."
        )
    try:
        metadata, raw_path = entries[0].split(b"\t", 1)
        mode, object_id_bytes, stage = metadata.split()
        indexed_path = raw_path.decode(
            "utf-8",
            errors="surrogateescape",
        ).replace("\\", "/")
        object_id = object_id_bytes.decode("ascii")
    except (UnicodeDecodeError, ValueError) as error:
        raise _BootstrapFailure(
            "Reviewed Git index entry is malformed."
        ) from error
    if (
        mode not in {b"100644", b"100755"}
        or stage != b"0"
        or indexed_path != relative_path
        or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", object_id)
        is None
    ):
        raise _BootstrapFailure(
            "Reviewed Git index entry is not an exact ordinary file."
        )

    head_blob_result = _run_trusted_git(
        resolved_root,
        ["rev-parse", f"HEAD:{relative_path}"],
        text=True,
    )
    head_object_id = (
        head_blob_result.stdout.strip()
        if head_blob_result.returncode == 0
        and isinstance(head_blob_result.stdout, str)
        else ""
    )
    if not secrets.compare_digest(object_id, head_object_id):
        raise _BootstrapFailure(
            "Reviewed file is staged differently from the current HEAD."
        )

    size_result = _run_trusted_git(
        resolved_root,
        ["cat-file", "-s", object_id],
        text=True,
    )
    try:
        object_size = int(size_result.stdout.strip())
    except (AttributeError, TypeError, ValueError) as error:
        raise _BootstrapFailure(
            "Reviewed Git object size could not be established."
        ) from error
    if (
        size_result.returncode != 0
        or object_size <= 0
        or object_size > max_bytes
    ):
        raise _BootstrapFailure(
            "Reviewed Git object exceeds its bootstrap limit."
        )
    blob_result = _run_trusted_git(
        resolved_root,
        ["cat-file", "blob", object_id],
        text=False,
    )
    if (
        blob_result.returncode != 0
        or not isinstance(blob_result.stdout, bytes)
        or len(blob_result.stdout) != object_size
    ):
        raise _BootstrapFailure(
            "Reviewed Git object bytes could not be read exactly."
        )

    head_after_result = _run_trusted_git(
        resolved_root,
        ["rev-parse", "HEAD"],
        text=True,
    )
    head_after = (
        head_after_result.stdout.strip()
        if head_after_result.returncode == 0
        and isinstance(head_after_result.stdout, str)
        else ""
    )
    if not secrets.compare_digest(head, head_after):
        raise _BootstrapFailure(
            "Reviewed Git HEAD changed during bootstrap."
        )
    return blob_result.stdout, head


def load_clean_index_module(
    repository_root: Path,
    relative_path: str,
    module_name: str,
    *,
    max_bytes: int,
) -> tuple[types.ModuleType, str]:
    payload, git_head = read_clean_index_file(
        repository_root,
        relative_path,
        max_bytes=max_bytes,
    )
    module_path = repository_root.joinpath(
        *PurePosixPath(relative_path).parts
    )
    previous_module = sys.modules.get(module_name)
    had_previous_module = module_name in sys.modules
    try:
        module = types.ModuleType(module_name)
        module.__file__ = str(module_path)
        module.__package__ = None
        sys.modules[module_name] = module
        exec(
            compile(payload, str(module_path), "exec"),
            module.__dict__,
        )
        return module, git_head
    except Exception as error:
        raise _BootstrapFailure(
            "Reviewed indexed Python module could not be loaded."
        ) from error
    finally:
        if had_previous_module:
            sys.modules[module_name] = previous_module
        else:
            sys.modules.pop(module_name, None)


try:
    ops, OPS_GIT_HEAD = load_clean_index_module(
        REPOSITORY_ROOT,
        SHARED_OPS_RELATIVE_PATH,
        SHARED_OPS_MODULE_NAME,
        max_bytes=MAX_SHARED_OPS_BYTES,
    )
except Exception as error:
    raise RuntimeError(
        "Reviewed WordPress operations could not be bootstrapped."
    ) from error

FIXED_ROUTE_PATH = "/wp-json/agentconfigure/v1/run"
CONFIGURATION_NAMESPACE = "/agentconfigure"
MAX_STYLESHEET_COUNT = 50
MAX_STYLESHEET_BYTES = 2 * 1024 * 1024
MAX_TOTAL_STYLESHEET_BYTES = 12 * 1024 * 1024
MAX_CODE_SNIPPETS_RECORDS = 98
CSS_TREE_PARSER = r"""
import fs from 'node:fs';
const csstree = await import(__CSS_TREE_MODULE_URL__);

const css = fs.readFileSync(0, 'utf8');
const parseErrors = [];
let ast;
try {
  ast = csstree.parse(css, {
    context: 'stylesheet',
    positions: false,
    onParseError(error) {
      parseErrors.push(error.message);
    }
  });
} catch {
  process.exit(2);
}

let ambiguous = parseErrors.length > 0;
let usableDeclarations = 0;
const imports = [];
const rules = [];

csstree.walk(ast, {
  enter(node) {
    if (node.type === 'Raw') {
      const declaration = this.declaration;
      const cssFunction = this.function;
      const rawValue = csstree.generate(node).trim();
      if (
        declaration?.type === 'Declaration' &&
        declaration.property.startsWith('--') &&
        declaration.value === node &&
        rawValue !== ''
      ) {
        return;
      }
      if (
        declaration?.type === 'Declaration' &&
        cssFunction?.type === 'Function' &&
        ['env', 'var'].includes(cssFunction.name.toLowerCase()) &&
        rawValue !== ''
      ) {
        return;
      }
      ambiguous = true;
      return;
    }
    if (node.type === 'Atrule' && node.name.toLowerCase() === 'import') {
      imports.push(csstree.generate(node.prelude));
      return;
    }
    if (node.type === 'Declaration') {
      const value = csstree.generate(node.value).trim();
      if (value === '') {
        ambiguous = true;
      } else {
        usableDeclarations += 1;
      }
      return;
    }
    if (node.type !== 'Rule') {
      return;
    }
    const keyframes = this.atrule?.name
      ?.toLowerCase()
      .endsWith('keyframes');
    if (keyframes) {
      if (node.prelude?.type !== 'SelectorList') {
        ambiguous = true;
        return;
      }
      node.prelude.children.forEach((selector) => {
        if (
          selector.type !== 'Selector' ||
          selector.children.size !== 1
        ) {
          ambiguous = true;
          return;
        }
        const part = selector.children.first;
        if (
          part.type === 'TypeSelector' &&
          ['from', 'to'].includes(part.name.toLowerCase())
        ) {
          return;
        }
        if (part.type === 'Percentage') {
          const percentage = Number(part.value);
          if (
            Number.isFinite(percentage) &&
            percentage >= 0 &&
            percentage <= 100
          ) {
            return;
          }
        }
        ambiguous = true;
      });
      return;
    }
    if (node.prelude?.type !== 'SelectorList') {
      ambiguous = true;
      return;
    }
    const declarations = [];
    node.block.children.forEach((child) => {
      if (child.type === 'Declaration') {
        declarations.push({
          important: Boolean(child.important),
          property: child.property,
          value: csstree.generate(child.value)
        });
      }
    });
    if (declarations.length > 0) {
      rules.push({
        declarations,
        selectors: csstree.generate(node.prelude)
      });
    }
  }
});

process.stdout.write(JSON.stringify({
  ambiguous,
  imports,
  rules,
  usable_declarations: usableDeclarations
}));
"""
ROUTE_TEMPLATE_SHA256 = (
    "30f2a9bf8f4a4cd2393ac22085b02ea7"
    "679fa92af1d59ef11f737aa5bb7d08c9"
)
COMMERCE_DOM_HELPER_PATH = (
    REPOSITORY_ROOT / "tools" / "qa" / "verify-commerce-dom.mjs"
)
COMMERCE_DOM_HELPER_SHA256 = (
    "e3d3fdbfe678fd9f2f637db0814c6dad"
    "be14cde2c6e44cdd41b9cbdaee597df4"
)
EXPECTED_PUPPETEER_VERSION = "25.3.0"
EXPECTED_PUPPETEER_URL = (
    "https://registry.npmjs.org/puppeteer-core/-/"
    "puppeteer-core-25.3.0.tgz"
)
EXPECTED_PUPPETEER_INTEGRITY = (
    "sha512-fm+wpUr2oigH1PXZvwgATrM2tYWHMDG8ASzTEe9uukCye4X5Ldx1K5"
    "BTHPFKITrIWvQQAQ256d1NpbEveBcKjA=="
)
COMMERCE_DOM_SCHEMA_VERSION = "1.0"
COMMERCE_DOM_PROCESS_TIMEOUT_SECONDS = 75
COMMERCE_DOM_PROFILE_PREFIX = "robbottx-commerce-browser-"
MAX_COMMERCE_DOM_OUTPUT_BYTES = 64 * 1024
COMMERCE_DOM_ENVIRONMENT_ALLOWLIST = frozenset(
    {
        "comspec",
        "home",
        "homedrive",
        "homepath",
        "lang",
        "lc_all",
        "localappdata",
        "path",
        "pathext",
        "systemroot",
        "temp",
        "tmp",
        "tz",
        "userprofile",
        "windir",
        "xdg_runtime_dir",
    }
)
EXPECTED_PAGES = {
    29: ("shop", "Shop"),
    30: ("cart", "Cart"),
    31: ("checkout", "Checkout"),
    32: ("my-account", "My account"),
}
TITLE_EVIDENCE_SCHEMA = {
    "cart": None,
    "checkout": None,
    "my-account": None,
    "shop": None,
}
OPTION_EVIDENCE_SCHEMA = {
    "coming_soon": None,
    "store_pages_only": None,
}
PAGE_ID_EVIDENCE_SCHEMA = {
    "cart": None,
    "checkout": None,
    "my-account": None,
    "shop": None,
}
COMMERCE_EVIDENCE_SCHEMA = {
    "after": {
        "page_mappings_unchanged": None,
        "public_store_verified": None,
        "store_pages_only_unchanged": None,
        "titles": TITLE_EVIDENCE_SCHEMA,
        "woocommerce_options": OPTION_EVIDENCE_SCHEMA,
        "woocommerce_page_ids": PAGE_ID_EVIDENCE_SCHEMA,
    },
    "authority_verified": None,
    "before": {
        "titles": TITLE_EVIDENCE_SCHEMA,
        "woocommerce_options": OPTION_EVIDENCE_SCHEMA,
        "woocommerce_page_ids": PAGE_ID_EVIDENCE_SCHEMA,
    },
    "callback_confirmed": None,
    "cleanup": {
        "attempted": None,
        "fixed_route_absent": None,
        "proven": None,
        "required": None,
        "route_absent": None,
        "snippet_absent": None,
    },
    "execute": None,
    "failure_stage": None,
    "failure_type": None,
    "fixed_route_absent_before": None,
    "page_identities_verified": None,
    "recorded_at": None,
    "route_absent_before": None,
    "schema_version": None,
    "snippet_count_before": None,
    "snippet_limit": None,
    "snippet_name_absent_before": None,
    "status": None,
}


class CommercePageFacts(HTMLParser):
    """Collect customer-visible facts from the rendered Shop document."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.html_language = ""
        self.title_parts: list[str] = []
        self.h1_parts: list[str] = []
        self.body_text_parts: list[str] = []
        self.visible_attributes: list[str] = []
        self.body_classes: set[str] = set()
        self.class_counts: Counter[str] = Counter()
        self.woocommerce_info_parts: list[str] = []
        self.woocommerce_info_in_main_count = 0
        self.body_count = 0
        self.head_count = 0
        self.h1_count = 0
        self.h1_inside_main_count = 0
        self.html_count = 0
        self.main_count = 0
        self.invalid_markup = False
        self.product_catalog = False
        self.product_item_count = 0
        self.product_links: list[str] = []
        self.valid_product_item_count = 0
        self.style_parts: list[str] = []
        self.title_count = 0
        self.title_inside_head_count = 0
        self._in_head = False
        self._in_title = False
        self._in_body = False
        self._h1_depth = 0
        self._hidden_depth = 0
        self._main_depth = 0
        self._product_contexts: list[dict[str, Any]] = []
        self._stack: list[tuple[str, set[str], bool]] = []
        self._style_depth = 0

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

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        tag = tag.lower()
        attribute_names = [name.lower() for name, _ in attrs]
        if len(attribute_names) != len(set(attribute_names)):
            self.invalid_markup = True
        values: dict[str, str] = {}
        for name, value in attrs:
            values.setdefault(name.lower(), value or "")
        attribute_name_set = set(attribute_names)
        classes = set(values.get("class", "").split())
        if tag == "html":
            self.html_count += 1
            self.html_language = values.get("lang", "")
        if tag == "head":
            self.head_count += 1
            self._in_head = True
        if tag == "title":
            self.title_count += 1
            if self._in_head:
                self.title_inside_head_count += 1
            self._in_title = True
        if tag == "style":
            self._style_depth += 1
        if tag == "body":
            self.body_count += 1
            self._in_head = False
            self._in_body = True
            self.body_classes.update(classes)
        hides_content = self._in_body and (
            tag in {"script", "style", "noscript"}
            or tag == "template"
            or tag == "dialog"
            and "open" not in attribute_name_set
            or tag == "details"
            and "open" not in attribute_name_set
            or "hidden" in attribute_name_set
            or "inert" in attribute_name_set
            or values.get("aria-hidden", "").strip().lower() == "true"
            or css_declarations_hide(values.get("style", ""))
        )
        if self._in_body:
            self.class_counts.update(classes)
            ancestor_classes = {
                class_name
                for _, element_classes, _ in self._stack
                for class_name in element_classes
            }
            product_pairs = {
                ("products", "product"),
                ("wc-block-grid__products", "wc-block-grid__product"),
                ("wc-block-product-template", "wc-block-product"),
            }
            is_product_root = any(
                self._main_depth
                and self._hidden_depth == 0
                and not hides_content
                and parent in ancestor_classes
                and child in classes
                for parent, child in product_pairs
            )
            if is_product_root:
                self.product_item_count += 1
                self._product_contexts.append(
                    {
                        "content": False,
                        "links": [],
                        "root_index": len(self._stack),
                    }
                )
            if (
                self._main_depth
                and self._hidden_depth == 0
                and not hides_content
                and "woocommerce-info" in classes
            ):
                self.woocommerce_info_in_main_count += 1
        if tag == "main" and self._in_body:
            self.main_count += 1
            self._main_depth += 1
        if hides_content:
            self._hidden_depth += 1
        if tag == "h1" and self._in_body:
            self.h1_count += 1
            if self._main_depth:
                self.h1_inside_main_count += 1
            self._h1_depth += 1
        if self._in_body and self._hidden_depth == 0:
            for name in ("alt", "aria-label", "title", "placeholder"):
                if values.get(name):
                    self.visible_attributes.append(values[name])
                    if self._product_contexts:
                        self._product_contexts[-1]["content"] = True
            href = values.get("href", "").strip()
            product_link_classes = {
                "woocommerce-LoopProduct-link",
                "woocommerce-loop-product__link",
                "wc-block-components-product-name",
                "wc-block-grid__product-link",
            }
            if (
                tag == "a"
                and self._product_contexts
                and not classes.isdisjoint(product_link_classes)
                and (
                    href.startswith("/")
                    and not href.startswith("//")
                    or href.startswith("https://robbottx.com/")
                )
            ):
                self._product_contexts[-1]["links"].append(href)
        if tag not in self.VOID_ELEMENTS:
            self._stack.append((tag, classes, hides_content))
        elif hides_content:
            self._hidden_depth = max(0, self._hidden_depth - 1)

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
        if tag == "title":
            self._in_title = False
        if tag == "style" and self._style_depth:
            self._style_depth -= 1
        if tag == "head":
            self._in_head = False
        if tag == "h1" and self._h1_depth:
            self._h1_depth -= 1
        if tag == "main" and self._main_depth:
            self._main_depth -= 1
        if tag == "body":
            self._in_body = False
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                removed = self._stack[index:]
                self._hidden_depth = max(
                    0,
                    self._hidden_depth
                    - sum(
                        1
                        for _, _, hides_content in removed
                        if hides_content
                    ),
                )
                remaining_contexts: list[dict[str, Any]] = []
                for context in self._product_contexts:
                    if context["root_index"] >= index:
                        if context["content"] and context["links"]:
                            self.product_catalog = True
                            self.valid_product_item_count += 1
                            self.product_links.extend(context["links"])
                    else:
                        remaining_contexts.append(context)
                self._product_contexts = remaining_contexts
                del self._stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if self._style_depth:
            self.style_parts.append(data)
        if self._in_title:
            self.title_parts.append(data)
        if self._in_body and self._hidden_depth == 0:
            stripped = data.strip()
            if stripped:
                self.body_text_parts.append(stripped)
                if self._h1_depth:
                    self.h1_parts.append(stripped)
                if self._product_contexts:
                    self._product_contexts[-1]["content"] = True
                if self._main_depth and any(
                    "woocommerce-info" in classes
                    for _, classes, _ in self._stack
                ):
                    self.woocommerce_info_parts.append(stripped)

    @staticmethod
    def normalize(parts: list[str]) -> str:
        return " ".join(" ".join(parts).split())

    @property
    def title(self) -> str:
        return self.normalize(self.title_parts)

    @property
    def h1(self) -> str:
        return self.normalize(self.h1_parts)

    @property
    def public_text(self) -> str:
        return self.normalize(
            self.body_text_parts + self.visible_attributes
        )

    @property
    def woocommerce_info_text(self) -> str:
        return self.normalize(self.woocommerce_info_parts)


def strip_top_level_css_important(value: str) -> tuple[str, bool]:
    quote = ""
    escaped = False
    depths = {"(": 0, "[": 0, "{": 0}
    closing = {")": "(", "]": "[", "}": "{"}
    important_markers: list[int] = []
    for index, character in enumerate(value):
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            continue
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if character in {"'", '"'}:
            quote = character
            continue
        if character in depths:
            depths[character] += 1
            continue
        if character in closing:
            opening = closing[character]
            if depths[opening]:
                depths[opening] -= 1
            continue
        if (
            character == "!"
            and all(depth == 0 for depth in depths.values())
        ):
            important_markers.append(index)
    if important_markers:
        marker = important_markers[-1]
        if re.fullmatch(
            r"!\s*important\s*",
            value[marker:],
            flags=re.IGNORECASE,
        ):
            return value[:marker].rstrip(), True
    return value, False


def parse_inline_css_declarations(
    declarations: str,
) -> list[dict[str, Any]] | None:
    without_comments: list[str] = []
    index = 0
    quote = ""
    while index < len(declarations):
        character = declarations[index]
        if quote:
            without_comments.append(character)
            if character == "\\" and index + 1 < len(declarations):
                index += 1
                without_comments.append(declarations[index])
            elif character == quote:
                quote = ""
            index += 1
            continue
        if character == "\\":
            without_comments.append(character)
            if index + 1 < len(declarations):
                index += 1
                without_comments.append(declarations[index])
            index += 1
            continue
        if character in {"'", '"'}:
            quote = character
            without_comments.append(character)
            index += 1
            continue
        if declarations.startswith("/*", index):
            comment_end = declarations.find("*/", index + 2)
            if comment_end < 0:
                return None
            index = comment_end + 2
            continue
        without_comments.append(character)
        index += 1
    if quote:
        return None

    records: list[dict[str, Any]] = []
    declaration_start = 0
    colon_index: int | None = None
    quote = ""
    escaped = False
    depths = {"(": 0, "[": 0, "{": 0}
    closing = {")": "(", "]": "[", "}": "{"}
    source = "".join(without_comments)
    for index, character in enumerate(source + ";"):
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            continue
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if character in {"'", '"'}:
            quote = character
            continue
        if character in depths:
            depths[character] += 1
            continue
        if character in closing:
            opening = closing[character]
            if depths[opening] == 0:
                return None
            depths[opening] -= 1
            continue
        if (
            character == ":"
            and colon_index is None
            and all(depth == 0 for depth in depths.values())
        ):
            colon_index = index
            continue
        if (
            character == ";"
            and all(depth == 0 for depth in depths.values())
        ):
            segment = source[declaration_start:index]
            if segment.strip():
                if colon_index is None:
                    return None
                property_name = source[
                    declaration_start:colon_index
                ].strip()
                property_value = source[
                    colon_index + 1:index
                ].strip()
                if not property_name or not property_value:
                    return None
                property_value, important = (
                    strip_top_level_css_important(property_value)
                )
                property_value = property_value.strip()
                if not property_value:
                    return None
                records.append(
                    {
                        "important": important,
                        "property": property_name,
                        "value": property_value,
                    }
                )
            declaration_start = index + 1
            colon_index = None
    if (
        quote
        or escaped
        or any(depth != 0 for depth in depths.values())
    ):
        return None
    return records


def css_declaration_records_hide(
    declarations: list[dict[str, Any]],
) -> bool:
    visible_display_tokens = {
        "block",
        "contents",
        "flex",
        "flow",
        "flow-root",
        "grid",
        "inline",
        "inline-block",
        "inline-flex",
        "inline-grid",
        "inline-table",
        "initial",
        "list-item",
        "ruby",
        "ruby-base",
        "ruby-base-container",
        "ruby-text",
        "ruby-text-container",
        "run-in",
        "table",
        "table-caption",
        "table-cell",
        "table-column",
        "table-column-group",
        "table-footer-group",
        "table-header-group",
        "table-row",
        "table-row-group",
        "inherit",
        "revert",
        "revert-layer",
        "unset",
    }
    parsed: dict[str, list[str]] = {}
    for declaration in declarations:
        property_name = declaration["property"].strip().lower()
        property_value = re.sub(
            r"\s+",
            " ",
            declaration["value"].lower(),
        ).strip()
        if "\\" in property_name:
            return True
        parsed.setdefault(property_name, []).append(property_value)
        if property_name == "display":
            display_tokens = property_value.split()
            if (
                not display_tokens
                or "none" in display_tokens
                or (
                    "var(" not in property_value
                    and "env(" not in property_value
                    and any(
                        token not in visible_display_tokens
                        for token in display_tokens
                    )
                )
            ):
                return True
        elif property_name == "visibility":
            if property_value in {"collapse", "hidden"}:
                return True
        elif property_name == "content-visibility":
            if property_value == "hidden":
                return True
        elif property_name == "opacity":
            opacity = re.fullmatch(
                r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)"
                r"(?:e[+-]?\d+)?)(%)?",
                property_value,
            )
            if opacity is not None and float(opacity.group(1)) <= 0:
                return True
        elif property_name == "clip":
            compact = re.sub(r"\s+", "", property_value)
            if compact in {
                "rect(0,0,0,0)",
                "rect(0px,0px,0px,0px)",
            }:
                return True
        elif property_name == "clip-path":
            compact = re.sub(r"\s+", "", property_value)
            if compact in {
                "circle(0)",
                "circle(0%)",
                "inset(50%)",
                "polygon(0 0,0 0,0 0,0 0)",
            }:
                return True
        elif property_name == "transform":
            compact = re.sub(r"\s+", "", property_value)
            if re.search(
                r"(?:^|\))scale(?:x|y)?\((?:[+-]?0+(?:\.0*)?"
                r"|[+-]?\.0+|[+-]?0+(?:\.0*)?%)\)",
                compact,
            ):
                return True
        elif property_name == "scale":
            scale_values = property_value.split()
            parsed_scale: list[float] = []
            for scale_value in scale_values:
                scale_match = re.fullmatch(
                    r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))(%)?",
                    scale_value,
                )
                if scale_match is None:
                    parsed_scale = []
                    break
                number = float(scale_match.group(1))
                if scale_match.group(2):
                    number /= 100
                parsed_scale.append(number)
            if parsed_scale and any(number == 0 for number in parsed_scale):
                return True
        elif property_name in {"filter", "-webkit-filter"}:
            for opacity in re.findall(
                r"opacity\(\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))"
                r"(%)?\s*\)",
                property_value,
            ):
                number = float(opacity[0])
                if number <= 0:
                    return True
        elif (
            property_name in {"color", "-webkit-text-fill-color"}
            and re.sub(r"\s+", "", property_value)
            in {"rgba(0,0,0,0)", "transparent"}
        ):
            return True
        elif (
            property_name in {"font-size", "line-height", "zoom"}
            and re.fullmatch(
                r"[+-]?(?:0+(?:\.0*)?|\.0+)(?:[a-z%]+)?",
                property_value,
            )
        ):
            return True
        elif property_name == "text-indent":
            indent = re.fullmatch(
                r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))"
                r"(px|em|rem|vw|vh|%)",
                property_value,
            )
            if indent is None or float(indent.group(1)) <= -100:
                return True
    def dimension_at_most(
        property_names: set[str],
        maximum: float,
    ) -> bool:
        for property_name in property_names:
            for value in parsed.get(property_name, []):
                dimension = re.fullmatch(
                    r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))"
                    r"(px|em|rem)?",
                    value,
                )
                if (
                    dimension is not None
                    and float(dimension.group(1)) <= maximum
                ):
                    return True
        return False

    position_values = {
        value
        for property_name in {"position"}
        for value in parsed.get(property_name, [])
    }
    overflow_values = {
        value
        for property_name in {
            "overflow",
            "overflow-x",
            "overflow-y",
        }
        for value in parsed.get(property_name, [])
    }
    if (
        position_values.intersection({"absolute", "fixed"})
        and overflow_values.intersection({"clip", "hidden"})
        and dimension_at_most({"height", "max-height"}, 1)
        and dimension_at_most({"width", "max-width"}, 1)
    ):
        return True
    if (
        overflow_values.intersection({"clip", "hidden"})
        and (
            dimension_at_most({"height", "max-height"}, 0)
            or dimension_at_most({"width", "max-width"}, 0)
        )
    ):
        return True
    if position_values.intersection({"absolute", "fixed"}):
        for property_name in {
            "bottom",
            "inset",
            "inset-block",
            "inset-block-end",
            "inset-block-start",
            "inset-inline",
            "inset-inline-end",
            "inset-inline-start",
            "left",
            "margin",
            "margin-block",
            "margin-block-end",
            "margin-block-start",
            "margin-inline",
            "margin-inline-end",
            "margin-inline-start",
            "right",
            "top",
        }:
            for value in parsed.get(property_name, []):
                offsets = re.findall(
                    r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))"
                    r"(px|em|rem|vw|vh|%)",
                    value,
                )
                if any(float(number) <= -100 for number, _ in offsets):
                    return True
    return False


def css_declarations_hide(declarations: str) -> bool:
    records = parse_inline_css_declarations(declarations)
    if records is None:
        return True
    return css_declaration_records_hide(records)


class VisibilityTree(HTMLParser):
    """Build the small DOM subset needed for scoped CSS visibility checks."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.nodes: list[dict[str, Any]] = []
        self._stack: list[int] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        tag = tag.lower()
        values = {
            name.lower(): value or ""
            for name, value in attrs
        }
        attribute_names = {
            name.lower()
            for name, _ in attrs
        }
        parent = self._stack[-1] if self._stack else None
        parent_hidden = (
            bool(self.nodes[parent]["hidden"])
            if parent is not None
            else False
        )
        hidden = parent_hidden or (
            tag in {"script", "style", "template", "noscript"}
            or tag == "dialog"
            and "open" not in attribute_names
            or tag == "details"
            and "open" not in attribute_names
            or "hidden" in attribute_names
            or "inert" in attribute_names
            or values.get("aria-hidden", "").strip().lower() == "true"
            or css_declarations_hide(values.get("style", ""))
        )
        node_index = len(self.nodes)
        self.nodes.append(
            {
                "attrs": values,
                "children": [],
                "classes": set(values.get("class", "").split()),
                "hidden": hidden,
                "parent": parent,
                "tag": tag,
            }
        )
        if parent is not None:
            self.nodes[parent]["children"].append(node_index)
        if tag not in CommercePageFacts.VOID_ELEMENTS:
            self._stack.append(node_index)

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in CommercePageFacts.VOID_ELEMENTS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self._stack) - 1, -1, -1):
            if self.nodes[self._stack[index]]["tag"] == tag:
                del self._stack[index:]
                break


def split_css_selector_list(selector_list: str) -> list[str] | None:
    selectors: list[str] = []
    start = 0
    bracket_depth = 0
    parenthesis_depth = 0
    quote = ""
    escaped = False
    for index, character in enumerate(selector_list):
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if quote:
            if character == quote:
                quote = ""
            continue
        if character in {"'", '"'} and bracket_depth:
            quote = character
        elif character == "[":
            bracket_depth += 1
        elif character == "]":
            bracket_depth -= 1
            if bracket_depth < 0:
                return None
        elif character == "(":
            parenthesis_depth += 1
        elif character == ")":
            parenthesis_depth -= 1
            if parenthesis_depth < 0:
                return None
        elif (
            character == ","
            and bracket_depth == 0
            and parenthesis_depth == 0
        ):
            selector = selector_list[start:index].strip()
            if not selector:
                return None
            selectors.append(selector)
            start = index + 1
    if escaped or quote or bracket_depth or parenthesis_depth:
        return None
    selector = selector_list[start:].strip()
    if not selector:
        return None
    selectors.append(selector)
    return selectors


def tokenize_css_selector(
    selector: str,
) -> tuple[list[str], list[str]] | None:
    if "\\" in selector:
        return None
    compounds: list[str] = []
    combinators: list[str] = []
    buffer: list[str] = []
    pending_combinator = ""
    bracket_depth = 0
    quote = ""

    def flush_buffer() -> None:
        nonlocal buffer
        compound = "".join(buffer).strip()
        if compound:
            compounds.append(compound)
        buffer = []

    for character in selector.strip():
        if quote:
            buffer.append(character)
            if character == quote:
                quote = ""
            continue
        if character in {"'", '"'} and bracket_depth:
            quote = character
            buffer.append(character)
            continue
        if character == "[":
            bracket_depth += 1
            buffer.append(character)
            continue
        if character == "]":
            bracket_depth -= 1
            if bracket_depth < 0:
                return None
            buffer.append(character)
            continue
        if bracket_depth:
            buffer.append(character)
            continue
        if character in {">", "+", "~"}:
            flush_buffer()
            if not compounds:
                return None
            pending_combinator = character
            continue
        if character.isspace():
            if buffer:
                flush_buffer()
                pending_combinator = " "
            continue
        if pending_combinator:
            if len(compounds) != len(combinators) + 1:
                return None
            combinators.append(pending_combinator)
            pending_combinator = ""
        buffer.append(character)
    flush_buffer()
    if (
        quote
        or bracket_depth
        or pending_combinator
        or not compounds
        or len(combinators) != len(compounds) - 1
    ):
        return None
    return compounds, combinators


def parse_css_attribute(
    source: str,
) -> tuple[str, str, str, str] | None:
    match = re.fullmatch(
        r"\s*([a-zA-Z_:][a-zA-Z0-9_:.-]*)"
        r"(?:\s*(~=|\|=|\^=|\$=|\*=|=)\s*"
        r"(?:\"([^\"]*)\"|'([^']*)'|([^\s]+))"
        r"(?:\s+([iIsS]))?)?\s*",
        source,
    )
    if match is None:
        return None
    operator = match.group(2) or ""
    value = next(
        (
            item
            for item in match.group(3, 4, 5)
            if item is not None
        ),
        "",
    )
    return (
        match.group(1).lower(),
        operator,
        value,
        (match.group(6) or "").lower(),
    )


def parse_css_compound(
    compound: str,
) -> dict[str, Any] | None:
    if not compound or ":" in compound or "\\" in compound:
        return None
    parsed: dict[str, Any] = {
        "attributes": [],
        "classes": [],
        "ids": [],
        "tag": "",
    }
    position = 0
    tag_match = re.match(r"(?:\*|[a-zA-Z][a-zA-Z0-9_-]*)", compound)
    if tag_match:
        parsed["tag"] = tag_match.group(0).lower()
        position = tag_match.end()
    while position < len(compound):
        marker = compound[position]
        if marker in {".", "#"}:
            identifier = re.match(
                r"[a-zA-Z0-9_-]+",
                compound[position + 1 :],
            )
            if identifier is None:
                return None
            value = identifier.group(0)
            key = "classes" if marker == "." else "ids"
            parsed[key].append(value)
            position += len(value) + 1
            continue
        if marker == "[":
            end = position + 1
            quote = ""
            while end < len(compound):
                character = compound[end]
                if quote:
                    if character == quote:
                        quote = ""
                elif character in {"'", '"'}:
                    quote = character
                elif character == "]":
                    break
                end += 1
            if end >= len(compound) or quote:
                return None
            attribute = parse_css_attribute(
                compound[position + 1 : end]
            )
            if attribute is None:
                return None
            parsed["attributes"].append(attribute)
            position = end + 1
            continue
        return None
    if (
        not parsed["tag"]
        and not parsed["classes"]
        and not parsed["ids"]
        and not parsed["attributes"]
    ):
        return None
    return parsed


def css_attribute_matches(
    actual: str,
    operator: str,
    expected: str,
    flag: str,
) -> bool:
    if flag == "i":
        actual = actual.lower()
        expected = expected.lower()
    if not operator:
        return True
    if operator == "=":
        return actual == expected
    if operator == "~=":
        return expected in actual.split()
    if operator == "|=":
        return actual == expected or actual.startswith(expected + "-")
    if operator == "^=":
        return actual.startswith(expected)
    if operator == "$=":
        return actual.endswith(expected)
    if operator == "*=":
        return expected in actual
    return False


def css_compound_matches(
    node: dict[str, Any],
    compound: dict[str, Any],
) -> bool:
    tag = compound["tag"]
    if tag and tag != "*" and node["tag"] != tag:
        return False
    if any(
        class_name not in node["classes"]
        for class_name in compound["classes"]
    ):
        return False
    node_id = node["attrs"].get("id", "")
    if any(selector_id != node_id for selector_id in compound["ids"]):
        return False
    for name, operator, expected, flag in compound["attributes"]:
        if name not in node["attrs"]:
            return False
        if not css_attribute_matches(
            node["attrs"][name],
            operator,
            expected,
            flag,
        ):
            return False
    return True


def previous_siblings(
    tree: VisibilityTree,
    node_index: int,
) -> list[int]:
    parent = tree.nodes[node_index]["parent"]
    if parent is None:
        return []
    siblings = tree.nodes[parent]["children"]
    position = siblings.index(node_index)
    return siblings[:position]


def css_selector_matches_node(
    tree: VisibilityTree,
    node_index: int,
    compounds: list[dict[str, Any]],
    combinators: list[str],
    compound_index: int | None = None,
) -> bool:
    if compound_index is None:
        compound_index = len(compounds) - 1
    if not css_compound_matches(
        tree.nodes[node_index],
        compounds[compound_index],
    ):
        return False
    if compound_index == 0:
        return True
    combinator = combinators[compound_index - 1]
    if combinator == ">":
        parent = tree.nodes[node_index]["parent"]
        return (
            parent is not None
            and css_selector_matches_node(
                tree,
                parent,
                compounds,
                combinators,
                compound_index - 1,
            )
        )
    if combinator == " ":
        parent = tree.nodes[node_index]["parent"]
        while parent is not None:
            if css_selector_matches_node(
                tree,
                parent,
                compounds,
                combinators,
                compound_index - 1,
            ):
                return True
            parent = tree.nodes[parent]["parent"]
        return False
    siblings = previous_siblings(tree, node_index)
    if combinator == "+":
        siblings = siblings[-1:]
    return any(
        css_selector_matches_node(
            tree,
            sibling,
            compounds,
            combinators,
            compound_index - 1,
        )
        for sibling in reversed(siblings)
    )


@functools.lru_cache(maxsize=1)
def require_css_tree_dependency() -> None:
    package = json.loads(
        (REPOSITORY_ROOT / "package.json").read_text(encoding="utf-8")
    )
    lock = json.loads(
        (REPOSITORY_ROOT / "package-lock.json").read_text(
            encoding="utf-8"
        )
    )
    root_dependencies = package.get("devDependencies")
    lock_packages = lock.get("packages")
    css_tree_lock = (
        lock_packages.get("node_modules/css-tree")
        if isinstance(lock_packages, dict)
        else None
    )
    installed_package_path = (
        REPOSITORY_ROOT
        / "node_modules"
        / "css-tree"
        / "package.json"
    )
    installed_entry_path = (
        REPOSITORY_ROOT
        / "node_modules"
        / "css-tree"
        / "lib"
        / "index.js"
    )
    try:
        installed_package = json.loads(
            installed_package_path.read_text(encoding="utf-8")
        )
        installed_entry_path.resolve(strict=True).relative_to(
            (REPOSITORY_ROOT / "node_modules" / "css-tree").resolve(
                strict=True
            )
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise ops.DeployFailure(
            "The reviewed local CSS parser is unavailable."
        ) from error
    if (
        not isinstance(root_dependencies, dict)
        or root_dependencies.get("css-tree") != "3.2.1"
        or not isinstance(css_tree_lock, dict)
        or css_tree_lock.get("version") != "3.2.1"
        or css_tree_lock.get("integrity")
        != (
            "sha512-X7sjQzceUhu1u7Y/ylrRZFU2FS6LRiFVp6rKLPg23y"
            "3x3c3DOKAwuXGDp+PAGjh6CSnCjYeAul8pcT8bAl+lSA=="
        )
        or not isinstance(installed_package, dict)
        or installed_package.get("version") != "3.2.1"
    ):
        raise ops.DeployFailure(
            "The pinned CSS parser dependency is not exact."
        )


def css_tokens_are_balanced(styles: str) -> bool:
    stack: list[str] = []
    closing = {")": "(", "]": "[", "}": "{"}
    quote = ""
    index = 0
    while index < len(styles):
        character = styles[index]
        if quote:
            if character == "\\" and index + 1 < len(styles):
                index += 2
                continue
            if character == quote:
                quote = ""
            index += 1
            continue
        if character in {"'", '"'}:
            quote = character
            index += 1
            continue
        if styles.startswith("/*", index):
            comment_end = styles.find("*/", index + 2)
            if comment_end < 0:
                return False
            index = comment_end + 2
            continue
        if character == "\\":
            if index + 1 >= len(styles):
                return False
            index += 2
            continue
        if character in {"(", "[", "{"}:
            stack.append(character)
        elif character in closing:
            if not stack or stack[-1] != closing[character]:
                return False
            stack.pop()
        index += 1
    return not quote and not stack


@functools.lru_cache(maxsize=128)
def parse_css_stylesheet(styles: str) -> dict[str, Any]:
    if len(styles.encode("utf-8")) > MAX_STYLESHEET_BYTES:
        raise ops.DeployFailure(
            "A reviewed stylesheet exceeded the safe byte bound."
        )
    if not css_tokens_are_balanced(styles):
        raise ops.DeployFailure(
            "A reviewed stylesheet contained unbalanced CSS tokens."
        )
    require_css_tree_dependency()
    css_tree_module_url = (
        REPOSITORY_ROOT
        / "node_modules"
        / "css-tree"
        / "lib"
        / "index.js"
    ).resolve(strict=True).as_uri()
    parser_source = CSS_TREE_PARSER.replace(
        "__CSS_TREE_MODULE_URL__",
        json.dumps(css_tree_module_url),
    )
    try:
        process = subprocess.run(
            [
                "node",
                "--input-type=module",
                "--eval",
                parser_source,
            ],
            input=styles,
            text=True,
            encoding="utf-8",
            errors="strict",
            capture_output=True,
            cwd=REPOSITORY_ROOT,
            timeout=30,
            check=False,
        )
    except (
        OSError,
        subprocess.SubprocessError,
        UnicodeError,
    ) as error:
        raise ops.DeployFailure(
            "The pinned CSS parser could not run."
        ) from error
    if process.returncode != 0:
        raise ops.DeployFailure(
            "A reviewed stylesheet did not parse as valid CSS."
        )
    try:
        result = json.loads(process.stdout)
    except (json.JSONDecodeError, TypeError) as error:
        raise ops.DeployFailure(
            "The pinned CSS parser returned an invalid result."
        ) from error
    if (
        not isinstance(result, dict)
        or set(result)
        != {
            "ambiguous",
            "imports",
            "rules",
            "usable_declarations",
        }
        or not isinstance(result["ambiguous"], bool)
        or not isinstance(result["imports"], list)
        or not isinstance(result["rules"], list)
        or not isinstance(result["usable_declarations"], int)
        or isinstance(result["usable_declarations"], bool)
        or result["usable_declarations"] < 0
    ):
        raise ops.DeployFailure(
            "The pinned CSS parser result exceeded its schema."
        )
    if result["ambiguous"]:
        raise ops.DeployFailure(
            "A reviewed stylesheet contained ambiguous CSS."
        )
    return result


def css_import_href(prelude: str) -> str:
    match = re.match(
        r"^\s*(?:"
        r"url\(\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s)]+))\s*\)"
        r"|\"([^\"]+)\"|'([^']+)'"
        r")",
        prelude,
        flags=re.IGNORECASE,
    )
    if match is None:
        raise ops.DeployFailure(
            "A stylesheet import URL could not be reviewed."
        )
    href = next(
        value
        for value in match.groups()
        if value is not None
    )
    if (
        not href
        or "\\" in href
        or any(ord(character) < 32 for character in href)
    ):
        raise ops.DeployFailure(
            "A stylesheet import URL was unsafe."
        )
    return href


def canonical_stylesheet_url(base_url: str, href: str) -> str:
    if (
        not href
        or len(href) > 2_048
        or any(ord(character) < 32 for character in href)
    ):
        raise ops.DeployFailure("A stylesheet URL was unsafe.")
    url = urllib.parse.urljoin(base_url, href)
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != "robbottx.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or len(url) > 2_048
    ):
        raise ops.DeployFailure(
            "Every reviewed stylesheet must be same-origin HTTPS."
        )
    return url


def linked_stylesheet_urls(
    tree: VisibilityTree,
    document_url: str,
) -> list[str]:
    base_url = document_url
    base_nodes = [
        node
        for node in tree.nodes
        if node["tag"] == "base" and node["attrs"].get("href")
    ]
    if len(base_nodes) > 1:
        raise ops.DeployFailure(
            "The rendered page declared multiple stylesheet bases."
        )
    if base_nodes:
        base_url = canonical_stylesheet_url(
            document_url,
            base_nodes[0]["attrs"]["href"],
        )
    urls: list[str] = []
    for node in tree.nodes:
        if node["tag"] != "link":
            continue
        rel_tokens = {
            token.lower()
            for token in node["attrs"].get("rel", "").split()
        }
        if "stylesheet" not in rel_tokens:
            continue
        if (
            "alternate" in rel_tokens
            or "disabled" in node["attrs"]
        ):
            raise ops.DeployFailure(
                "An alternate or disabled stylesheet is ambiguous."
            )
        urls.append(
            canonical_stylesheet_url(
                base_url,
                node["attrs"].get("href", ""),
            )
        )
    unique_urls = list(dict.fromkeys(urls))
    if len(unique_urls) > MAX_STYLESHEET_COUNT:
        raise ops.DeployFailure(
            "The rendered page exceeded the stylesheet count bound."
        )
    return unique_urls


def stylesheet_media_type(content_type: str) -> tuple[str, str]:
    media_type = content_type.split(";", 1)[0].strip().lower()
    charset = ""
    for parameter in content_type.split(";")[1:]:
        name, separator, value = parameter.partition("=")
        if separator and name.strip().lower() == "charset":
            charset = value.strip().strip('"').lower()
    return media_type, charset


def fetch_stylesheet_graph(
    document_url: str,
    tree: VisibilityTree,
    inline_styles: str,
) -> list[dict[str, Any]]:
    pending: list[tuple[str, str | None, int, tuple[str, ...]]] = []
    if inline_styles.strip():
        pending.append((document_url, inline_styles, 0, (document_url,)))
    pending.extend(
        (url, None, 0, (url,))
        for url in linked_stylesheet_urls(tree, document_url)
    )
    reviewed: set[str] = set()
    results: list[dict[str, Any]] = []
    total_bytes = 0
    while pending:
        source_url, supplied_styles, depth, ancestry = pending.pop(0)
        external = supplied_styles is None
        if external and source_url in reviewed:
            continue
        if external:
            reviewed.add(source_url)
            if len(reviewed) > MAX_STYLESHEET_COUNT:
                raise ops.DeployFailure(
                    "The stylesheet graph exceeded its count bound."
                )
            status, content_type, styles = ops.request(
                source_url,
                timeout=90,
                accept="text/css",
            )
            media_type, charset = stylesheet_media_type(content_type)
            if (
                status != 200
                or media_type != "text/css"
                or charset not in {"", "utf-8"}
                or "\ufffd" in styles
            ):
                raise ops.DeployFailure(
                    "A linked stylesheet response was not exact."
                )
        else:
            styles = supplied_styles
        style_bytes = len(styles.encode("utf-8"))
        if style_bytes > MAX_STYLESHEET_BYTES:
            raise ops.DeployFailure(
                "A reviewed stylesheet exceeded its byte bound."
            )
        total_bytes += style_bytes
        if total_bytes > MAX_TOTAL_STYLESHEET_BYTES:
            raise ops.DeployFailure(
                "The stylesheet graph exceeded its total byte bound."
            )
        parsed = parse_css_stylesheet(styles)
        if (
            external
            and parsed["usable_declarations"] == 0
            and not parsed["imports"]
        ):
            raise ops.DeployFailure(
                "A linked stylesheet contained no usable CSS."
            )
        results.append(parsed)
        for prelude in parsed["imports"]:
            if not isinstance(prelude, str):
                raise ops.DeployFailure(
                    "A stylesheet import record was invalid."
                )
            import_url = canonical_stylesheet_url(
                source_url,
                css_import_href(prelude),
            )
            if import_url in ancestry:
                raise ops.DeployFailure(
                    "A stylesheet import cycle was detected."
                )
            if depth >= 5:
                raise ops.DeployFailure(
                    "The stylesheet import graph exceeded its depth bound."
                )
            if import_url not in reviewed:
                pending.append(
                    (
                        import_url,
                        None,
                        depth + 1,
                        ancestry + (import_url,),
                    )
                )
    return results


def reviewed_proof_scope(
    tree: VisibilityTree,
    *,
    product_catalog: bool,
    product_page: bool,
) -> set[int]:
    structural_tags = {"body", "h1", "html", "main"}
    if product_page:
        proof_classes = {
            "cart",
            "product",
            "product_title",
            "rbtx-offer-evidence",
            "single_add_to_cart_button",
            "stock",
            "summary",
            "type-product",
        }
        descendant_root_classes = {
            "cart",
            "product_title",
            "rbtx-offer-evidence",
            "single_add_to_cart_button",
            "stock",
        }
    elif product_catalog:
        proof_classes = {
            "product",
            "products",
            "wc-block-components-product-name",
            "wc-block-grid__product",
            "wc-block-grid__product-link",
            "wc-block-grid__products",
            "wc-block-product",
            "wc-block-product-template",
            "woocommerce-LoopProduct-link",
            "woocommerce-loop-product__link",
        }
        descendant_root_classes = {
            "wc-block-components-product-name",
            "wc-block-grid__product-link",
            "woocommerce-LoopProduct-link",
            "woocommerce-loop-product__link",
        }
    else:
        proof_classes = {"woocommerce-info"}
        descendant_root_classes = {"woocommerce-info"}
    direct_proof = {
        index
        for index, node in enumerate(tree.nodes)
        if (
            not node["hidden"]
            and (
                node["tag"] in structural_tags
                or not node["classes"].isdisjoint(proof_classes)
            )
        )
    }
    proof_scope = set(direct_proof)
    descendant_roots = {
        index
        for index, node in enumerate(tree.nodes)
        if (
            not node["hidden"]
            and (
                node["tag"] == "h1"
                or not node["classes"].isdisjoint(
                    descendant_root_classes
                )
            )
        )
    }
    pending_descendants = list(descendant_roots)
    while pending_descendants:
        node_index = pending_descendants.pop()
        for child in tree.nodes[node_index]["children"]:
            if child not in proof_scope:
                proof_scope.add(child)
                pending_descendants.append(child)
    for node_index in direct_proof:
        parent = tree.nodes[node_index]["parent"]
        while parent is not None:
            proof_scope.add(parent)
            parent = tree.nodes[parent]["parent"]
    return proof_scope


def stylesheet_hides_reviewed_proof(
    document_url: str,
    html: str,
    styles: str,
    *,
    product_catalog: bool,
    product_page: bool,
) -> bool:
    tree = VisibilityTree()
    try:
        tree.feed(html)
        tree.close()
    except Exception:
        return True
    proof_scope = reviewed_proof_scope(
        tree,
        product_catalog=product_catalog,
        product_page=product_page,
    )
    stylesheet_records = fetch_stylesheet_graph(
        document_url,
        tree,
        styles,
    )
    for stylesheet in stylesheet_records:
        rules = stylesheet.get("rules")
        if not isinstance(rules, list):
            raise ops.DeployFailure(
                "The CSS parser returned invalid rule records."
            )
        for rule in rules:
            if (
                not isinstance(rule, dict)
                or set(rule) != {"declarations", "selectors"}
                or not isinstance(rule["selectors"], str)
                or not isinstance(rule["declarations"], list)
            ):
                raise ops.DeployFailure(
                    "The CSS parser returned an invalid rule."
                )
            for declaration in rule["declarations"]:
                if (
                    not isinstance(declaration, dict)
                    or set(declaration)
                    != {"important", "property", "value"}
                    or not isinstance(declaration["important"], bool)
                    or not isinstance(declaration["property"], str)
                    or not isinstance(declaration["value"], str)
                ):
                    raise ops.DeployFailure(
                        "The CSS parser returned an invalid declaration."
                    )
            if not css_declaration_records_hide(
                rule["declarations"]
            ):
                continue
            selectors = split_css_selector_list(rule["selectors"])
            if selectors is None:
                continue
            for selector in selectors:
                tokenized = tokenize_css_selector(selector)
                if tokenized is None:
                    continue
                raw_compounds, combinators = tokenized
                compounds = [
                    parse_css_compound(compound)
                    for compound in raw_compounds
                ]
                if any(compound is None for compound in compounds):
                    continue
                parsed_compounds = [
                    compound
                    for compound in compounds
                    if compound is not None
                ]
                selected_nodes = [
                    node_index
                    for node_index, node in enumerate(tree.nodes)
                    if (
                        not node["hidden"]
                        and css_selector_matches_node(
                            tree,
                            node_index,
                            parsed_compounds,
                            combinators,
                        )
                    )
                ]
                if not selected_nodes:
                    if (
                        selector.strip()
                        == "#end-resizable-editor-section"
                    ):
                        return True
                    continue
                if any(
                    node_index in proof_scope
                    for node_index in selected_nodes
                ):
                    return True
    return False


class ProductPageFacts(HTMLParser):
    """Collect one rendered, purchasable WooCommerce product scope."""

    def __init__(self, product_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.product_url = product_url
        self.body_classes: set[str] = set()
        self.body_count = 0
        self.head_count = 0
        self.h1_count = 0
        self.h1_parts: list[str] = []
        self.html_count = 0
        self.html_language = ""
        self.invalid_markup = False
        self.main_count = 0
        self.product_title_count = 0
        self.product_structure_count = 0
        self.product_wrapper_count = 0
        self.style_parts: list[str] = []
        self.title_count = 0
        self.title_inside_head_count = 0
        self.title_parts: list[str] = []
        self.verified_product_ids: list[int] = []
        self.visible_text_parts: list[str] = []
        self._hidden_depth = 0
        self._in_body = False
        self._in_head = False
        self._in_title = False
        self._disabled_fieldset_indices: set[int] = set()
        self._product_contexts: list[dict[str, Any]] = []
        self._seen_element_ids: set[str] = set()
        self._stack: list[
            tuple[
                str,
                set[str],
                bool,
                bool,
                bool,
                bool,
                bool,
                bool,
            ]
        ] = []
        self._style_depth = 0

    @staticmethod
    def normalize(parts: list[str]) -> str:
        return " ".join(" ".join(parts).split())

    @staticmethod
    def positive_identifier(value: str) -> int | None:
        if not re.fullmatch(r"[1-9][0-9]{0,18}", value.strip()):
            return None
        return int(value)

    @staticmethod
    def meaningful_text(parts: list[str]) -> bool:
        text = ProductPageFacts.normalize(parts)
        lowered = text.lower()
        return (
            len(text) >= 2
            and any(character.isalnum() for character in text)
            and lowered
            not in {
                "n/a",
                "none",
                "placeholder",
                "product",
                "untitled",
            }
        )

    def form_action_is_canonical(self, action: str) -> bool:
        if not action:
            return False
        resolved = urllib.parse.urljoin(self.product_url, action)
        parsed = urllib.parse.urlsplit(resolved)
        expected = urllib.parse.urlsplit(self.product_url)
        return (
            parsed.scheme == "https"
            and parsed.netloc.lower() == "robbottx.com"
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and parsed.path.rstrip("/") == expected.path.rstrip("/")
        )

    def context_is_complete(self, context: dict[str, Any]) -> bool:
        form = context.get("form")
        if not isinstance(form, dict):
            return False
        surface_ids = context["surface_ids"]
        form_ids = form["identifiers"]
        submit_labels = form["submit_labels"]
        return (
            context["summary_count"] == 1
            and context["title_count"] == 1
            and self.meaningful_text(context["title_parts"])
            and context["stock_count"] == 1
            and self.meaningful_text(context["stock_parts"])
            and context["form_count"] == 1
            and form["closed"] is True
            and form["method"] == "post"
            and self.form_action_is_canonical(form["action"])
            and form["submit_count"] == 1
            and form["invalid_control_ownership"] is False
            and form["invalid_identifier"] is False
            and self.meaningful_text(submit_labels)
            and any(
                phrase in self.normalize(submit_labels).lower()
                for phrase in {"add to cart", "buy", "order"}
            )
            and len(surface_ids) == 1
            and form_ids == surface_ids
        )

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        tag = tag.lower()
        attribute_names = [name.lower() for name, _ in attrs]
        if len(attribute_names) != len(set(attribute_names)):
            self.invalid_markup = True
        values: dict[str, str] = {}
        for name, value in attrs:
            values.setdefault(name.lower(), value or "")
        attribute_name_set = set(attribute_names)
        classes = set(values.get("class", "").split())
        element_id = values.get("id", "").strip()
        if element_id:
            if element_id in self._seen_element_ids:
                self.invalid_markup = True
            self._seen_element_ids.add(element_id)
        if tag == "form" and any(
            stack_tag == "form"
            for stack_tag, _, _, _, _, _, _, _ in self._stack
        ):
            self.invalid_markup = True
        if tag == "html":
            self.html_count += 1
            self.html_language = values.get("lang", "")
        if tag == "head":
            self.head_count += 1
            self._in_head = True
        if tag == "title":
            self.title_count += 1
            self.title_inside_head_count += int(self._in_head)
            self._in_title = True
        if tag == "style":
            self._style_depth += 1
        if tag == "body":
            self.body_count += 1
            self._in_head = False
            self._in_body = True
        hides_content = self._in_body and (
            tag in {"script", "style", "noscript", "template"}
            or tag == "dialog"
            and "open" not in attribute_name_set
            or tag == "details"
            and "open" not in attribute_name_set
            or "hidden" in attribute_name_set
            or "inert" in attribute_name_set
            or values.get("aria-hidden", "").strip().lower() == "true"
            or css_declarations_hide(values.get("style", ""))
        )
        visible = (
            self._in_body
            and self._hidden_depth == 0
            and not hides_content
        )
        visible_main = visible and tag == "main"
        visible_h1 = visible and tag == "h1"
        title_scope = False
        stock_scope = False
        submit_scope = False
        inside_disabled_fieldset = bool(
            self._disabled_fieldset_indices
        )
        if visible:
            if tag == "body":
                self.body_classes.update(classes)
            if visible_main:
                self.main_count += 1
            if visible_h1:
                self.h1_count += 1
                if "product_title" in classes:
                    self.product_title_count += 1
            inside_main = visible_main or any(
                stack_main
                for _, _, _, stack_main, _, _, _, _ in self._stack
            )
            is_product_wrapper = {
                "product",
                "type-product",
            }.issubset(classes)
            if is_product_wrapper:
                self.product_wrapper_count += 1
                if inside_main:
                    surface_ids: set[int] = set()
                    wrapper_id = re.fullmatch(
                        r"product-([1-9][0-9]{0,18})",
                        values.get("id", ""),
                    )
                    if wrapper_id:
                        surface_ids.add(int(wrapper_id.group(1)))
                    for class_name in classes:
                        post_class = re.fullmatch(
                            r"post-([1-9][0-9]{0,18})",
                            class_name,
                        )
                        if post_class:
                            surface_ids.add(int(post_class.group(1)))
                    for name in ("data-product-id", "data-product_id"):
                        identifier = self.positive_identifier(
                            values.get(name, "")
                        )
                        if identifier is not None:
                            surface_ids.add(identifier)
                    self._product_contexts.append(
                        {
                            "form": None,
                            "form_count": 0,
                            "root_index": len(self._stack),
                            "stock_count": 0,
                            "stock_parts": [],
                            "summary_count": 0,
                            "surface_ids": surface_ids,
                            "title_count": 0,
                            "title_parts": [],
                        }
                    )
            context = (
                self._product_contexts[-1]
                if self._product_contexts
                else None
            )
            active_root_index = (
                context["root_index"]
                if context is not None
                else -1
            )
            inside_summary = any(
                stack_index > active_root_index
                and "summary" in stack_classes
                for stack_index, (
                    _,
                    stack_classes,
                    _,
                    _,
                    _,
                    _,
                    _,
                    _,
                ) in enumerate(self._stack)
            )
            if context is not None and "summary" in classes:
                context["summary_count"] += 1
            summary_scope = inside_summary or "summary" in classes
            title_scope = bool(
                context is not None
                and visible_h1
                and "product_title" in classes
                and summary_scope
            )
            if title_scope:
                context["title_count"] += 1
            stock_scope = bool(
                context is not None
                and "stock" in classes
                and summary_scope
            )
            if stock_scope:
                context["stock_count"] += 1
            if (
                context is not None
                and tag == "form"
                and "cart" in classes
                and summary_scope
            ):
                context["form_count"] += 1
                context["form"] = {
                    "action": values.get("action", "").strip(),
                    "closed": False,
                    "identifiers": set(),
                    "invalid_control_ownership": False,
                    "invalid_identifier": False,
                    "method": values.get("method", "").strip().lower(),
                    "root_index": len(self._stack),
                    "submit_count": 0,
                    "submit_labels": [],
                }
            form = (
                context.get("form")
                if context is not None
                else None
            )
            inside_form = bool(
                isinstance(form, dict)
                and form["closed"] is False
                and (
                    len(self._stack) > form["root_index"]
                    or (
                        tag == "form"
                        and "cart" in classes
                    )
                )
            )
            if inside_form and isinstance(form, dict):
                identifier_name = values.get("name", "")
                is_identifier = identifier_name in {
                    "add-to-cart",
                    "product_id",
                }
                is_identifier_control = tag in {"button", "input"}
                reassigned_control = "form" in attribute_name_set
                control_disabled = (
                    "disabled" in attribute_name_set
                    or inside_disabled_fieldset
                )
                if is_identifier:
                    if (
                        not is_identifier_control
                        or reassigned_control
                        or control_disabled
                    ):
                        form["invalid_identifier"] = True
                    identifier = self.positive_identifier(
                        values.get("value", "")
                    )
                    if (
                        identifier is None
                        or not is_identifier_control
                        or reassigned_control
                        or control_disabled
                    ):
                        form["invalid_identifier"] = True
                    else:
                        form["identifiers"].add(identifier)
                is_submit = (
                    tag == "button"
                    and values.get("type", "submit").lower() == "submit"
                    or tag == "input"
                    and values.get("type", "").lower() == "submit"
                )
                enabled_submit = (
                    is_submit
                    and "single_add_to_cart_button" in classes
                    and not control_disabled
                    and values.get("aria-disabled", "").lower() != "true"
                    and not reassigned_control
                    and values.get("formmethod", "post").lower() == "post"
                    and (
                        not values.get("formaction", "")
                        or self.form_action_is_canonical(
                            values["formaction"]
                        )
                    )
                )
                if is_submit and reassigned_control:
                    form["invalid_control_ownership"] = True
                if enabled_submit:
                    form["submit_count"] += 1
                    submit_scope = tag == "button"
                    for name in ("aria-label", "title", "value"):
                        if values.get(name):
                            form["submit_labels"].append(values[name])
            for name in ("alt", "aria-label", "title", "placeholder"):
                if values.get(name):
                    self.visible_text_parts.append(values[name])
        if hides_content:
            self._hidden_depth += 1
        if (
            tag == "fieldset"
            and "disabled" in attribute_name_set
        ):
            self._disabled_fieldset_indices.add(len(self._stack))
        if tag not in CommercePageFacts.VOID_ELEMENTS:
            self._stack.append(
                (
                    tag,
                    classes,
                    hides_content,
                    visible_main,
                    visible_h1,
                    title_scope,
                    stock_scope,
                    submit_scope,
                )
            )
        elif hides_content:
            self._hidden_depth = max(0, self._hidden_depth - 1)

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in CommercePageFacts.VOID_ELEMENTS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        if tag == "style" and self._style_depth:
            self._style_depth -= 1
        if tag == "head":
            self._in_head = False
        if tag == "body":
            self._in_body = False
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] != tag:
                continue
            removed = self._stack[index:]
            self._disabled_fieldset_indices = {
                fieldset_index
                for fieldset_index in self._disabled_fieldset_indices
                if fieldset_index < index
            }
            self._hidden_depth = max(
                0,
                self._hidden_depth
                - sum(
                    1
                    for _, _, hides, _, _, _, _, _ in removed
                    if hides
                ),
            )
            for context in self._product_contexts:
                form = context.get("form")
                if (
                    isinstance(form, dict)
                    and tag == "form"
                    and form["root_index"] == index
                    and form["closed"] is False
                ):
                    form["closed"] = True
            remaining_contexts: list[dict[str, Any]] = []
            for context in self._product_contexts:
                if context["root_index"] >= index:
                    if self.context_is_complete(context):
                        self.product_structure_count += 1
                        self.verified_product_ids.append(
                            next(iter(context["surface_ids"]))
                        )
                else:
                    remaining_contexts.append(context)
            self._product_contexts = remaining_contexts
            del self._stack[index:]
            break

    def handle_data(self, data: str) -> None:
        if self._style_depth:
            self.style_parts.append(data)
        if self._in_title:
            self.title_parts.append(data)
        if not self._in_body or self._hidden_depth:
            return
        stripped = data.strip()
        if not stripped:
            return
        self.visible_text_parts.append(stripped)
        if any(
            visible_h1
            for _, _, _, _, visible_h1, _, _, _ in self._stack
        ):
            self.h1_parts.append(stripped)
        context = (
            self._product_contexts[-1]
            if self._product_contexts
            else None
        )
        if context is None:
            return
        if any(
            title_scope
            for _, _, _, _, _, title_scope, _, _ in self._stack
        ):
            context["title_parts"].append(stripped)
        if any(
            stock_scope
            for _, _, _, _, _, _, stock_scope, _ in self._stack
        ):
            context["stock_parts"].append(stripped)
        form = context.get("form")
        if (
            isinstance(form, dict)
            and any(
                submit_scope
                for _, _, _, _, _, _, _, submit_scope in self._stack
            )
        ):
            form["submit_labels"].append(stripped)

    @property
    def h1(self) -> str:
        return self.normalize(self.h1_parts)

    @property
    def title(self) -> str:
        return self.normalize(self.title_parts)

    @property
    def visible_text(self) -> str:
        return self.normalize(self.visible_text_parts)


def require_snippet_capacity(
    base_url: str,
    auth: str,
) -> int:
    status, content_type, body = ops.request(
        (
            f"{base_url}/wp-json/code-snippets/v1/snippets"
            "?per_page=100&page=1"
        ),
        auth=auth,
        timeout=60,
    )
    if status < 200 or status >= 300:
        raise ops.DeployFailure(
            "Code Snippets capacity verification failed."
        )
    snippets = ops.decode_json(
        content_type,
        body,
        "Code Snippets capacity verification",
    )
    if not isinstance(snippets, list):
        raise ops.DeployFailure(
            "Code Snippets capacity verification returned an "
            "unexpected JSON shape."
        )
    snippet_count = len(snippets)
    if snippet_count > MAX_CODE_SNIPPETS_RECORDS:
        raise ops.DeployFailure(
            "Code Snippets has insufficient safe temporary capacity."
        )
    return snippet_count


def prepare_output_path(value: Path | str) -> Path:
    output_path = Path(value).expanduser().resolve()
    if output_path.exists() or output_path.is_symlink():
        raise ops.DeployFailure(
            "--output already exists; refusing to overwrite it."
        )
    if not output_path.parent.is_dir():
        raise ops.DeployFailure(
            "--output parent directory does not exist."
        )
    return output_path


def require_allowlisted_evidence(
    payload: dict,
    schema: dict = COMMERCE_EVIDENCE_SCHEMA,
    *,
    context: str = "evidence",
) -> None:
    if not isinstance(payload, dict):
        raise ops.DeployFailure(
            "Commerce evidence has an invalid shape."
        )
    if set(payload).difference(schema):
        raise ops.DeployFailure(
            f"Commerce {context} contains a non-allowlisted field."
        )
    for key, value in payload.items():
        child_schema = schema[key]
        if isinstance(child_schema, dict):
            if not isinstance(value, dict):
                raise ops.DeployFailure(
                    f"Commerce {context} has an invalid nested shape."
                )
            require_allowlisted_evidence(
                value,
                child_schema,
                context=f"{context}.{key}",
            )
        elif isinstance(value, (dict, list, set, tuple)):
            raise ops.DeployFailure(
                f"Commerce {context} has an invalid field value."
            )


def write_new_evidence(output_path: Path, payload: dict) -> None:
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    temporary_path = output_path.with_name(
        f".{output_path.name}.tmp-{os.getpid()}-{secrets.token_hex(8)}"
    )
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary_path, output_path)
        except FileExistsError as error:
            raise ops.DeployFailure(
                "--output was created concurrently; refusing to overwrite it."
            ) from error
    except ops.DeployFailure:
        raise
    except OSError as error:
        raise ops.DeployFailure(
            "Durable commerce evidence could not be written."
        ) from error
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify and optionally apply the reviewed commerce visibility "
            "and English page titles."
        )
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--boundary-receipt",
        required=True,
        type=Path,
        help="Fresh public-boundary release receipt for the plugin artifact.",
    )
    parser.add_argument(
        "--plugin-version",
        required=True,
        help="Exact three-part robbottx-core release version.",
    )
    parser.add_argument(
        "--plugin-zip-sha256",
        required=True,
        help="Exact SHA-256 of plugin-dist/robbottx-core-<version>.zip.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="New durable JSON evidence path. Existing paths are refused.",
    )
    return parser.parse_args()


def validate_commerce_release_inputs(args: argparse.Namespace) -> None:
    if (
        re.fullmatch(
            r"\d+\.\d+\.\d+",
            str(getattr(args, "plugin_version", "")),
        )
        is None
    ):
        raise ops.DeployFailure(
            "--plugin-version must be a three-part numeric release."
        )
    if (
        re.fullmatch(
            r"[0-9a-fA-F]{64}",
            str(getattr(args, "plugin_zip_sha256", "")),
        )
        is None
    ):
        raise ops.DeployFailure(
            "--plugin-zip-sha256 must be a 64-character hexadecimal value."
        )
    receipt = getattr(args, "boundary_receipt", None)
    if not isinstance(receipt, Path):
        raise ops.DeployFailure("--boundary-receipt is required.")


def verify_commerce_release_boundary(args: argparse.Namespace) -> str:
    """Freeze reviewed route bytes and prove the current release boundary."""

    validate_commerce_release_inputs(args)
    try:
        template_payload, template_head = read_clean_index_file(
            REPOSITORY_ROOT,
            ROUTE_TEMPLATE_RELATIVE_PATH,
            max_bytes=MAX_ROUTE_TEMPLATE_BYTES,
        )
        verifier, verifier_head = load_clean_index_module(
            REPOSITORY_ROOT,
            BOUNDARY_VERIFIER_RELATIVE_PATH,
            BOUNDARY_VERIFIER_MODULE_NAME,
            max_bytes=MAX_BOUNDARY_VERIFIER_BYTES,
        )
    except Exception as error:
        raise ops.DeployFailure(
            "Reviewed commerce release code could not be loaded."
        ) from error

    if (
        template_head != OPS_GIT_HEAD
        or verifier_head != OPS_GIT_HEAD
    ):
        raise ops.DeployFailure(
            "Reviewed commerce release code does not share one Git HEAD."
        )
    try:
        route_template = template_payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ops.DeployFailure(
            "Commerce route template is not valid UTF-8."
        ) from error
    if (
        hashlib.sha256(template_payload).hexdigest()
        != ROUTE_TEMPLATE_SHA256
    ):
        raise ops.DeployFailure(
            "Commerce route template does not match the reviewed release."
        )

    try:
        scanner = getattr(verifier, "run_reviewed_boundary_scan")
        validator = getattr(verifier, "validate_boundary_receipt")
        if not callable(scanner) or not callable(validator):
            raise AttributeError("boundary verifier entry point unavailable")
        scan_report = scanner(REPOSITORY_ROOT)
        scan_head = getattr(scan_report, "git_head", None)
        public_snapshot_sha256 = getattr(
            scan_report,
            "public_snapshot_payload_sha256",
            None,
        )
        if (
            scan_head != template_head
            or not isinstance(public_snapshot_sha256, str)
            or re.fullmatch(
                r"[0-9a-f]{64}",
                public_snapshot_sha256,
            )
            is None
        ):
            raise ops.DeployFailure(
                "Current public-boundary scan did not retain the frozen release."
            )
        result = validator(
            args.boundary_receipt,
            version=args.plugin_version,
            slug="robbottx-core",
            zip_sha256=args.plugin_zip_sha256,
            record_hash=public_snapshot_sha256,
            repository_root=REPOSITORY_ROOT,
            scan_report=scan_report,
        )
    except Exception as error:
        verifier_failure = getattr(verifier, "DeployFailure", ())
        if (
            isinstance(verifier_failure, type)
            and isinstance(error, verifier_failure)
        ):
            raise ops.DeployFailure(str(error)) from error
        if isinstance(error, ops.DeployFailure):
            raise
        raise ops.DeployFailure(
            "Commerce public-boundary verification failed with "
            f"{type(error).__name__}."
        ) from error

    expected_artifact_path = (
        f"plugin-dist/robbottx-core-{args.plugin_version}.zip"
    )
    if (
        not isinstance(result, dict)
        or set(result)
        != {"artifact_path", "git_head", "receipt_body_sha256"}
        or result.get("artifact_path") != expected_artifact_path
        or result.get("git_head") != template_head
        or re.fullmatch(
            r"[0-9a-f]{64}",
            str(result.get("receipt_body_sha256", "")),
        )
        is None
    ):
        raise ops.DeployFailure(
            "Commerce public-boundary verification returned an invalid proof."
        )
    return route_template


def build_route_code(route_token: str, template: str) -> str:
    if not re.fullmatch(
        r"commerce-[1-9][0-9]{9,}-[0-9a-f]{32}",
        route_token,
    ):
        raise ops.DeployFailure(
            "Commerce route token has an invalid release-bound shape."
        )
    if not isinstance(template, str):
        raise ops.DeployFailure(
            "Commerce route template was not frozen before runtime access."
        )
    if (
        hashlib.sha256(template.encode("utf-8")).hexdigest()
        != ROUTE_TEMPLATE_SHA256
    ):
        raise ops.DeployFailure(
            "Commerce route template does not match the reviewed release."
        )
    route_code = template.replace("{{ROUTE_TOKEN}}", route_token)
    if "{{" in route_code or "}}" in route_code:
        raise ops.DeployFailure(
            "Commerce route template has unresolved placeholders."
        )
    expected_route = f"'/run-{route_token}'"
    forbidden_write_patterns = (
        r"\badd_option\s*\(",
        r"\bdelete_option\s*\(",
        r"\bdelete_post_meta\s*\(",
        r"\bupdate_post_meta\s*\(",
        r"\bwp_delete_post\s*\(",
        r"\bwp_insert_post\s*\(",
    )
    woo_page_keys = {
        29: "shop",
        30: "cart",
        31: "checkout",
        32: "myaccount",
    }
    expected_page_blocks = {
        page_id: (slug, title, woo_page_keys[page_id])
        for page_id, (slug, title) in EXPECTED_PAGES.items()
    }
    declared_page_ids = [
        int(value)
        for value in re.findall(
            r"^\s{8}([0-9]+)\s*=>\s*array\(\s*$",
            route_code,
            flags=re.MULTILINE,
        )
    ]
    page_blocks_are_exact = declared_page_ids == list(expected_page_blocks)
    for page_id, (slug, title, woo_key) in expected_page_blocks.items():
        expected_block = (
            f"        {page_id} => array(\n"
            f"            'slug'    => '{slug}',\n"
            f"            'title'   => '{title}',\n"
            f"            'woo_key' => '{woo_key}',\n"
            "        ),"
        )
        page_blocks_are_exact = (
            page_blocks_are_exact
            and route_code.count(expected_block) == 1
        )
    option_write_keys = re.findall(
        r"\bupdate_option\s*\(\s*'([^']+)'",
        route_code,
    )
    if (
        route_code.count(expected_route) != 1
        or route_code.count("'methods'             => 'GET'") != 1
        or route_code.count("'methods'             => 'POST'") != 1
        or option_write_keys
        != ["woocommerce_coming_soon"]
        or len(re.findall(r"\bwp_update_post\s*\(", route_code)) != 1
        or route_code.count("$rollback = static function") != 1
        or route_code.count("$abort_transaction = static function") != 1
        or route_code.count("catch ( Throwable $error )") != 2
        or route_code.count("global $wpdb;") != 1
        or route_code.count(
            "$wpdb->query( 'START TRANSACTION' )"
        )
        != 1
        or route_code.count("$wpdb->query( 'ROLLBACK' )") != 1
        or route_code.count("$wpdb->query( 'COMMIT' )") != 1
        or route_code.count("clean_post_cache( $page_id )") != 1
        or route_code.count("wp_cache_delete(") != 3
        or route_code.count("$original_titles = array();") != 1
        or route_code.count("$original_coming_soon = (string)") != 1
        or route_code.count("$verify_original_state = static function")
        != 1
        or route_code.count(
            "robbottx_commerce_transaction_start_failed"
        )
        != 1
        or route_code.count("robbottx_commerce_rollback_failed") != 1
        or route_code.count(
            "robbottx_commerce_transaction_rolled_back"
        )
        != 1
        or not page_blocks_are_exact
        or any(
            re.search(pattern, route_code)
            for pattern in forbidden_write_patterns
        )
    ):
        raise ops.DeployFailure(
            "Commerce route template exceeds the reviewed write scope."
        )
    return route_code


def verify_authority(base_url: str, auth: str) -> None:
    status, content_type, body = ops.request(
        (
            f"{base_url}/wp-json/wp/v2/users/me"
            "?context=edit&_fields=id,roles,capabilities"
        ),
        auth=auth,
    )
    identity = ops.json_object(
        status,
        content_type,
        body,
        "Application Password verification",
    )
    capabilities = identity.get("capabilities", {})
    required = {
        "edit_pages",
        "edit_published_pages",
        "manage_options",
        "manage_woocommerce",
        "update_plugins",
    }
    if (
        not isinstance(identity.get("id"), int)
        or identity["id"] <= 0
        or not isinstance(identity.get("roles"), list)
        or "administrator" not in identity["roles"]
        or not isinstance(capabilities, dict)
        or any(capabilities.get(item) is not True for item in required)
    ):
        raise ops.DeployFailure(
            "Authenticated WordPress user lacks commerce authority."
        )


def verify_snippet_bound(base_url: str, auth: str) -> int:
    return require_snippet_capacity(base_url, auth)


def page_title(record: dict[str, Any]) -> str:
    title = record.get("title")
    if not isinstance(title, dict):
        return ""
    value = title.get("raw", title.get("rendered", ""))
    return value if isinstance(value, str) else ""


def verify_pages(
    base_url: str,
    auth: str,
    *,
    require_titles: bool,
) -> dict[str, bool]:
    evidence: dict[str, bool] = {}
    for page_id, (slug, expected_title) in EXPECTED_PAGES.items():
        status, content_type, body = ops.request(
            (
                f"{base_url}/wp-json/wp/v2/pages/{page_id}"
                "?context=edit&_fields=id,slug,status,title,link"
            ),
            auth=auth,
        )
        record = ops.json_object(
            status,
            content_type,
            body,
            "Commerce page verification",
        )
        identity_matches = (
            record.get("id") == page_id
            and record.get("slug") == slug
            and record.get("status") == "publish"
            and record.get("link") == f"{base_url}/{slug}/"
        )
        if not identity_matches:
            raise ops.DeployFailure(
                "A commerce page identity did not match the review."
            )
        title_matches = page_title(record) == expected_title
        if require_titles and not title_matches:
            raise ops.DeployFailure(
                "A reviewed English commerce title is absent."
            )
        evidence[slug] = title_matches
    return evidence


def read_page_title_values(
    base_url: str,
    auth: str,
) -> dict[str, str]:
    values: dict[str, str] = {}
    for page_id, (slug, _) in EXPECTED_PAGES.items():
        status, content_type, body = ops.request(
            (
                f"{base_url}/wp-json/wp/v2/pages/{page_id}"
                "?context=edit&_fields=id,slug,status,title,link"
            ),
            auth=auth,
        )
        record = ops.json_object(
            status,
            content_type,
            body,
            "Commerce title snapshot",
        )
        if (
            record.get("id") != page_id
            or record.get("slug") != slug
            or record.get("status") != "publish"
            or record.get("link") != f"{base_url}/{slug}/"
        ):
            raise ops.DeployFailure(
                "A commerce title snapshot changed identity."
            )
        title = page_title(record)
        if not title:
            raise ops.DeployFailure(
                "A commerce title snapshot was empty."
            )
        values[slug] = title
    return values


def _read_json_file(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ops.DeployFailure(
            f"{context} is unavailable or invalid."
        ) from error
    if not isinstance(value, dict):
        raise ops.DeployFailure(f"{context} has an unexpected shape.")
    return value


def find_commerce_chrome() -> Path:
    configured = os.environ.get("CHROME_PATH", "")
    candidates = [
        configured
        if "\x00" not in configured and "\r" not in configured
        and "\n" not in configured
        else "",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
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
        try:
            executable = Path(candidate).expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        if executable.is_file():
            return executable
    raise ops.DeployFailure(
        "A supported Chrome executable is required for commerce proof."
    )


def verify_commerce_dom_dependencies() -> tuple[Path, Path, Path]:
    try:
        helper_bytes = COMMERCE_DOM_HELPER_PATH.read_bytes()
        helper_path = COMMERCE_DOM_HELPER_PATH.resolve(strict=True)
        repository_root = REPOSITORY_ROOT.resolve(strict=True)
    except OSError as error:
        raise ops.DeployFailure(
            "The pinned commerce browser verifier is unavailable."
        ) from error
    if (
        COMMERCE_DOM_HELPER_PATH.is_symlink()
        or repository_root not in helper_path.parents
        or hashlib.sha256(helper_bytes).hexdigest()
        != COMMERCE_DOM_HELPER_SHA256
    ):
        raise ops.DeployFailure(
            "The commerce browser verifier does not match its release pin."
        )

    package = _read_json_file(
        repository_root / "package.json",
        "package.json",
    )
    lock = _read_json_file(
        repository_root / "package-lock.json",
        "package-lock.json",
    )
    installed = _read_json_file(
        repository_root
        / "node_modules"
        / "puppeteer-core"
        / "package.json",
        "Installed Puppeteer package",
    )
    dependencies = package.get("devDependencies")
    lock_packages = lock.get("packages")
    root_record = (
        lock_packages.get("")
        if isinstance(lock_packages, dict)
        else None
    )
    lock_record = (
        lock_packages.get("node_modules/puppeteer-core")
        if isinstance(lock_packages, dict)
        else None
    )
    root_dependencies = (
        root_record.get("devDependencies")
        if isinstance(root_record, dict)
        else None
    )
    if (
        not isinstance(dependencies, dict)
        or dependencies.get("puppeteer-core")
        != EXPECTED_PUPPETEER_VERSION
        or not isinstance(root_dependencies, dict)
        or root_dependencies.get("puppeteer-core")
        != EXPECTED_PUPPETEER_VERSION
        or not isinstance(lock_record, dict)
        or lock_record.get("version") != EXPECTED_PUPPETEER_VERSION
        or lock_record.get("resolved") != EXPECTED_PUPPETEER_URL
        or lock_record.get("integrity") != EXPECTED_PUPPETEER_INTEGRITY
        or installed.get("name") != "puppeteer-core"
        or installed.get("version") != EXPECTED_PUPPETEER_VERSION
    ):
        raise ops.DeployFailure(
            "The commerce browser dependency is not exactly pinned."
        )

    node_value = shutil.which("node")
    if not node_value or not Path(node_value).is_file():
        raise ops.DeployFailure(
            "The Node.js runtime required for commerce proof was not found."
        )
    return Path(node_value).resolve(), find_commerce_chrome(), helper_path


def commerce_dom_process_environment() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if (
            key.casefold() in COMMERCE_DOM_ENVIRONMENT_ALLOWLIST
            and "\x00" not in value
        )
    }
    environment["LANG"] = "C"
    environment["LC_ALL"] = "C"
    return environment


def remove_owned_commerce_dom_profile(profile: Path) -> bool:
    temporary_root = Path(tempfile.gettempdir()).resolve()
    candidate = profile.resolve(strict=False)
    if (
        candidate.parent != temporary_root
        or not candidate.name.startswith(COMMERCE_DOM_PROFILE_PREFIX)
        or len(candidate.name) <= len(COMMERCE_DOM_PROFILE_PREFIX)
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


def terminate_commerce_dom_process_tree(
    process: subprocess.Popen[str],
) -> None:
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


def _is_bounded_count(value: object) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= 10_000
    )


def _require_dom_counts(
    dom: object,
    expected_keys: set[str],
) -> dict[str, int]:
    if (
        not isinstance(dom, dict)
        or set(dom) != expected_keys
        or not all(_is_bounded_count(value) for value in dom.values())
    ):
        raise ops.DeployFailure(
            "Commerce browser proof returned an unexpected result."
        )
    return dom


def validate_commerce_dom_result(
    result: object,
    *,
    mode: str,
    expected_path: str,
) -> None:
    expected_top_keys = {
        "dom",
        "failureCodes",
        "mode",
        "navigation",
        "operational",
        "passed",
        "routeUi",
        "schemaVersion",
        "source",
        "stylesheets",
    }
    if (
        not isinstance(result, dict)
        or set(result) != expected_top_keys
        or result.get("schemaVersion") != COMMERCE_DOM_SCHEMA_VERSION
        or result.get("operational") is not True
        or result.get("passed") is not True
        or result.get("mode") != mode
        or result.get("source") != "live"
        or result.get("failureCodes") != []
    ):
        raise ops.DeployFailure(
            "Commerce browser proof returned an unexpected result."
        )

    navigation = result.get("navigation")
    stylesheets = result.get("stylesheets")
    if (
        not isinstance(navigation, dict)
        or set(navigation)
        != {
            "finalOrigin",
            "finalPath",
            "redirectCount",
            "redirectStatus",
            "status",
        }
        or not isinstance(stylesheets, dict)
        or set(stylesheets)
        != {
            "blockedCount",
            "externalCount",
            "failedCount",
            "loadedCount",
        }
        or not all(
            _is_bounded_count(value)
            for value in stylesheets.values()
        )
        or stylesheets["failedCount"] != 0
        or stylesheets["blockedCount"] != 0
        or stylesheets["loadedCount"] != stylesheets["externalCount"]
        or navigation.get("status") != 200
        or navigation.get("finalOrigin") != "https://robbottx.com"
        or not _is_bounded_count(navigation.get("redirectCount"))
    ):
        raise ops.DeployFailure(
            "Commerce browser proof returned an unexpected result."
        )

    route_ui = result.get("routeUi")
    direct_navigation = (
        navigation.get("finalPath") == expected_path
        and navigation.get("redirectCount") == 0
        and navigation.get("redirectStatus") is None
    )
    checkout_empty_redirect = (
        mode == "checkout"
        and route_ui == "empty_cart_redirect"
        and navigation.get("finalPath") == "/cart/"
        and navigation.get("redirectCount") == 1
        and navigation.get("redirectStatus") == 302
    )
    if not (direct_navigation or checkout_empty_redirect):
        raise ops.DeployFailure(
            "Commerce browser proof returned an unexpected result."
        )

    dom = result.get("dom")
    if mode == "shop":
        counts = _require_dom_counts(
            dom,
            {"productCardCount", "productLinkCount"},
        )
        valid_catalog = (
            route_ui == "product_catalog"
            and counts["productCardCount"] > 0
            and counts["productLinkCount"]
            >= counts["productCardCount"]
        )
        passed = valid_catalog
    elif mode == "cart":
        counts = _require_dom_counts(
            dom,
            {"cartFormCount", "dataInputCount", "submitCount"},
        )
        valid_cart = (
            route_ui == "cart"
            and counts["cartFormCount"] == 1
            and counts["dataInputCount"] > 0
            and counts["submitCount"] > 0
        )
        valid_empty = (
            route_ui == "reviewed_empty_state"
            and all(value == 0 for value in counts.values())
        )
        passed = valid_cart or valid_empty
    elif mode == "account":
        counts = _require_dom_counts(
            dom,
            {
                "loginFormCount",
                "passwordCount",
                "submitCount",
                "usernameCount",
            },
        )
        passed = (
            route_ui == "login_form"
            and counts["loginFormCount"] == 1
            and counts["usernameCount"] == 1
            and counts["passwordCount"] == 1
            and counts["submitCount"] == 1
        )
    elif mode == "checkout" and checkout_empty_redirect:
        counts = _require_dom_counts(
            dom,
            {"cartFormCount", "dataInputCount", "submitCount"},
        )
        passed = all(value == 0 for value in counts.values())
    elif mode == "checkout":
        counts = _require_dom_counts(
            dom,
            {"checkoutFormCount", "dataInputCount", "submitCount"},
        )
        passed = (
            route_ui == "checkout"
            and counts["checkoutFormCount"] == 1
            and counts["dataInputCount"] > 0
            and counts["submitCount"] == 1
        )
    elif mode == "product":
        counts = _require_dom_counts(
            dom,
            {
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
        )
        passed = (
            route_ui == "product"
            and counts["actionFormCount"] == 1
            and counts["addToCartCount"] == 1
            and counts["identifierCount"] in {1, 2}
            and counts["offerEvidenceCount"] == 1
            and counts["positiveStockCount"] == 1
            and counts["primaryActionCount"] == 1
            and counts["primarySurfaceCount"] == 1
            and counts["productCardCount"] == 1
            and counts["stockCount"] == 1
            and counts["submitCount"] == 1
            and counts["titleCount"] == 1
            and counts["validOfferEvidenceCount"] == 1
        )
    else:
        passed = False

    if not passed:
        raise ops.DeployFailure(
            "Commerce browser proof returned an unexpected result."
        )


def run_commerce_dom_proof(
    mode: str,
    url: str,
    *,
    product_id: int | None = None,
) -> None:
    try:
        parsed = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qsl(
            parsed.query,
            keep_blank_values=True,
            strict_parsing=True,
        )
    except ValueError as error:
        raise ops.DeployFailure(
            "Commerce browser proof received an invalid target."
        ) from error
    expected_paths = {
        "account": "/my-account/",
        "cart": "/cart/",
        "checkout": "/checkout/",
        "shop": "/shop/",
    }
    if (
        mode not in {*expected_paths, "product"}
        or len(url) > 2_048
        or any(ord(character) < 32 for character in url)
        or parsed.scheme != "https"
        or parsed.netloc.lower() != "robbottx.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or re.fullmatch(r"rbtxcb=[0-9]{1,20}", parsed.query) is None
        or len(query) != 1
        or query[0][0] != "rbtxcb"
        or re.fullmatch(r"[0-9]{1,20}", query[0][1]) is None
        or int(query[0][1]) < 1
        or (
            mode != "product"
            and parsed.path != expected_paths[mode]
        )
        or (
            mode == "product"
            and not parsed.path.startswith("/product/")
        )
        or (
            mode == "product"
            and (
                not isinstance(product_id, int)
                or isinstance(product_id, bool)
                or product_id < 1
                or product_id > 9_007_199_254_740_991
            )
        )
        or (mode != "product" and product_id is not None)
    ):
        raise ops.DeployFailure(
            "Commerce browser proof received an invalid target."
        )

    node_path, chrome_path, helper_path = (
        verify_commerce_dom_dependencies()
    )
    payload: dict[str, object] = {
        "expectedOrigin": "https://robbottx.com",
        "expectedPath": parsed.path,
        "mode": mode,
        "url": url,
    }
    if mode == "product":
        payload["productId"] = product_id
    input_json = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    try:
        profile = Path(
            tempfile.mkdtemp(prefix=COMMERCE_DOM_PROFILE_PREFIX)
        ).resolve()
    except OSError as error:
        raise ops.DeployFailure(
            "Commerce browser proof could not be completed."
        ) from error

    creation_flags = 0
    popen_options: dict[str, object] = {}
    if os.name == "nt":
        creation_flags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    else:
        popen_options["start_new_session"] = True
    try:
        process = subprocess.Popen(
            [
                str(node_path),
                str(helper_path),
                "--chrome",
                str(chrome_path),
                "--profile",
                str(profile),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            cwd=str(REPOSITORY_ROOT),
            encoding="utf-8",
            errors="strict",
            env=commerce_dom_process_environment(),
            creationflags=creation_flags,
            **popen_options,
        )
    except OSError as error:
        remove_owned_commerce_dom_profile(profile)
        raise ops.DeployFailure(
            "Commerce browser proof could not be completed."
        ) from error
    try:
        output, _ = process.communicate(
            input=input_json,
            timeout=COMMERCE_DOM_PROCESS_TIMEOUT_SECONDS,
        )
    except (
        OSError,
        subprocess.SubprocessError,
        UnicodeError,
    ) as error:
        terminate_commerce_dom_process_tree(process)
        try:
            process.communicate(timeout=5)
        except (
            OSError,
            subprocess.SubprocessError,
            UnicodeError,
        ):
            terminate_commerce_dom_process_tree(process)
        remove_owned_commerce_dom_profile(profile)
        raise ops.DeployFailure(
            "Commerce browser proof could not be completed."
        ) from error
    profile_removed = remove_owned_commerce_dom_profile(profile)
    if (
        process.returncode != 0
        or not profile_removed
        or not isinstance(output, str)
        or len(output.encode("utf-8")) > MAX_COMMERCE_DOM_OUTPUT_BYTES
    ):
        raise ops.DeployFailure(
            "Commerce browser proof could not be completed."
        )
    try:
        result = json.loads(output)
    except json.JSONDecodeError as error:
        raise ops.DeployFailure(
            "Commerce browser proof returned an unexpected result."
        ) from error
    validate_commerce_dom_result(
        result,
        mode=mode,
        expected_path=parsed.path,
    )


def verify_public_product_page(
    base_url: str,
    product_href: str,
) -> tuple[str, int]:
    product_url = urllib.parse.urljoin(
        f"{base_url}/shop/",
        product_href,
    )
    parsed_url = urllib.parse.urlsplit(product_url)
    if (
        len(product_url) > 2_048
        or any(ord(character) < 32 for character in product_url)
        or parsed_url.scheme != "https"
        or parsed_url.netloc.lower() != "robbottx.com"
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.fragment
        or parsed_url.query
    ):
        raise ops.DeployFailure(
            "A public Shop product link is not a safe canonical URL."
        )
    requested_product_url = ops.add_cache_buster(product_url)
    status, content_type, body = ops.request(
        requested_product_url,
        timeout=90,
        accept="text/html",
    )
    media_type = content_type.split(";", 1)[0].strip().lower()
    charset = ""
    if ";" in content_type:
        for parameter in content_type.split(";")[1:]:
            name, separator, value = parameter.partition("=")
            if separator and name.strip().lower() == "charset":
                charset = value.strip().strip('"').lower()
    facts = ProductPageFacts(product_url)
    try:
        facts.feed(body)
        facts.close()
    except Exception as error:
        raise ops.DeployFailure(
            "A public Shop product page could not be parsed."
        ) from error
    public_surface = " ".join(
        [facts.title, facts.h1, facts.visible_text]
    )
    lowered_surface = public_surface.lower()
    stylesheet_hides_proof = stylesheet_hides_reviewed_proof(
        product_url,
        body,
        " ".join(facts.style_parts),
        product_catalog=True,
        product_page=True,
    )
    if (
        status != 200
        or media_type != "text/html"
        or charset not in {"", "utf-8"}
        or facts.html_count != 1
        or facts.head_count != 1
        or facts.body_count != 1
        or facts.invalid_markup
        or facts.title_count != 1
        or facts.title_inside_head_count != 1
        or facts.main_count != 1
        or facts.h1_count != 1
        or facts.product_title_count != 1
        or facts.html_language != "en-US"
        or "RobbottX" not in facts.title
        or not facts.h1
        or "single-product" not in facts.body_classes
        or "error404" in facts.body_classes
        or any(
            "coming-soon" in class_name.lower()
            for class_name in facts.body_classes
        )
        or facts.product_wrapper_count != 1
        or facts.product_structure_count != 1
        or len(facts.verified_product_ids) != 1
        or stylesheet_hides_proof
        or "page not found" in lowered_surface
        or "not found" in facts.h1.lower()
        or any(
            "\u0590" <= character <= "\u05ff"
            for character in public_surface
        )
    ):
        raise ops.DeployFailure(
            "A public Shop product link did not expose a usable "
            "WooCommerce product page."
        )
    return requested_product_url, facts.verified_product_ids[0]


def verify_public_store(base_url: str) -> None:
    requested_shop_url = ops.add_cache_buster(f"{base_url}/shop/")
    status, content_type, body = ops.request(
        requested_shop_url,
        timeout=90,
        accept="text/html",
    )
    facts = CommercePageFacts()
    try:
        facts.feed(body)
        facts.close()
    except Exception as error:
        raise ops.DeployFailure(
            "Public shop HTML could not be parsed."
        ) from error
    public_surface = " ".join(
        [facts.title, facts.h1, facts.public_text]
    )
    lowered_surface = public_surface.lower()
    media_type = content_type.split(";", 1)[0].strip().lower()
    charset = ""
    if ";" in content_type:
        for parameter in content_type.split(";")[1:]:
            name, separator, value = parameter.partition("=")
            if separator and name.strip().lower() == "charset":
                charset = value.strip().strip('"').lower()
    reviewed_empty_state = (
        facts.woocommerce_info_in_main_count > 0
        and (
            "No products were found matching your selection."
            in facts.woocommerce_info_text
        )
    )
    stylesheet_hides_proof = stylesheet_hides_reviewed_proof(
        f"{base_url}/shop/",
        body,
        " ".join(facts.style_parts),
        product_catalog=facts.product_catalog,
        product_page=False,
    )
    if (
        status != 200
        or media_type != "text/html"
        or charset not in {"", "utf-8"}
        or facts.html_count != 1
        or facts.head_count != 1
        or facts.body_count != 1
        or facts.invalid_markup
        or "woocommerce-shop" not in facts.body_classes
        or any(
            "coming-soon" in class_name.lower()
            for class_name in facts.class_counts
        )
        or "coming soon" in lowered_surface
        or facts.html_language != "en-US"
        or facts.title_count != 1
        or facts.title_inside_head_count != 1
        or facts.title != "Shop \u2013 RobbottX"
        or facts.h1_count != 1
        or facts.h1_inside_main_count != 1
        or facts.h1 != "Shop"
        or facts.main_count != 1
        or not facts.product_catalog
        or reviewed_empty_state
        or (
            facts.product_item_count
            != facts.valid_product_item_count
        )
        or stylesheet_hides_proof
        or any(
            "\u0590" <= character <= "\u05ff"
            for character in public_surface
        )
    ):
        raise ops.DeployFailure(
            "Public shop did not expose the reviewed live English surface."
        )
    verified_products: list[tuple[str, int]] = []
    if facts.product_catalog:
        product_links = sorted(set(facts.product_links))
        if not product_links or len(product_links) > 100:
            raise ops.DeployFailure(
                "Public Shop product-link coverage is outside the "
                "reviewed verification bound."
            )
        for product_href in product_links:
            verified_products.append(
                verify_public_product_page(base_url, product_href)
            )
    for mode, path in (
        ("shop", "/shop/"),
        ("cart", "/cart/"),
        ("account", "/my-account/"),
        ("checkout", "/checkout/"),
    ):
        target_url = (
            requested_shop_url
            if mode == "shop"
            else ops.add_cache_buster(f"{base_url}{path}")
        )
        run_commerce_dom_proof(mode, target_url)
    for product_url, product_id in verified_products:
        run_commerce_dom_proof(
            "product",
            product_url,
            product_id=product_id,
        )


def prove_configuration_namespace_absent(
    base_url: str,
) -> tuple[bool, list[str]]:
    try:
        status, content_type, body = ops.request(
            ops.add_cache_buster(f"{base_url}/wp-json/"),
            timeout=30,
        )
        index = ops.json_object(
            status,
            content_type,
            body,
            "Commerce REST route inventory",
        )
        routes = index.get("routes")
        if not isinstance(routes, dict):
            return False, [
                "commerce REST route inventory has an unexpected shape"
            ]
        if any(
            isinstance(route_pattern, str)
            and route_pattern.startswith(CONFIGURATION_NAMESPACE)
            for route_pattern in routes
        ):
            return False, [
                "a commerce configuration namespace route is registered"
            ]
        return True, []
    except Exception as error:
        return False, [
            "commerce REST route inventory raised "
            f"{type(error).__name__}"
        ]


def require_configuration_namespace_absent(
    base_url: str,
    context: str,
) -> None:
    absent, failures = prove_configuration_namespace_absent(base_url)
    if absent:
        return
    summary = "; ".join(failures)
    raise ops.DeployFailure(
        f"{context}: temporary commerce namespace is not absent. "
        f"{summary}."
    )


def expected_woocommerce_page_ids() -> dict[str, int]:
    return {
        slug: page_id
        for page_id, (slug, _) in EXPECTED_PAGES.items()
    }


def read_commerce_state(
    base_url: str,
    auth: str,
    route_path: str,
    *,
    require_live: bool,
) -> dict[str, dict[str, Any]]:
    status, content_type, body = ops.request(
        f"{base_url}{route_path}",
        method="GET",
        auth=auth,
        timeout=30,
    )
    state = ops.json_object(
        status,
        content_type,
        body,
        "Independent commerce state verification",
    )
    coming_soon = state.get("coming_soon")
    store_pages_only = state.get("store_pages_only")
    page_ids = state.get("page_ids")
    expected_page_ids = expected_woocommerce_page_ids()
    if (
        coming_soon not in {"yes", "no"}
        or store_pages_only not in {"yes", "no"}
        or (require_live and coming_soon != "no")
        or not isinstance(page_ids, dict)
        or set(page_ids) != set(expected_page_ids)
        or any(
            not isinstance(value, int)
            or isinstance(value, bool)
            for value in page_ids.values()
        )
        or page_ids != expected_page_ids
    ):
        raise ops.DeployFailure(
            "WooCommerce state was not independently verified."
        )
    return {
        "woocommerce_options": {
            "coming_soon": coming_soon,
            "store_pages_only": store_pages_only,
        },
        "woocommerce_page_ids": page_ids,
    }


def verify_commerce_state(
    base_url: str,
    auth: str,
    route_path: str,
) -> dict[str, dict[str, Any]]:
    return read_commerce_state(
        base_url,
        auth,
        route_path,
        require_live=True,
    )


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def _json_object_without_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError("duplicate JSON object key")
        document[key] = value
    return document


def confirm_exact_configuration_callback(
    status: int,
    content_type: str,
    body: str,
    *,
    store_pages_only: str,
) -> None:
    if (
        status < 200
        or status >= 300
        or content_type.split(";", 1)[0].strip().lower()
        != "application/json"
        or not isinstance(body, str)
        or len(body.encode("utf-8")) > 1024 * 1024
    ):
        raise ops.DeployFailure(
            "Commerce configuration callback was not exact."
        )
    try:
        callback = json.loads(
            body,
            object_pairs_hook=_json_object_without_duplicate_keys,
        )
    except (
        json.JSONDecodeError,
        RecursionError,
        UnicodeError,
        ValueError,
    ) as error:
        raise ops.DeployFailure(
            "Commerce configuration callback was not exact."
        ) from error

    if (
        not isinstance(callback, dict)
        or set(callback)
        != {
            "cache_flush_sent",
            "result",
            "state",
            "store_live",
            "titles_verified",
        }
        or callback["result"] is not True
        or callback["store_live"] is not True
        or callback["cache_flush_sent"] is not True
        or not isinstance(callback["titles_verified"], dict)
        or set(callback["titles_verified"])
        != set(TITLE_EVIDENCE_SCHEMA)
        or any(
            value is not True
            for value in callback["titles_verified"].values()
        )
        or callback["state"]
        != {
            "coming_soon": "no",
            "store_pages_only": store_pages_only,
            "page_ids": expected_woocommerce_page_ids(),
        }
    ):
        raise ops.DeployFailure(
            "Commerce configuration callback was not exact."
        )


def _run_configuration(
    args: argparse.Namespace,
    evidence: dict[str, Any],
) -> None:
    evidence["failure_stage"] = "public_boundary"
    route_template = verify_commerce_release_boundary(args)

    evidence["failure_stage"] = "runtime_authority"
    base_url = ops.normalize_base_url(ops.required_env("WP_BASE_URL"))
    user = ops.required_env("WP_USER")
    password = ops.required_env("WP_APP_PASSWORD")
    auth = ops.make_auth(user, password)

    verify_authority(base_url, auth)
    evidence["authority_verified"] = True

    evidence["failure_stage"] = "public_record_preflight"
    snippet_count = verify_snippet_bound(base_url, auth)
    before_titles = verify_pages(
        base_url,
        auth,
        require_titles=False,
    )
    before_title_values = read_page_title_values(base_url, auth)
    evidence["page_identities_verified"] = True
    evidence["snippet_count_before"] = snippet_count
    evidence["snippet_limit"] = MAX_CODE_SNIPPETS_RECORDS
    evidence["before"] = {
        "titles": before_titles,
        "woocommerce_options": {
            "coming_soon": None,
            "store_pages_only": None,
        },
        "woocommerce_page_ids": {
            "cart": None,
            "checkout": None,
            "my-account": None,
            "shop": None,
        },
    }

    route_token = ops.make_route_token("commerce")
    route_path = f"/wp-json/agentconfigure/v1/run-{route_token}"
    snippet_name = f"tmp-robbottx-commerce-configure-{route_token}"
    evidence["failure_stage"] = "temporary_surface_preflight"
    require_configuration_namespace_absent(
        base_url,
        "Pre-create route verification",
    )
    ops.require_snippet_name_absent(base_url, snippet_name, auth)
    evidence["fixed_route_absent_before"] = True
    evidence["route_absent_before"] = True
    evidence["snippet_name_absent_before"] = True
    if not args.execute:
        evidence["cleanup"] = {
            "attempted": False,
            "fixed_route_absent": True,
            "proven": True,
            "required": False,
            "route_absent": True,
            "snippet_absent": True,
        }
        evidence.pop("failure_stage", None)
        evidence["status"] = "preflight_ok"
        return

    route_code = build_route_code(route_token, route_template)
    snippet_id: int | None = None
    callback_confirmed = False
    snippet_absent_after = False
    route_absent_after = False
    fixed_route_absent_after = False
    failure: Exception | None = None
    failure_stage = "temporary_route_creation"

    try:
        failure_stage = "action_boundary"
        evidence["failure_stage"] = failure_stage
        action_template = verify_commerce_release_boundary(args)
        if not secrets.compare_digest(
            action_template.encode("utf-8"),
            route_template.encode("utf-8"),
        ):
            raise ops.DeployFailure(
                "Commerce release boundary changed before the mutation."
            )

        failure_stage = "temporary_route_creation"
        evidence["failure_stage"] = failure_stage
        status, content_type, body = ops.request(
            f"{base_url}/wp-json/code-snippets/v1/snippets",
            method="POST",
            auth=auth,
            payload={
                "name": snippet_name,
                "code": route_code,
                "scope": "global",
                "active": True,
            },
        )
        created = ops.json_object(
            status,
            content_type,
            body,
            "Temporary commerce route creation",
        )
        snippet_id = ops.parse_created_snippet_id(created)

        failure_stage = "before_option_state"
        evidence["failure_stage"] = failure_stage
        before_state = read_commerce_state(
            base_url,
            auth,
            route_path,
            require_live=False,
        )
        before_options = before_state["woocommerce_options"]
        before_page_ids = before_state["woocommerce_page_ids"]
        evidence["before"].update(before_state)

        failure_stage = "configuration_callback"
        evidence["failure_stage"] = failure_stage
        try:
            status, content_type, body = ops.request(
                f"{base_url}{route_path}",
                method="POST",
                auth=auth,
                payload={},
                timeout=120,
            )
            confirm_exact_configuration_callback(
                status,
                content_type,
                body,
                store_pages_only=before_options["store_pages_only"],
            )
            callback_confirmed = True
        except Exception:
            callback_confirmed = False
        evidence["callback_confirmed"] = callback_confirmed

        failure_stage = "after_state"
        evidence["failure_stage"] = failure_stage
        after_state = read_commerce_state(
            base_url,
            auth,
            route_path,
            require_live=False,
        )
        option_state = after_state["woocommerce_options"]
        after_page_ids = after_state["woocommerce_page_ids"]
        after_title_values = read_page_title_values(base_url, auth)
        store_pages_only_unchanged = (
            option_state["store_pages_only"]
            == before_options["store_pages_only"]
        )
        page_mappings_unchanged = (
            after_page_ids == before_page_ids
        )
        expected_title_values = {
            slug: title
            for _, (slug, title) in EXPECTED_PAGES.items()
        }
        rollback_verified = (
            after_state == before_state
            and after_title_values == before_title_values
        )
        applied_state_verified = (
            option_state["coming_soon"] == "no"
            and store_pages_only_unchanged
            and page_mappings_unchanged
            and after_title_values == expected_title_values
        )
        evidence["after"] = {
            "page_mappings_unchanged": page_mappings_unchanged,
            "public_store_verified": False,
            "store_pages_only_unchanged": (
                store_pages_only_unchanged
            ),
            "titles": {
                slug: (
                    after_title_values.get(slug)
                    == expected_title_values[slug]
                )
                for slug in TITLE_EVIDENCE_SCHEMA
            },
            "woocommerce_options": option_state,
            "woocommerce_page_ids": after_page_ids,
        }
        if not store_pages_only_unchanged:
            raise ops.DeployFailure(
                "WooCommerce store protection scope changed unexpectedly."
            )
        if not page_mappings_unchanged:
            raise ops.DeployFailure(
                "WooCommerce page mappings changed unexpectedly."
            )
        if rollback_verified and not applied_state_verified:
            failure_stage = "rollback_verified"
            evidence["failure_stage"] = failure_stage
            raise ops.DeployFailure(
                "Commerce configuration failed and the original "
                "state was independently verified."
            )
        if not applied_state_verified:
            failure_stage = "partial_state"
            evidence["failure_stage"] = failure_stage
            raise ops.DeployFailure(
                "Commerce configuration left an unreviewed partial state."
            )
        after_titles = verify_pages(
            base_url,
            auth,
            require_titles=True,
        )
        verify_public_store(base_url)
        evidence["after"]["titles"] = after_titles
        evidence["after"]["public_store_verified"] = True
    except Exception as error:
        failure = error
        evidence["failure_stage"] = failure_stage
    finally:
        cleanup_failures: list[str] = []
        try:
            snippet_absent_after, snippet_failures = (
                ops.cleanup_temporary_snippets(
                    base_url,
                    auth,
                    snippet_name,
                    snippet_id,
                )
            )
            cleanup_failures.extend(snippet_failures)
        except Exception as error:
            cleanup_failures.append(
                "snippet cleanup raised "
                f"{type(error).__name__}"
            )

        unique_probe = False
        try:
            unique_probe, unique_failures = (
                ops.prove_deploy_route_absent(
                    base_url,
                    auth,
                    route_path,
                )
            )
            cleanup_failures.extend(unique_failures)
        except Exception as error:
            cleanup_failures.append(
                "unique-route cleanup proof raised "
                f"{type(error).__name__}"
            )

        namespace_inventory = False
        try:
            namespace_inventory, inventory_failures = (
                prove_configuration_namespace_absent(base_url)
            )
            cleanup_failures.extend(inventory_failures)
        except Exception as error:
            cleanup_failures.append(
                "commerce namespace inventory proof raised "
                f"{type(error).__name__}"
            )
        route_absent_after = unique_probe and namespace_inventory
        fixed_route_absent_after = namespace_inventory

        cleanup_proven = (
            snippet_absent_after
            and route_absent_after
            and fixed_route_absent_after
        )
        evidence["cleanup"] = {
            "attempted": True,
            "fixed_route_absent": fixed_route_absent_after,
            "proven": cleanup_proven,
            "required": True,
            "route_absent": route_absent_after,
            "snippet_absent": snippet_absent_after,
        }
        if not cleanup_proven:
            cleanup_message = (
                "Temporary commerce route cleanup was not proven."
            )
            if cleanup_failures:
                cleanup_message += " " + "; ".join(cleanup_failures) + "."
            if failure is None:
                failure = ops.DeployFailure(cleanup_message)
                evidence["failure_stage"] = "cleanup"
            else:
                failure = ops.DeployFailure(
                    "Commerce configuration failed with "
                    f"{type(failure).__name__}. {cleanup_message}"
                )

    if failure is not None:
        if isinstance(failure, ops.DeployFailure):
            raise failure
        raise ops.DeployFailure(
            "Commerce configuration failed with "
            f"{type(failure).__name__}."
        ) from failure

    evidence.pop("failure_stage", None)
    evidence["status"] = "configured"


def main() -> int:
    args = parse_args()
    output_path = prepare_output_path(args.output)
    evidence: dict[str, Any] = {
        "execute": bool(args.execute),
        "recorded_at": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
        "schema_version": 1,
        "status": "started",
    }
    try:
        _run_configuration(args, evidence)
    except Exception as error:
        evidence["failure_stage"] = evidence.get(
            "failure_stage",
            "unclassified",
        )
        evidence["failure_type"] = type(error).__name__
        evidence["status"] = "failed"
        evidence.setdefault(
            "cleanup",
            {
                "attempted": False,
                "fixed_route_absent": evidence.get(
                    "fixed_route_absent_before"
                ),
                "proven": True,
                "required": False,
                "route_absent": evidence.get("route_absent_before"),
                "snippet_absent": evidence.get(
                    "snippet_name_absent_before"
                ),
            },
        )
        require_allowlisted_evidence(
            evidence,
            COMMERCE_EVIDENCE_SCHEMA,
        )
        write_new_evidence(output_path, evidence)
        emit(evidence)
        if isinstance(error, ops.DeployFailure):
            raise
        raise ops.DeployFailure(
            "Commerce configuration failed with "
            f"{type(error).__name__}."
        ) from error

    require_allowlisted_evidence(
        evidence,
        COMMERCE_EVIDENCE_SCHEMA,
    )
    write_new_evidence(output_path, evidence)
    emit(evidence)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ops.DeployFailure as error:
        print(f"Commerce configuration failed: {error}", file=sys.stderr)
        sys.exit(1)
