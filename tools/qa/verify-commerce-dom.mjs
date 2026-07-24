#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import process from "node:process";

import puppeteer from "puppeteer-core";

const SCHEMA_VERSION = "1.0";
const PROFILE_PREFIX = "robbottx-commerce-browser-";
const MAX_INPUT_BYTES = 16 * 1024 * 1024;
const DEFAULT_OPERATION_TIMEOUT_MS = 45_000;
const CLEANUP_TIMEOUT_MS = 15_000;
const CLOSE_TIMEOUT_MS = 3_000;
const VALID_MODES = new Set([
  "account",
  "cart",
  "checkout",
  "product",
  "shop",
]);
const SAFE_CHILD_ENVIRONMENT_KEYS = [
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
];

function safeChildEnvironment(extra = {}) {
  const environment = { ...extra };
  for (const name of SAFE_CHILD_ENVIRONMENT_KEYS) {
    if (process.env[name] !== undefined) {
      environment[name] = process.env[name];
    }
  }
  return environment;
}

function parseArguments(argv) {
  let chrome = "";
  let operationTimeoutMs = DEFAULT_OPERATION_TIMEOUT_MS;
  let profile = "";
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--chrome" && index + 1 < argv.length) {
      chrome = argv[index + 1];
      index += 1;
      continue;
    }
    if (argument === "--profile" && index + 1 < argv.length) {
      profile = argv[index + 1];
      index += 1;
      continue;
    }
    if (
      argument === "--operation-timeout-ms"
      && index + 1 < argv.length
      && process.env.NODE_ENV === "test"
    ) {
      operationTimeoutMs = Number(argv[index + 1]);
      index += 1;
      continue;
    }
    throw new Error("invalid_arguments");
  }
  if (
    !chrome
    || !path.isAbsolute(chrome)
    || !fs.existsSync(chrome)
    || !Number.isInteger(operationTimeoutMs)
    || operationTimeoutMs < 50
    || operationTimeoutMs > DEFAULT_OPERATION_TIMEOUT_MS
  ) {
    throw new Error("invalid_arguments");
  }
  if (
    profile
    && (
      !path.isAbsolute(profile)
      || !fs.existsSync(profile)
      || !fs.statSync(profile).isDirectory()
      || !path.basename(profile).startsWith(PROFILE_PREFIX)
      || path.basename(profile).length <= PROFILE_PREFIX.length
    )
  ) {
    throw new Error("invalid_arguments");
  }
  if (profile) {
    const resolvedProfile = fs.realpathSync(profile);
    const configuredRoot = (
      process.env.NODE_ENV === "test"
      && process.env.ROBBOTTX_COMMERCE_PROOF_PROFILE_ROOT
    )
      ? path.resolve(process.env.ROBBOTTX_COMMERCE_PROOF_PROFILE_ROOT)
      : os.tmpdir();
    const resolvedRoot = fs.realpathSync(configuredRoot);
    if (path.dirname(resolvedProfile) !== resolvedRoot) {
      throw new Error("invalid_arguments");
    }
  }
  return { chrome, operationTimeoutMs, profile };
}

async function readStandardInput() {
  const chunks = [];
  let byteCount = 0;
  for await (const chunk of process.stdin) {
    byteCount += chunk.length;
    if (byteCount > MAX_INPUT_BYTES) {
      throw new Error("input_too_large");
    }
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString("utf8").replace(/^\uFEFF/u, "");
}

function validateInput(value) {
  if (
    value === null
    || typeof value !== "object"
    || Array.isArray(value)
    || !VALID_MODES.has(value.mode)
    || value.expectedOrigin !== "https://robbottx.com"
    || typeof value.expectedPath !== "string"
    || !value.expectedPath.startsWith("/")
    || value.expectedPath.includes("?")
    || value.expectedPath.includes("#")
  ) {
    throw new Error("invalid_input");
  }

  const hasUrl = typeof value.url === "string";
  const hasHtml = typeof value.html === "string";
  if (hasUrl === hasHtml) {
    throw new Error("invalid_source");
  }
  if (hasUrl) {
    const target = new URL(value.url);
    if (
      target.protocol !== "https:"
      || target.origin !== value.expectedOrigin
      || target.pathname !== value.expectedPath
      || target.username
      || target.password
      || target.port
      || target.hash
      || target.search.length < 2
    ) {
      throw new Error("invalid_live_url");
    }
  } else if (
    Buffer.byteLength(value.html, "utf8") > MAX_INPUT_BYTES
    || !value.html.trim()
  ) {
    throw new Error("invalid_fixture_html");
  }

  if (
    value.mode === "product"
    && (
      !Number.isInteger(value.productId)
      || value.productId < 1
      || value.productId > Number.MAX_SAFE_INTEGER
    )
  ) {
    throw new Error("invalid_product_id");
  }
  if (value.mode !== "product" && "productId" in value) {
    throw new Error("unexpected_product_id");
  }

  return {
    expectedOrigin: value.expectedOrigin,
    expectedPath: value.expectedPath,
    html: hasHtml ? value.html : null,
    mode: value.mode,
    productId: value.mode === "product" ? value.productId : null,
    source: hasUrl ? "live" : "fixture",
    url: hasUrl ? value.url : null,
  };
}

function failureResult(mode = "", source = "", code = "browser_error") {
  return {
    schemaVersion: SCHEMA_VERSION,
    operational: false,
    passed: false,
    mode: VALID_MODES.has(mode) ? mode : "",
    source: source === "live" || source === "fixture" ? source : "",
    routeUi: "",
    failureCodes: [code],
    navigation: {
      status: null,
      redirectStatus: null,
      finalOrigin: "",
      finalPath: "",
      redirectCount: 0,
    },
    stylesheets: {
      externalCount: 0,
      loadedCount: 0,
      failedCount: 0,
      blockedCount: 0,
    },
    dom: {},
  };
}

function withTimeout(promise, timeoutMs, code) {
  let timeout;
  return Promise.race([
    promise,
    new Promise((_, reject) => {
      timeout = setTimeout(() => reject(new Error(code)), timeoutMs);
    }),
  ]).finally(() => clearTimeout(timeout));
}

function withDeadline(promise, deadline, code) {
  const remaining = deadline - Date.now();
  if (remaining <= 0) {
    return Promise.reject(new Error(code));
  }
  return withTimeout(promise, remaining, code);
}

function pidIsAlive(pid) {
  if (!Number.isInteger(pid) || pid < 1) {
    return false;
  }
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function terminateOwnedProcessTrees(processIds, timeoutMs) {
  const pids = [...new Set(processIds)].filter(pidIsAlive);
  if (pids.length === 0 || timeoutMs <= 0) {
    return;
  }
  try {
    if (process.platform === "win32") {
      execFileSync(
        "taskkill.exe",
        [
          ...pids.flatMap((pid) => ["/PID", String(pid)]),
          "/T",
          "/F",
        ],
        {
          stdio: "ignore",
          timeout: timeoutMs,
          windowsHide: true,
        },
      );
    } else {
      for (const pid of pids) {
        process.kill(pid, "SIGKILL");
      }
    }
  } catch {
    // The process may have exited between the liveness check and termination.
  }
}

function ownedProfileProcessIds(profile, timeoutMs = CLOSE_TIMEOUT_MS) {
  try {
    let output;
    if (process.platform === "win32") {
      output = execFileSync(
        "powershell.exe",
        [
          "-NoLogo",
          "-NoProfile",
          "-NonInteractive",
          "-Command",
          (
            "Get-CimInstance Win32_Process | "
            + "Where-Object { $_.CommandLine -and "
            + "$_.CommandLine.ToLowerInvariant().Contains("
            + "$env:ROBBOTTX_OWNED_PROFILE.ToLowerInvariant()) } | "
            + "ForEach-Object { $_.ProcessId }"
          ),
        ],
        {
          encoding: "utf8",
          env: safeChildEnvironment({
            ROBBOTTX_OWNED_PROFILE: profile,
          }),
          stdio: ["ignore", "pipe", "ignore"],
          timeout: Math.max(1, timeoutMs),
          windowsHide: true,
        },
      );
    } else {
      output = execFileSync(
        "ps",
        ["-eo", "pid=,args="],
        {
          encoding: "utf8",
          stdio: ["ignore", "pipe", "ignore"],
          timeout: Math.max(1, timeoutMs),
        },
      )
        .split(/\r?\n/gu)
        .filter((line) => line.includes(profile))
        .map((line) => line.trim().split(/\s+/u)[0])
        .join("\n");
    }
    return new Set(
      output
        .split(/\r?\n/gu)
        .map((value) => Number(value.trim()))
        .filter((value) => (
          Number.isInteger(value)
          && value > 0
          && value !== process.pid
        )),
    );
  } catch {
    return null;
  }
}

async function waitForPidExit(pid, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (pidIsAlive(pid) && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  return !pidIsAlive(pid);
}

function ownedProfileRoot() {
  if (
    process.env.NODE_ENV === "test"
    && process.env.ROBBOTTX_COMMERCE_PROOF_PROFILE_ROOT
  ) {
    return path.resolve(
      process.env.ROBBOTTX_COMMERCE_PROOF_PROFILE_ROOT,
    );
  }
  return os.tmpdir();
}

function createOwnedProfile(requestedProfile = "") {
  if (requestedProfile) {
    return fs.realpathSync(requestedProfile);
  }
  const root = ownedProfileRoot();
  fs.mkdirSync(root, { recursive: true });
  const profile = fs.mkdtempSync(path.join(root, PROFILE_PREFIX));
  const resolvedRoot = fs.realpathSync(root);
  const resolvedProfile = fs.realpathSync(profile);
  const requiredPrefix = resolvedRoot.endsWith(path.sep)
    ? resolvedRoot
    : `${resolvedRoot}${path.sep}`;
  if (
    !resolvedProfile.startsWith(requiredPrefix)
    || path.basename(resolvedProfile).length <= PROFILE_PREFIX.length
    || !path.basename(resolvedProfile).startsWith(PROFILE_PREFIX)
  ) {
    throw new Error("unsafe_profile_path");
  }
  return resolvedProfile;
}

async function cleanup(browser, context, browserPid, profile) {
  const cleanupDeadline = Date.now() + CLEANUP_TIMEOUT_MS;
  const remaining = () => Math.max(0, cleanupDeadline - Date.now());
  let cleanupPassed = true;
  const capturedProcessIds = ownedProfileProcessIds(
    profile,
    Math.min(CLOSE_TIMEOUT_MS, remaining()),
  );
  if (capturedProcessIds === null) {
    cleanupPassed = false;
  }
  if (context !== null) {
    try {
      await withTimeout(
        context.close(),
        Math.max(1, Math.min(CLOSE_TIMEOUT_MS, remaining())),
        "context_close_timeout",
      );
    } catch {
      cleanupPassed = false;
    }
  }
  if (browser !== null) {
    try {
      await withTimeout(
        browser.close(),
        Math.max(1, Math.min(CLOSE_TIMEOUT_MS, remaining())),
        "browser_close_timeout",
      );
    } catch {
      cleanupPassed = false;
    }
  }
  terminateOwnedProcessTrees(
    [browserPid, ...(capturedProcessIds || [])],
    Math.max(1, Math.min(CLOSE_TIMEOUT_MS, remaining())),
  );
  if (!(await waitForPidExit(browserPid, remaining()))) {
    cleanupPassed = false;
  }
  const remainingProcessIds = ownedProfileProcessIds(
    profile,
    Math.min(CLOSE_TIMEOUT_MS, remaining()),
  );
  if (remainingProcessIds === null) {
    cleanupPassed = false;
  } else {
    terminateOwnedProcessTrees(
      remainingProcessIds,
      Math.max(1, Math.min(CLOSE_TIMEOUT_MS, remaining())),
    );
    const finalProcessIds = ownedProfileProcessIds(
      profile,
      Math.min(CLOSE_TIMEOUT_MS, remaining()),
    );
    if (finalProcessIds === null || finalProcessIds.size > 0) {
      cleanupPassed = false;
    }
  }
  try {
    fs.rmSync(profile, {
      force: true,
      maxRetries: 5,
      recursive: true,
      retryDelay: 100,
    });
  } catch {
    cleanupPassed = false;
  }
  if (fs.existsSync(profile)) {
    cleanupPassed = false;
  }
  return cleanupPassed;
}

function boundedCount(value) {
  return Number.isInteger(value) && value >= 0
    ? Math.min(value, 10_000)
    : 0;
}

function allowlistedResult(result) {
  const navigation = result.navigation ?? {};
  const stylesheets = result.stylesheets ?? {};
  const dom = result.dom ?? {};
  const allowedDomKeys = [
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
  ];
  const safeDom = {};
  for (const key of allowedDomKeys) {
    if (key in dom) {
      safeDom[key] = boundedCount(dom[key]);
    }
  }
  return {
    schemaVersion: SCHEMA_VERSION,
    operational: result.operational === true,
    passed: result.passed === true,
    mode: VALID_MODES.has(result.mode) ? result.mode : "",
    source: result.source === "live" || result.source === "fixture"
      ? result.source
      : "",
    routeUi: [
      "",
      "cart",
      "checkout",
      "empty_cart_redirect",
      "login_form",
      "product",
      "product_catalog",
      "reviewed_empty_state",
    ].includes(result.routeUi)
      ? result.routeUi
      : "",
    failureCodes: Array.isArray(result.failureCodes)
      ? [...new Set(
        result.failureCodes
          .filter((code) => typeof code === "string")
          .slice(0, 32),
      )]
      : ["invalid_result"],
    navigation: {
      status: Number.isInteger(navigation.status)
        ? navigation.status
        : null,
      redirectStatus: Number.isInteger(navigation.redirectStatus)
        ? navigation.redirectStatus
        : null,
      finalOrigin: navigation.finalOrigin === "https://robbottx.com"
        ? navigation.finalOrigin
        : "",
      finalPath: typeof navigation.finalPath === "string"
        && navigation.finalPath.startsWith("/")
        && !navigation.finalPath.includes("?")
        && !navigation.finalPath.includes("#")
        ? navigation.finalPath
        : "",
      redirectCount: boundedCount(navigation.redirectCount),
    },
    stylesheets: {
      externalCount: boundedCount(stylesheets.externalCount),
      loadedCount: boundedCount(stylesheets.loadedCount),
      failedCount: boundedCount(stylesheets.failedCount),
      blockedCount: boundedCount(stylesheets.blockedCount),
    },
    dom: safeDom,
  };
}

async function configurePage(page, input, requestState) {
  await page.setJavaScriptEnabled(false);
  await page.setCacheEnabled(false);
  await page.setBypassServiceWorker(true);
  await page.setViewport({ width: 1280, height: 900, deviceScaleFactor: 1 });
  await page.setUserAgent(
    "RobbottX-Commerce-Browser-Proof/1.0",
  );
  page.setDefaultNavigationTimeout(30_000);
  page.setDefaultTimeout(10_000);
  await page.setRequestInterception(true);

  page.on("request", (request) => {
    if (request.isInterceptResolutionHandled()) {
      return;
    }
    const requestUrl = request.url();
    const resourceType = request.resourceType();
    let allowed = false;
    let parsed = null;
    try {
      parsed = new URL(requestUrl);
    } catch {
      parsed = null;
    }

    const checkoutRedirectRequest = (
      input.source === "live"
      && input.mode === "checkout"
      && request.isNavigationRequest()
      && request.frame() === page.mainFrame()
      && resourceType === "document"
      && requestUrl === `${input.expectedOrigin}/cart/`
      && request.redirectChain().length === 1
      && request.redirectChain()[0].url() === input.url
      && request.redirectChain()[0].response()?.status() === 302
    );
    if (
      input.source === "live"
      && request.isNavigationRequest()
      && request.frame() === page.mainFrame()
      && resourceType === "document"
      && requestUrl === input.url
    ) {
      allowed = true;
    } else if (checkoutRedirectRequest) {
      allowed = true;
    } else if (
      input.source === "live"
      && ["font", "image", "stylesheet"].includes(resourceType)
      && parsed !== null
      && parsed.protocol === "https:"
      && parsed.origin === input.expectedOrigin
      && !parsed.username
      && !parsed.password
      && !parsed.port
      && !parsed.hash
    ) {
      allowed = true;
    }

    if (resourceType === "stylesheet") {
      requestState.stylesheetRequests.add(requestUrl);
      if (!allowed) {
        requestState.blockedStylesheets.add(requestUrl);
      }
    }
    if (allowed) {
      void request.continue();
    } else {
      void request.abort("blockedbyclient");
    }
  });

  page.on("requestfailed", (request) => {
    if (
      request.resourceType() === "stylesheet"
      && !requestState.blockedStylesheets.has(request.url())
    ) {
      requestState.failedStylesheets.add(request.url());
    }
  });
  page.on("response", (response) => {
    const request = response.request();
    if (request.resourceType() !== "stylesheet") {
      return;
    }
    const requestUrl = request.url();
    const contentType = response.headers()["content-type"] || "";
    const contentTypeParts = contentType
      .split(";")
      .map((part) => part.trim().toLowerCase());
    const charsetParts = contentTypeParts
      .slice(1)
      .filter((part) => part.startsWith("charset="))
      .map((part) => part.slice("charset=".length).replace(/^["']|["']$/gu, ""));
    const validContentType = (
      contentTypeParts[0] === "text/css"
      && charsetParts.length <= 1
      && (
        charsetParts.length === 0
        || ["ascii", "us-ascii", "utf-8", "utf8"].includes(charsetParts[0])
      )
    );
    if (
      response.status() === 200
      && response.url() === requestUrl
      && request.redirectChain().length === 0
      && validContentType
    ) {
      requestState.loadedStylesheets.add(requestUrl);
    } else {
      requestState.failedStylesheets.add(requestUrl);
    }
  });
}

async function inspectDom(page, input) {
  return page.evaluate(
    ({ expectedOrigin, expectedPath, mode, productId, renderedPath }) => {
      const semanticInputTypes = new Set([
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
      ]);

      const text = (element) => (
        (element?.innerText || element?.textContent || "")
          .replace(/\s+/gu, " ")
          .trim()
      );
      const handlerBlocks = (element, name) => {
        const handler = element.getAttribute(name) || "";
        return (
          /\breturn\s+(?:false|0|!1)\b/iu.test(handler)
          || /\.prevent\s*default\s*\(/iu.test(handler)
          || /\.return\s*value\s*=\s*(?:false|0|!1)\b/iu.test(
            handler.replace(/returnValue/giu, "return value"),
          )
        );
      };
      const resolveLength = (token, basis) => {
        const normalized = token.trim().toLowerCase();
        if (/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)%$/u.test(normalized)) {
          return Number.parseFloat(normalized) * basis / 100;
        }
        if (
          /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:px)?$/u.test(normalized)
        ) {
          return Number.parseFloat(normalized);
        }
        return null;
      };
      const insetClipRectangle = (style, rectangle) => {
        const match = /^inset\((.*)\)$/iu.exec(style.clipPath.trim());
        if (!match) {
          return null;
        }
        const insetPart = match[1].split(/\s+round\s+/iu)[0].trim();
        const tokens = insetPart.split(/\s+/u).filter(Boolean);
        if (tokens.length < 1 || tokens.length > 4) {
          return null;
        }
        const expanded = tokens.length === 1
          ? [tokens[0], tokens[0], tokens[0], tokens[0]]
          : tokens.length === 2
            ? [tokens[0], tokens[1], tokens[0], tokens[1]]
            : tokens.length === 3
              ? [tokens[0], tokens[1], tokens[2], tokens[1]]
              : tokens;
        const top = resolveLength(expanded[0], rectangle.height);
        const right = resolveLength(expanded[1], rectangle.width);
        const bottom = resolveLength(expanded[2], rectangle.height);
        const left = resolveLength(expanded[3], rectangle.width);
        if ([top, right, bottom, left].includes(null)) {
          return null;
        }
        return {
          bottom: rectangle.bottom - bottom,
          left: rectangle.left + left,
          right: rectangle.right - right,
          top: rectangle.top + top,
        };
      };
      const legacyClipRectangle = (style, rectangle) => {
        const match = /^rect\((.*)\)$/iu.exec(style.clip.trim());
        if (!match) {
          return null;
        }
        const tokens = match[1].split(/[\s,]+/u).filter(Boolean);
        if (tokens.length !== 4 || tokens.includes("auto")) {
          return null;
        }
        const values = tokens.map((token, index) => (
          resolveLength(
            token,
            index % 2 === 0 ? rectangle.height : rectangle.width,
          )
        ));
        if (values.includes(null)) {
          return null;
        }
        return {
          bottom: rectangle.top + values[2],
          left: rectangle.left + values[3],
          right: rectangle.left + values[1],
          top: rectangle.top + values[0],
        };
      };
      const intersectRectangle = (target, clipping) => {
        target.bottom = Math.min(target.bottom, clipping.bottom);
        target.left = Math.max(target.left, clipping.left);
        target.right = Math.min(target.right, clipping.right);
        target.top = Math.max(target.top, clipping.top);
      };
      const transformConceals = (value) => {
        if (!value || value === "none") {
          return false;
        }
        try {
          const matrix = new DOMMatrixReadOnly(value);
          const horizontalScale = Math.hypot(matrix.m11, matrix.m12);
          const verticalScale = Math.hypot(matrix.m21, matrix.m22);
          return (
            horizontalScale < 0.01
            || verticalScale < 0.01
            || Math.abs(matrix.m41)
              >= document.documentElement.clientWidth
            || Math.abs(matrix.m42)
              >= document.documentElement.clientHeight
          );
        } catch {
          return true;
        }
      };
      const animationCanConceal = (element) => {
        try {
          const rectangle = element.getBoundingClientRect();
          return element.getAnimations().some((animation) => {
            if (typeof animation.effect?.getKeyframes !== "function") {
              return true;
            }
            return animation.effect.getKeyframes().some((frame) => {
              if (
                String(frame.display || "").toLowerCase() === "none"
                || ["collapse", "hidden"].includes(
                  String(frame.visibility || "").toLowerCase(),
                )
                || String(frame.contentVisibility || "").toLowerCase()
                  === "hidden"
                || String(frame.pointerEvents || "").toLowerCase()
                  === "none"
                || (
                  "opacity" in frame
                  && Number.parseFloat(frame.opacity) <= 0.01
                )
                || (
                  "clipPath" in frame
                  && String(frame.clipPath).toLowerCase() !== "none"
                )
                || (
                  "clip" in frame
                  && String(frame.clip).toLowerCase() !== "auto"
                )
                || (
                  "maskImage" in frame
                  && String(frame.maskImage).toLowerCase() !== "none"
                )
                || (
                  "webkitMaskImage" in frame
                  && String(frame.webkitMaskImage).toLowerCase() !== "none"
                )
                || (
                  "transform" in frame
                  && transformConceals(String(frame.transform))
                )
                || (
                  "fontSize" in frame
                  && (
                    resolveLength(
                      String(frame.fontSize),
                      rectangle.height,
                    ) ?? 0
                  ) < 4
                )
                || (
                  "textIndent" in frame
                  && Math.abs(
                    resolveLength(
                      String(frame.textIndent),
                      rectangle.width,
                    ) ?? rectangle.width
                  ) >= rectangle.width
                )
                || (
                  "width" in frame
                  && (
                    resolveLength(String(frame.width), rectangle.width) ?? 0
                  ) < 4
                )
                || (
                  "height" in frame
                  && (
                    resolveLength(String(frame.height), rectangle.height) ?? 0
                  ) < 4
                )
                || (
                  "filter" in frame
                  && (
                    /opacity\(\s*(?:0+(?:\.0*)?|\.0+)%?\s*\)/iu
                      .test(String(frame.filter))
                    || /blur\(\s*(?:[1-9]\d{2,}|\d{4,})px\s*\)/iu
                      .test(String(frame.filter))
                  )
                )
              ) {
                return true;
              }
              for (const property of [
                "bottom",
                "left",
                "right",
                "top",
              ]) {
                if (!(property in frame)) {
                  continue;
                }
                const basis = ["left", "right"].includes(property)
                  ? document.documentElement.clientWidth
                  : document.documentElement.clientHeight;
                const offset = resolveLength(String(frame[property]), basis);
                if (offset === null || Math.abs(offset) >= basis) {
                  return true;
                }
              }
              if ("color" in frame || "webkitTextFillColor" in frame) {
                const foreground = parsedColor(
                  String(
                    frame.webkitTextFillColor
                    || frame.color
                    || getComputedStyle(element).color,
                  ),
                );
                const backgrounds = effectiveBackground(element);
                if (
                  foreground === null
                  || foreground.alpha <= 0.01
                  || backgrounds === null
                  || backgrounds.some((background) => (
                    contrastRatio(
                      compositeColor(foreground, background),
                      background,
                    ) < 3
                  ))
                ) {
                  return true;
                }
              }
              return false;
            });
          });
        } catch {
          return true;
        }
      };
      const safeHref = (
        rawValue,
        requiredPath,
        allowEmpty = false,
        requiredPrefix = "",
      ) => {
        if (document.querySelector("base[href],base[target]") !== null) {
          return false;
        }
        if (rawValue === null || rawValue.trim() === "") {
          return allowEmpty;
        }
        try {
          const parsed = new URL(rawValue, `${expectedOrigin}/`);
          return (
            parsed.protocol === "https:"
            && parsed.origin === expectedOrigin
            && !parsed.username
            && !parsed.password
            && !parsed.port
            && !parsed.hash
            && !parsed.search
            && (requiredPath === "" || parsed.pathname === requiredPath)
            && (
              requiredPrefix === ""
              || parsed.pathname.startsWith(requiredPrefix)
            )
          );
        } catch {
          return false;
        }
      };
      const concealedByStyle = (element) => {
        let cumulativeOpacity = 1;
        for (
          let current = element;
          current instanceof Element;
          current = current.parentElement
        ) {
          if (
            current.getAttributeNames().some(
              (name) => /^on/iu.test(name),
            )
          ) {
            return true;
          }
          if (
            current.hasAttribute("hidden")
            || current.hasAttribute("inert")
            || current.getAttribute("aria-hidden")?.trim().toLowerCase()
              === "true"
            || current.tagName === "TEMPLATE"
            || current.tagName === "DATALIST"
          ) {
            return true;
          }
          const style = getComputedStyle(current);
          const opacity = Number.parseFloat(style.opacity);
          cumulativeOpacity *= Number.isFinite(opacity) ? opacity : 0;
          for (const match of style.filter.matchAll(
            /opacity\(\s*([0-9]*\.?[0-9]+)(%)?\s*\)/giu,
          )) {
            const filterOpacity = Number.parseFloat(match[1])
              / (match[2] ? 100 : 1);
            cumulativeOpacity *= filterOpacity;
          }
          if (
            style.display === "none"
            || style.visibility === "hidden"
            || style.visibility === "collapse"
            || style.contentVisibility === "hidden"
            || cumulativeOpacity <= 0.010001
          ) {
            return true;
          }
          const compactClip = style.clip.replace(/\s+/gu, "");
          if (
            compactClip === "rect(0px,0px,0px,0px)"
            || compactClip === "rect(0px 0px 0px 0px)"
            || (
              style.clip
              && style.clip !== "auto"
              && legacyClipRectangle(
                style,
                current.getBoundingClientRect(),
              ) === null
            )
          ) {
            return true;
          }
          const compactClipPath = style.clipPath.replace(/\s+/gu, "");
          if (
            compactClipPath !== "none"
            && (
              !compactClipPath.startsWith("inset(")
              || insetClipRectangle(
                style,
                current.getBoundingClientRect(),
              ) === null
            )
          ) {
            return true;
          }
          const maskImages = [
            style.maskImage,
            style.webkitMaskImage,
          ].filter((value) => typeof value === "string" && value !== "");
          if (maskImages.some((value) => value.trim() !== "none")) {
            return true;
          }
          if (
            /(?:^|\s)opacity\(\s*(?:0+(?:\.0*)?|\.0+)%?\s*\)/iu
              .test(style.filter)
          ) {
            return true;
          }
          if (
            transformConceals(style.transform)
            || animationCanConceal(current)
          ) {
            return true;
          }
        }
        return false;
      };
      const visibleGeometry = (element, rectangle) => {
        const visible = {
          bottom: rectangle.bottom,
          left: rectangle.left,
          right: rectangle.right,
          top: rectangle.top,
        };
        let fixed = false;
        for (
          let current = element;
          current instanceof Element;
          current = current.parentElement
        ) {
          const style = getComputedStyle(current);
          const currentRectangle = current.getBoundingClientRect();
          fixed = fixed || style.position === "fixed";
          const insetClip = insetClipRectangle(style, currentRectangle);
          if (insetClip !== null) {
            intersectRectangle(visible, insetClip);
          }
          const legacyClip = legacyClipRectangle(style, currentRectangle);
          if (legacyClip !== null) {
            intersectRectangle(visible, legacyClip);
          }
          if (current !== element) {
            const overflowX = style.overflowX.toLowerCase();
            const overflowY = style.overflowY.toLowerCase();
            if (["auto", "clip", "hidden", "scroll"].includes(overflowX)) {
              visible.left = Math.max(visible.left, currentRectangle.left);
              visible.right = Math.min(visible.right, currentRectangle.right);
            }
            if (["auto", "clip", "hidden", "scroll"].includes(overflowY)) {
              if (
                ["BODY", "HTML"].includes(current.tagName)
                && ["auto", "scroll"].includes(overflowY)
              ) {
                continue;
              }
              visible.top = Math.max(visible.top, currentRectangle.top);
              visible.bottom = Math.min(
                visible.bottom,
                currentRectangle.bottom,
              );
            }
          }
        }
        visible.left = Math.max(visible.left, 0);
        visible.right = Math.min(
          visible.right,
          document.documentElement.clientWidth,
        );
        visible.top = Math.max(visible.top, 0);
        if (fixed) {
          visible.bottom = Math.min(
            visible.bottom,
            document.documentElement.clientHeight,
          );
        }
        return {
          bottom: visible.bottom,
          height: visible.bottom - visible.top,
          left: visible.left,
          right: visible.right,
          top: visible.top,
          width: visible.right - visible.left,
        };
      };
      const hitTested = (element, geometry, textOwner = null) => {
        const viewportBottom = document.documentElement.clientHeight;
        const viewportRight = document.documentElement.clientWidth;
        const sample = (candidate) => {
          const left = Math.max(candidate.left, 0);
          const right = Math.min(candidate.right, viewportRight);
          const top = Math.max(candidate.top, 0);
          const bottom = Math.min(candidate.bottom, viewportBottom);
          if (right <= left || bottom <= top) {
            return false;
          }
          if (
            transparentPaintedOverlayCovers(
              element,
              { bottom, left, right, top },
            )
          ) {
            return false;
          }
          const insetX = Math.min(2, (right - left) / 4);
          const insetY = Math.min(2, (bottom - top) / 4);
          const horizontal = [
            left + insetX,
            (left + right) / 2,
            right - insetX,
          ];
          const vertical = [
            top + insetY,
            (top + bottom) / 2,
            bottom - insetY,
          ];
          return vertical.some((y) => horizontal.some((x) => {
            const topmost = document.elementsFromPoint(x, y)[0];
            return (
              topmost instanceof Element
              && (
                textOwner instanceof Element
                  ? (
                    topmost === textOwner
                    || topmost.contains(textOwner)
                  )
                  : (
                    topmost === element
                    || element.contains(topmost)
                  )
              )
            );
          }));
        };
        if (geometry.top < viewportBottom) {
          return sample(geometry);
        }
        const scrollState = [];
        for (
          let current = element.parentElement;
          current instanceof HTMLElement;
          current = current.parentElement
        ) {
          scrollState.push({
            element: current,
            left: current.scrollLeft,
            top: current.scrollTop,
          });
        }
        const scrollX = window.scrollX;
        const scrollY = window.scrollY;
        try {
          element.scrollIntoView({
            behavior: "instant",
            block: "center",
            inline: "nearest",
          });
          const rectangle = element.getBoundingClientRect();
          return sample(visibleGeometry(element, rectangle));
        } catch {
          return false;
        } finally {
          for (const state of scrollState.reverse()) {
            state.element.scrollLeft = state.left;
            state.element.scrollTop = state.top;
          }
          window.scrollTo(scrollX, scrollY);
        }
      };
      const parsedColor = (value) => {
        const normalized = String(value || "")
          .replace(/\s+/gu, "")
          .toLowerCase();
        if (!normalized || normalized === "transparent") {
          return { alpha: 0, blue: 0, green: 0, red: 0 };
        }
        const rgba = /^rgba?\((.*)\)$/u.exec(normalized);
        if (rgba) {
          const parts = rgba[1].split(/[,/]/u);
          if (parts.length >= 3) {
            const channels = parts.slice(0, 3).map((part) => (
              part.endsWith("%")
                ? Number.parseFloat(part) * 2.55
                : Number.parseFloat(part)
            ));
            const alpha = parts.length >= 4
              ? Number.parseFloat(parts[parts.length - 1])
              : 1;
            if (
              channels.every(Number.isFinite)
              && Number.isFinite(alpha)
            ) {
              return {
                alpha,
                blue: channels[2],
                green: channels[1],
                red: channels[0],
              };
            }
          }
        }
        return null;
      };
      const compositeColor = (foreground, background) => {
        const alpha = foreground.alpha
          + background.alpha * (1 - foreground.alpha);
        if (alpha <= 0) {
          return { alpha: 0, blue: 0, green: 0, red: 0 };
        }
        return {
          alpha,
          blue: (
            foreground.blue * foreground.alpha
            + background.blue * background.alpha
              * (1 - foreground.alpha)
          ) / alpha,
          green: (
            foreground.green * foreground.alpha
            + background.green * background.alpha
              * (1 - foreground.alpha)
          ) / alpha,
          red: (
            foreground.red * foreground.alpha
            + background.red * background.alpha
              * (1 - foreground.alpha)
          ) / alpha,
        };
      };
      const effectiveBackground = (element) => {
        let color = { alpha: 0, blue: 0, green: 0, red: 0 };
        for (
          let current = element;
          current instanceof Element;
          current = current.parentElement
        ) {
          const style = getComputedStyle(current);
          if (style.backgroundImage !== "none") {
            if (!/^linear-gradient\(/iu.test(style.backgroundImage)) {
              return null;
            }
            const gradientColors = [
              ...style.backgroundImage.matchAll(/rgba?\([^)]*\)/giu),
            ].map((match) => parsedColor(match[0]));
            if (
              gradientColors.length < 2
              || gradientColors.some(
                (candidate) => candidate === null || candidate.alpha < 0.999,
              )
            ) {
              return null;
            }
            return gradientColors;
          }
          const layer = parsedColor(style.backgroundColor);
          if (layer === null) {
            return null;
          }
          color = compositeColor(color, layer);
          if (color.alpha >= 0.999) {
            return [color];
          }
        }
        return [
          compositeColor(
            color,
            { alpha: 1, blue: 255, green: 255, red: 255 },
          ),
        ];
      };
      const luminance = (color) => {
        const channel = (value) => {
          const normalized = value / 255;
          return normalized <= 0.04045
            ? normalized / 12.92
            : ((normalized + 0.055) / 1.055) ** 2.4;
        };
        return (
          0.2126 * channel(color.red)
          + 0.7152 * channel(color.green)
          + 0.0722 * channel(color.blue)
        );
      };
      const contrastRatio = (first, second) => {
        const firstLuminance = luminance(first);
        const secondLuminance = luminance(second);
        return (
          (Math.max(firstLuminance, secondLuminance) + 0.05)
          / (Math.min(firstLuminance, secondLuminance) + 0.05)
        );
      };
      const pseudoOccludes = (element) => (
        ["::before", "::after"].some((pseudo) => {
          const style = getComputedStyle(element, pseudo);
          if (
            ["none", "normal"].includes(style.content)
            || style.display === "none"
            || Number.parseFloat(style.opacity) <= 0
            || !["absolute", "fixed"].includes(style.position)
            || Number.parseInt(style.zIndex || "0", 10) < 0
          ) {
            return false;
          }
          const background = parsedColor(style.backgroundColor);
          const rectangle = element.getBoundingClientRect();
          const pseudoWidth = resolveLength(style.width, rectangle.width);
          const pseudoHeight = resolveLength(style.height, rectangle.height);
          const coversByInset = [
            style.bottom,
            style.left,
            style.right,
            style.top,
          ].every((value) => resolveLength(value, 1) === 0);
          const coversBySize = (
            pseudoWidth !== null
            && pseudoHeight !== null
            && pseudoWidth >= rectangle.width * 0.8
            && pseudoHeight >= rectangle.height * 0.8
          );
          return (
            (coversByInset || coversBySize)
            && (
              style.backgroundImage !== "none"
              || (background !== null && background.alpha >= 0.9)
            )
          );
        })
      );
      const overlapRatio = (target, candidate) => {
        const width = Math.max(
          0,
          Math.min(target.right, candidate.right)
            - Math.max(target.left, candidate.left),
        );
        const height = Math.max(
          0,
          Math.min(target.bottom, candidate.bottom)
            - Math.max(target.top, candidate.top),
        );
        const targetArea = Math.max(
          1,
          (target.right - target.left) * (target.bottom - target.top),
        );
        return width * height / targetArea;
      };
      const visuallyOpaqueLayer = (style) => {
        const opacity = Number.parseFloat(style.opacity);
        if (
          style.display === "none"
          || ["collapse", "hidden"].includes(style.visibility)
          || !Number.isFinite(opacity)
          || opacity <= 0.01
        ) {
          return false;
        }
        const background = parsedColor(style.backgroundColor);
        return (
          style.backgroundImage !== "none"
          || (
            background !== null
            && background.alpha * opacity >= 0.5
          )
        );
      };
      const pseudoRectangle = (owner, style) => {
        const ownerRectangle = owner.getBoundingClientRect();
        const viewport = {
          bottom: document.documentElement.clientHeight,
          height: document.documentElement.clientHeight,
          left: 0,
          right: document.documentElement.clientWidth,
          top: 0,
          width: document.documentElement.clientWidth,
        };
        const base = style.position === "fixed" ? viewport : ownerRectangle;
        const insets = {
          bottom: resolveLength(style.bottom, base.height),
          left: resolveLength(style.left, base.width),
          right: resolveLength(style.right, base.width),
          top: resolveLength(style.top, base.height),
        };
        if (
          Object.values(insets).every((value) => value === 0)
        ) {
          return {
            bottom: base.bottom,
            left: base.left,
            right: base.right,
            top: base.top,
          };
        }
        const width = resolveLength(style.width, base.width);
        const height = resolveLength(style.height, base.height);
        if (
          width === null
          || height === null
          || width <= 0
          || height <= 0
        ) {
          return null;
        }
        const left = insets.left !== null
          ? base.left + insets.left
          : insets.right !== null
            ? base.right - insets.right - width
            : base.left;
        const top = insets.top !== null
          ? base.top + insets.top
          : insets.bottom !== null
            ? base.bottom - insets.bottom - height
            : base.top;
        return {
          bottom: top + height,
          left,
          right: left + width,
          top,
        };
      };
      const transparentPaintedOverlayCovers = (element, geometry) => {
        for (const candidate of document.querySelectorAll("*")) {
          const style = getComputedStyle(candidate);
          const zIndex = Number.parseInt(style.zIndex, 10);
          if (
            candidate !== element
            && !candidate.contains(element)
            && style.pointerEvents === "none"
            && ["absolute", "fixed", "sticky"].includes(style.position)
            && (!Number.isFinite(zIndex) || zIndex >= 0)
            && visuallyOpaqueLayer(style)
            && overlapRatio(geometry, candidate.getBoundingClientRect()) >= 0.8
          ) {
            return true;
          }
          for (const pseudo of ["::before", "::after"]) {
            const pseudoStyle = getComputedStyle(candidate, pseudo);
            const pseudoZIndex = Number.parseInt(pseudoStyle.zIndex, 10);
            if (
              !["none", "normal"].includes(pseudoStyle.content)
              && ["absolute", "fixed"].includes(pseudoStyle.position)
              && (!Number.isFinite(pseudoZIndex) || pseudoZIndex >= 0)
              && visuallyOpaqueLayer(pseudoStyle)
            ) {
              const rectangle = pseudoRectangle(candidate, pseudoStyle);
              if (
                rectangle !== null
                && overlapRatio(geometry, rectangle) >= 0.8
              ) {
                return true;
              }
            }
          }
        }
        return false;
      };
      const paintedColor = (value) => {
        const color = parsedColor(value);
        return color !== null && color.alpha > 0.01;
      };
      const textPainted = (element) => {
        const style = getComputedStyle(element);
        const foreground = parsedColor(
          style.webkitTextFillColor || style.color,
        );
        const backgrounds = effectiveBackground(element);
        return (
          paintedColor(style.color)
          && paintedColor(style.webkitTextFillColor || style.color)
          && Number.parseFloat(style.fontSize) >= 4
          && foreground !== null
          && backgrounds !== null
          && backgrounds.every((background) => (
            contrastRatio(
              compositeColor(foreground, background),
              background,
            ) >= 3
          ))
          && !pseudoOccludes(element)
        );
      };
      const meaningfulTextVisible = (element) => {
        if (
          !(element instanceof HTMLElement)
          || concealedByStyle(element)
        ) {
          return false;
        }
        const walker = document.createTreeWalker(
          element,
          NodeFilter.SHOW_TEXT,
        );
        for (
          let node = walker.nextNode();
          node !== null;
          node = walker.nextNode()
        ) {
          if (!/[\p{L}\p{N}]/u.test(node.nodeValue || "")) {
            continue;
          }
          const parent = node.parentElement;
          if (
            !(parent instanceof HTMLElement)
            || concealedByStyle(parent)
            || !textPainted(parent)
          ) {
            continue;
          }
          const range = document.createRange();
          range.selectNodeContents(node);
          const elementGeometry = visibleGeometry(
            element,
            element.getBoundingClientRect(),
          );
          const ranges = [...range.getClientRects()];
          if (ranges.some((rectangle) => {
            const geometry = {
              bottom: Math.min(rectangle.bottom, elementGeometry.bottom),
              left: Math.max(rectangle.left, elementGeometry.left),
              right: Math.min(rectangle.right, elementGeometry.right),
              top: Math.max(rectangle.top, elementGeometry.top),
            };
            geometry.height = geometry.bottom - geometry.top;
            geometry.width = geometry.right - geometry.left;
            return (
              geometry.width >= 1
              && geometry.height >= 4
              && hitTested(element, geometry, parent)
            );
          })) {
            return true;
          }
        }
        return false;
      };
      const rendered = (element, actionable = false) => {
        if (
          !(element instanceof HTMLElement)
          || !element.isConnected
          || concealedByStyle(element)
        ) {
          return false;
        }
        if (
          typeof element.checkVisibility === "function"
          && !element.checkVisibility({
            checkOpacity: true,
            checkVisibilityCSS: true,
          })
        ) {
          return false;
        }
        const rectangle = element.getBoundingClientRect();
        const geometry = visibleGeometry(element, rectangle);
        const minimumDimension = actionable ? 8 : 4;
        if (
          !Number.isFinite(rectangle.width)
          || !Number.isFinite(rectangle.height)
          || rectangle.width <= 0.5
          || rectangle.height <= 0.5
          || rectangle.right <= 0
          || rectangle.left >= document.documentElement.clientWidth
          || rectangle.bottom <= 0
          || geometry.width < minimumDimension
          || geometry.height < minimumDimension
        ) {
          return false;
        }
        if (!hitTested(element, geometry)) {
          return false;
        }
        if (actionable) {
          for (
            let current = element;
            current instanceof Element;
            current = current.parentElement
          ) {
            if (getComputedStyle(current).pointerEvents === "none") {
              return false;
            }
          }
        }
        return true;
      };
      const enabled = (control) => (
        !control.matches(":disabled")
        && control.getAttribute("aria-disabled")?.trim().toLowerCase()
          !== "true"
      );
      const isSubmit = (control) => (
        (
          control instanceof HTMLButtonElement
          && ["", "submit"].includes(
            (control.getAttribute("type") || "submit").trim().toLowerCase(),
          )
        )
        || (
          control instanceof HTMLInputElement
          && ["image", "submit"].includes(control.type.toLowerCase())
        )
      );
      const ownedControls = (form) => (
        [...form.querySelectorAll("button,input")]
          .filter((control) => control.form === form && form.contains(control))
      );
      const submitControls = (form) => (
        ownedControls(form).filter(
          (control) => (
            enabled(control)
            && isSubmit(control)
            && rendered(control, true)
            && !handlerBlocks(control, "onclick")
          ),
        )
      );
      const visibleControlLabel = (control) => {
        if (control instanceof HTMLButtonElement) {
          return meaningfulTextVisible(control) ? text(control) : "";
        }
        if (!(control instanceof HTMLInputElement) || !textPainted(control)) {
          return "";
        }
        const style = getComputedStyle(control);
        const textIndent = resolveLength(
          style.textIndent,
          control.getBoundingClientRect().width,
        );
        if (
          textIndent === null
          || Math.abs(textIndent) > 1
          || Number.parseFloat(style.lineHeight) === 0
        ) {
          return "";
        }
        const type = control.type.toLowerCase();
        const nativeLabel = type === "image"
          ? control.getAttribute("alt") || ""
          : control.value;
        if (/[\p{L}\p{N}]/u.test(nativeLabel)) {
          return nativeLabel.trim();
        }
        const labelledBy = (
          control.getAttribute("aria-labelledby") || ""
        ).trim().split(/\s+/u).filter(Boolean);
        const labels = labelledBy
          .map((id) => document.getElementById(id))
          .filter((label) => (
            label instanceof HTMLElement
            && meaningfulTextVisible(label)
          ));
        return labels.map((label) => text(label)).join(" ").trim();
      };
      const fieldVisiblyUsable = (control) => {
        if (
          !(control instanceof HTMLInputElement)
          || !textPainted(control)
        ) {
          return false;
        }
        const style = getComputedStyle(control);
        const surroundingBackgrounds = effectiveBackground(
          control.parentElement || document.body,
        );
        const fieldBackgrounds = effectiveBackground(control);
        const contrastsWith = (foreground, backgrounds, threshold) => (
          foreground !== null
          && backgrounds !== null
          && backgrounds.every((background) => (
            contrastRatio(
              compositeColor(foreground, background),
              background,
            ) >= threshold
          ))
        );
        const borderVisible = [
          ["borderTopWidth", "borderTopStyle", "borderTopColor"],
          ["borderRightWidth", "borderRightStyle", "borderRightColor"],
          ["borderBottomWidth", "borderBottomStyle", "borderBottomColor"],
          ["borderLeftWidth", "borderLeftStyle", "borderLeftColor"],
        ].some(([widthName, styleName, colorName]) => (
          Number.parseFloat(style[widthName]) >= 1
          && !["hidden", "none"].includes(style[styleName])
          && contrastsWith(
            parsedColor(style[colorName]),
            surroundingBackgrounds,
            3,
          )
        ));
        const backgroundVisible = (
          fieldBackgrounds !== null
          && surroundingBackgrounds !== null
          && fieldBackgrounds.every((fieldBackground) => (
            surroundingBackgrounds.every((surroundingBackground) => (
              contrastRatio(fieldBackground, surroundingBackground) >= 1.5
            ))
          ))
        );
        const placeholder = control.getAttribute("placeholder") || "";
        const placeholderStyle = getComputedStyle(control, "::placeholder");
        const placeholderColor = parsedColor(placeholderStyle.color);
        const placeholderVisible = (
          /[\p{L}\p{N}]/u.test(placeholder)
          && Number.parseFloat(placeholderStyle.opacity) > 0.01
          && Number.parseFloat(placeholderStyle.fontSize) >= 4
          && placeholderColor !== null
          && placeholderColor.alpha > 0.01
          && fieldBackgrounds !== null
          && fieldBackgrounds.every((background) => (
            contrastRatio(
              compositeColor(placeholderColor, background),
              background,
            ) >= 3
          ))
        );
        const type = control.type.toLowerCase();
        const valueVisible = (
          !["checkbox", "hidden", "radio", "range"].includes(type)
          && /[\p{L}\p{N}]/u.test(control.value)
        );
        return (
          borderVisible
          || backgroundVisible
          || placeholderVisible
          || valueVisible
        );
      };
      const routeSubmitControls = (form, route) => {
        const patterns = {
          account: /\b(?:log in|login|sign in)\b/iu,
          cart: /\b(?:checkout|proceed|update cart)\b/iu,
          checkout: /\b(?:complete purchase|pay|place order|submit order)\b/iu,
          product: /\b(?:add to cart|buy|order|purchase)\b/iu,
        };
        return submitControls(form).filter((control) => {
          const label = visibleControlLabel(control);
          if (!patterns[route].test(label)) {
            return false;
          }
          if (route === "account") {
            return control.name === "login";
          }
          if (route === "cart") {
            const blockCart = control.closest(".wc-block-cart");
            return (
              control.name === "update_cart"
              || (
                blockCart instanceof HTMLElement
                && control.classList.contains(
                  "wc-block-components-button",
                )
              )
            );
          }
          if (route === "checkout") {
            const blockCheckout = control.closest(".wc-block-checkout");
            return (
              (
                control.id === "place_order"
                && control.name === "woocommerce_checkout_place_order"
              )
              || (
                blockCheckout instanceof HTMLElement
                && control.classList.contains(
                  "wc-block-components-checkout-place-order-button",
                )
              )
            );
          }
          return true;
        });
      };
      const routeDataInputs = (controls, route) => (
        visibleDataInputs(controls).filter((control) => {
          const name = control.name.trim().toLowerCase();
          if (route === "cart") {
            return (
              (
                /^cart\[[^\]]+\]\[qty\]$/u.test(name)
                && control.closest(".cart_item") instanceof HTMLElement
              )
              || (
                (
                  ["quantity", "qty"].includes(name)
                  || control.classList.contains("qty")
                )
                && control.closest(".wc-block-cart-item")
                  instanceof HTMLElement
              )
            );
          }
          return (
            [
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
            ].includes(name)
            || [
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
            ].includes(control.autocomplete.toLowerCase())
          );
        })
      );
      const checkoutDataIsCoherent = (controls, blockCheckout) => {
        const candidates = routeDataInputs(controls, "checkout");
        const names = new Set(
          candidates.map((control) => control.name.trim().toLowerCase()),
        );
        const autocompleteTokens = candidates.map((control) => new Set(
          control.autocomplete.toLowerCase().split(/\s+/u).filter(Boolean),
        ));
        const hasAutocomplete = (scope, field) => (
          autocompleteTokens.some((tokens) => (
            tokens.has(field)
            && (
              tokens.has(scope)
              || (
                blockCheckout
                && ["billing", "shipping"].some(
                  (candidateScope) => tokens.has(candidateScope),
                )
              )
            )
          ))
        );
        const hasNamed = (classicName, blockAlternates = []) => (
          names.has(classicName)
          || (
            blockCheckout
            && blockAlternates.some((candidate) => names.has(candidate))
          )
        );
        return (
          (
            hasNamed(
              "billing_first_name",
              ["shipping_first_name"],
            )
            || hasAutocomplete("billing", "given-name")
          )
          && (
            hasNamed(
              "billing_last_name",
              ["shipping_last_name"],
            )
            || hasAutocomplete("billing", "family-name")
          )
          && (
            hasNamed(
              "billing_address_1",
              ["shipping_address_1"],
            )
            || hasAutocomplete("billing", "address-line1")
          )
          && (
            hasNamed("billing_city", ["shipping_city"])
            || hasAutocomplete("billing", "address-level2")
          )
          && (
            hasNamed(
              "billing_postcode",
              ["shipping_postcode"],
            )
            || hasAutocomplete("billing", "postal-code")
          )
          && (
            hasNamed("billing_email", ["email", "shipping_email"])
            || hasAutocomplete("billing", "email")
          )
        );
      };
      const visibleDataInputs = (controls) => (
        controls.filter(
          (control) => (
            control instanceof HTMLInputElement
            && semanticInputTypes.has(control.type.toLowerCase())
            && enabled(control)
            && !control.readOnly
            && control.getAttribute("aria-readonly")
              ?.trim().toLowerCase() !== "true"
            && rendered(control, true)
            && fieldVisiblyUsable(control)
          ),
        )
      );
      const formIsSafe = (form, path, allowEmpty = false) => (
        form.method.toLowerCase() === "post"
        && safeHref(form.getAttribute("action"), path, allowEmpty)
        && [
          "application/x-www-form-urlencoded",
          "multipart/form-data",
        ].includes(form.enctype.toLowerCase())
        && ["", "_self"].includes(
          (form.getAttribute("target") || "").trim().toLowerCase(),
        )
        && !handlerBlocks(form, "onsubmit")
      );
      const submitterIsSafe = (
        control,
        form,
        path,
        allowEmpty = false,
      ) => {
        const formAction = control.getAttribute("formaction");
        const formMethod = (
          control.getAttribute("formmethod") || form.method
        ).trim().toLowerCase();
        const formEnctype = (
          control.getAttribute("formenctype") || form.enctype
        ).trim().toLowerCase();
        const formTarget = (
          control.getAttribute("formtarget")
          || form.getAttribute("target")
          || ""
        ).trim().toLowerCase();
        return (
          formMethod === "post"
          && [
            "application/x-www-form-urlencoded",
            "multipart/form-data",
          ].includes(formEnctype)
          && ["", "_self"].includes(formTarget)
          && (
            formAction === null
            || safeHref(formAction, path, allowEmpty)
          )
        );
      };
      const ownedNonce = (form, name) => (
        ownedControls(form).filter((control) => (
          control instanceof HTMLInputElement
          && control.type.toLowerCase() === "hidden"
          && control.name === name
          && enabled(control)
          && /^[A-Za-z0-9]{10}$/u.test(control.value.trim())
        )).length === 1
      );
      const visibleMatches = (selector) => (
        [...document.querySelectorAll(selector)].filter(
          (element) => rendered(element),
        )
      );
      const result = {
        passed: false,
        routeUi: "",
        failureCodes: [],
        dom: {},
      };

      if (mode === "product") {
        const productContainers = visibleMatches(
          "article.product,div.product,section.product",
        );
        const cartForms = [...document.querySelectorAll("form.cart")]
          .filter((form) => form.isConnected && !concealedByStyle(form));
        const actionForms = cartForms.filter(
          (form) => submitControls(form).length > 0,
        );
        const surfaceContexts = [];
        const actionContexts = [];

        for (const form of actionForms) {
          const summary = form.closest(".summary");
          const product = form.closest(".product");
          if (
            !(summary instanceof HTMLElement)
            || !(product instanceof HTMLElement)
            || !productContainers.includes(product)
            || summary.closest(".product") !== product
            || form.closest(".summary") !== summary
          ) {
            continue;
          }
          const summaries = [...product.querySelectorAll(".summary")]
            .filter(
              (candidate) => (
                candidate.closest(".product") === product
                && rendered(candidate)
              ),
            );
          const titles = [...summary.querySelectorAll("h1.product_title")]
            .filter(
              (candidate) => (
                candidate.closest(".summary") === summary
                && candidate.closest(".product") === product
                && rendered(candidate)
                && meaningfulTextVisible(candidate)
              ),
            );
          const stockElements = [...summary.querySelectorAll(".stock")]
            .filter((candidate) => (
              candidate.closest(".summary") === summary
              && candidate.closest(".product") === product
              && rendered(candidate)
            ));
          const stockStates = stockElements.filter((candidate) => {
              const classes = new Set(
                [...candidate.classList].map((value) => value.toLowerCase()),
              );
              const stockStatus = (
                candidate.getAttribute("data-stock-status") || ""
              ).trim().toLowerCase();
              const stockText = text(candidate);
              const normalizedStockText = stockText.toLowerCase();
              const negativeStockState = (
                classes.has("out-of-stock")
                || classes.has("outofstock")
                || classes.has("unavailable")
                || [
                  "out-of-stock",
                  "outofstock",
                  "unavailable",
                ].includes(stockStatus)
              );
              return (
                (
                  classes.has("in-stock")
                  || classes.has("available-on-backorder")
                  || [
                    "available-on-backorder",
                    "in-stock",
                    "instock",
                    "onbackorder",
                  ].includes(stockStatus)
                )
                && !negativeStockState
                && meaningfulTextVisible(candidate)
                && !["availability", "status", "stock"].includes(
                  normalizedStockText,
                )
                && !(
                  /\b(?:out of stock|sold out|unavailable|not available|not in stock|discontinued|no longer available|cannot be purchased)\b/iu
                    .test(normalizedStockText)
                )
              );
            });
          const offerEvidenceElements = [
            ...summary.querySelectorAll(".rbtx-offer-evidence"),
          ].filter((candidate) => (
            candidate.closest(".summary") === summary
            && candidate.closest(".product") === product
            && rendered(candidate)
          ));
          const validOfferEvidence = offerEvidenceElements.filter(
            (candidate) => {
              const supplier = (
                candidate.getAttribute("data-supplier") || ""
              ).trim();
              const region = (
                candidate.getAttribute("data-region") || ""
              ).trim();
              const quantityBasis = (
                candidate.getAttribute("data-quantity-basis") || ""
              ).trim();
              const checkedAt = (
                candidate.getAttribute("data-checked-at") || ""
              ).trim();
              const offerHash = (
                candidate.getAttribute("data-offer-hash") || ""
              ).trim();
              const visible = text(candidate).toLowerCase();
              const parsedCheckedAt = Date.parse(checkedAt);
              const currentTime = Date.now();
              return (
                supplier.length >= 2
                && supplier.length <= 120
                && !/[\u0000-\u001f\u007f]/u.test(supplier)
                && /^[A-Z]{2}$/u.test(region)
                && /^[1-9][0-9]{0,8} (?:unit|units)$/u.test(quantityBasis)
                && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/u.test(
                  checkedAt,
                )
                && Number.isFinite(parsedCheckedAt)
                && parsedCheckedAt >= currentTime - (24 * 60 * 60 * 1000)
                && parsedCheckedAt <= currentTime + (5 * 60 * 1000)
                && /^[0-9a-f]{64}$/u.test(offerHash)
                && meaningfulTextVisible(candidate)
                && visible.includes(supplier.toLowerCase())
                && visible.includes(region.toLowerCase())
                && visible.includes(quantityBasis.toLowerCase())
                && visible.includes(checkedAt.toLowerCase())
              );
            },
          );
          if (titles.length === 0) {
            continue;
          }
          const controls = ownedControls(form);
          const submits = routeSubmitControls(form, "product");
          const identifiers = controls.filter((control) => (
            ["add-to-cart", "product_id"].includes(control.name)
            && (
              enabled(control)
              || control.hasAttribute("disabled")
              || control.getAttribute("aria-disabled")
                ?.trim().toLowerCase() === "true"
            )
          ));
          const identifiersValid = (
            identifiers.length > 0
            && identifiers.every((control) => (
              enabled(control)
              && control.value.trim() === String(productId)
              && (
                (
                  control instanceof HTMLInputElement
                  && control.type.toLowerCase() === "hidden"
                )
                || (
                  submits.includes(control)
                  && (
                    control instanceof HTMLButtonElement
                    || (
                      control instanceof HTMLInputElement
                      && control.type.toLowerCase() === "submit"
                    )
                  )
                )
              )
            ))
          );
          const addToCartControls = identifiers.filter((control) => (
            control.name === "add-to-cart"
            && control.value.trim() === String(productId)
            && (
              (
                control instanceof HTMLInputElement
                && control.type.toLowerCase() === "hidden"
              )
              || (
                submits.includes(control)
                && (
                  control instanceof HTMLButtonElement
                  || (
                    control instanceof HTMLInputElement
                    && control.type.toLowerCase() === "submit"
                  )
                )
              )
            )
          ));
          const context = {
            addToCartCount: addToCartControls.length,
            identifierCount: identifiers.length,
            offerEvidenceCount: offerEvidenceElements.length,
            positiveStockCount: stockStates.length,
            stockCount: stockElements.length,
            submitCount: submits.length,
            summaryCount: summaries.length,
            titleCount: titles.length,
            validOfferEvidenceCount: validOfferEvidence.length,
          };
          surfaceContexts.push(context);
          if (
            summaries.length === 1
            && titles.length === 1
            && stockElements.length === 1
            && stockStates.length === 1
            && offerEvidenceElements.length === 1
            && validOfferEvidence.length === 1
            && formIsSafe(form, expectedPath, true)
            && submits.length === 1
            && submits.every((control) => (
              submitterIsSafe(
                control,
                form,
                expectedPath,
                true,
              )
            ))
            && identifiersValid
            && addToCartControls.length > 0
          ) {
            actionContexts.push(context);
          }
        }
        const primarySurface = (
          surfaceContexts.length === 1
          && surfaceContexts[0].summaryCount === 1
          && surfaceContexts[0].titleCount === 1
          && surfaceContexts[0].stockCount === 1
          && surfaceContexts[0].positiveStockCount === 1
          && surfaceContexts[0].offerEvidenceCount === 1
          && surfaceContexts[0].validOfferEvidenceCount === 1
        );
        const primaryAction = (
          primarySurface
          && actionForms.length === 1
          && actionContexts.length === 1
        );
        const context = surfaceContexts[0] || {};
        result.passed = primarySurface && primaryAction;
        result.routeUi = result.passed ? "product" : "";
        result.dom = {
          actionFormCount: actionForms.length,
          addToCartCount: context.addToCartCount || 0,
          identifierCount: context.identifierCount || 0,
          offerEvidenceCount: context.offerEvidenceCount || 0,
          positiveStockCount: context.positiveStockCount || 0,
          primaryActionCount: actionContexts.length,
          primarySurfaceCount: surfaceContexts.length,
          productCardCount: productContainers.length,
          stockCount: context.stockCount || 0,
          submitCount: context.submitCount || 0,
          titleCount: context.titleCount || 0,
          validOfferEvidenceCount: context.validOfferEvidenceCount || 0,
        };
        if (!primarySurface) {
          result.failureCodes.push("product_surface");
        }
        if (!primaryAction) {
          result.failureCodes.push("product_action");
        }
        return result;
      }

      if (mode === "shop") {
        const productCards = visibleMatches(
          ".products .product,"
          + ".wc-block-grid__products .wc-block-grid__product,"
          + ".wc-block-product-template .wc-block-product",
        );
        const linksByCard = productCards.map((card) => (
          [...card.querySelectorAll("a[href]")].filter(
            (link) => (
              link.closest(
                ".products .product,"
                + ".wc-block-grid__products .wc-block-grid__product,"
                + ".wc-block-product-template .wc-block-product",
              ) === card
              && rendered(link, true)
              && safeHref(
                link.getAttribute("href"),
                "",
                false,
                "/product/",
              )
              && (
                meaningfulTextVisible(link)
                || [...link.querySelectorAll("img[alt][src]")].some(
                  (image) => (
                    image instanceof HTMLImageElement
                    && /[\p{L}\p{N}]/u.test(image.alt)
                    && image.complete
                    && image.naturalWidth > 0
                    && image.naturalHeight > 0
                    && rendered(image)
                  ),
                )
              )
            ),
          )
        ));
        const links = linksByCard.flat();
        const emptyStates = visibleMatches(".woocommerce-info").filter(
          (element) => (
            text(element)
              === "No products were found matching your selection."
            && meaningfulTextVisible(element)
          ),
        );
        const catalog = (
          productCards.length > 0
          && linksByCard.every((cardLinks) => cardLinks.length > 0)
        );
        const reviewedEmptyState = emptyStates.length === 1;
        result.passed = catalog && !reviewedEmptyState;
        result.routeUi = result.passed ? "product_catalog" : "";
        result.dom = {
          productCardCount: productCards.length,
          productLinkCount: links.length,
        };
        if (!result.passed) {
          result.failureCodes.push("shop_surface");
        }
        return result;
      }

      if (mode === "cart") {
        const forms = visibleMatches("form.woocommerce-cart-form");
        const validForms = forms.filter((form) => {
          const controls = ownedControls(form);
          const dataInputs = routeDataInputs(controls, "cart");
          const submits = routeSubmitControls(form, "cart");
          return (
            formIsSafe(form, "/cart/")
            && dataInputs.length > 0
            && submits.length > 0
            && submits.every((control) => (
              submitterIsSafe(control, form, "/cart/")
            ))
            && ownedNonce(form, "woocommerce-cart-nonce")
          );
        });
        const blockScopes = visibleMatches(".wc-block-cart");
        const blockForms = blockScopes.flatMap((scope) => (
          [...scope.querySelectorAll("form")].filter(
            (form) => rendered(form),
          )
        ));
        const allForms = [...new Set([...forms, ...blockForms])];
        const validBlockForms = blockForms.filter((form) => {
            const controls = ownedControls(form);
            const dataInputs = routeDataInputs(controls, "cart");
            const submits = routeSubmitControls(form, "cart");
            return (
              formIsSafe(form, "/cart/", true)
              && dataInputs.length > 0
              && submits.length > 0
              && submits.every((control) => (
                submitterIsSafe(control, form, "/cart/", true)
              ))
              && form.closest(".wc-block-cart") instanceof HTMLElement
            );
        });
        const classicEmpty = visibleMatches(".cart-empty").filter(
          (element) => text(element).includes("Your cart is currently empty"),
        );
        const returnLinks = visibleMatches(".return-to-shop a[href],a.return-to-shop[href]")
          .filter((link) => (
            safeHref(link.getAttribute("href"), "/shop/")
          ));
        const blockEmpty = visibleMatches(
          ".wp-block-woocommerce-empty-cart-block",
        ).filter(
          (element) => text(element).includes("Your cart is currently empty"),
        );
        const reviewedEmptyState = (
          (classicEmpty.length === 1 && returnLinks.length > 0)
          || blockEmpty.length === 1
        );
        const validFormCount = new Set(
          [...validForms, ...validBlockForms],
        ).size;
        const cartSurface = (
          allForms.length === 1
          && validFormCount === 1
          && !reviewedEmptyState
        );
        const emptySurface = (
          allForms.length === 0
          && reviewedEmptyState
        );
        result.passed = cartSurface || emptySurface;
        result.routeUi = cartSurface
          ? "cart"
          : emptySurface
            ? "reviewed_empty_state"
            : "";
        const reviewedForm = validForms[0] || validBlockForms[0] || null;
        const controls = reviewedForm ? ownedControls(reviewedForm) : [];
        result.dom = {
          cartFormCount: allForms.length,
          dataInputCount: routeDataInputs(controls, "cart").length,
          submitCount: reviewedForm
            ? routeSubmitControls(reviewedForm, "cart").length
            : 0,
        };
        if (!result.passed) {
          result.failureCodes.push("cart_surface");
        }
        return result;
      }

      if (mode === "account") {
        const forms = visibleMatches("form.woocommerce-form-login");
        const validForms = [];
        let usernameCount = 0;
        let passwordCount = 0;
        let submitCount = 0;
        for (const form of forms) {
          const controls = ownedControls(form);
          const usernames = controls.filter((control) => (
            control instanceof HTMLInputElement
            && control.name === "username"
            && ["email", "text"].includes(control.type.toLowerCase())
            && enabled(control)
            && !control.readOnly
            && control.getAttribute("aria-readonly")
              ?.trim().toLowerCase() !== "true"
            && rendered(control, true)
            && fieldVisiblyUsable(control)
          ));
          const passwords = controls.filter((control) => (
            control instanceof HTMLInputElement
            && control.name === "password"
            && control.type.toLowerCase() === "password"
            && enabled(control)
            && !control.readOnly
            && control.getAttribute("aria-readonly")
              ?.trim().toLowerCase() !== "true"
            && rendered(control, true)
            && fieldVisiblyUsable(control)
          ));
          const submits = submitControls(form);
          if (
            formIsSafe(form, "/my-account/", true)
            && usernames.length === 1
            && passwords.length === 1
            && routeSubmitControls(form, "account").length > 0
            && routeSubmitControls(form, "account").every(
              (control) => (
                submitterIsSafe(
                  control,
                  form,
                  "/my-account/",
                  true,
                )
              ),
            )
            && ownedNonce(form, "woocommerce-login-nonce")
          ) {
            validForms.push(form);
            usernameCount = usernames.length;
            passwordCount = passwords.length;
            submitCount = routeSubmitControls(form, "account").length;
          }
        }
        result.passed = forms.length === 1 && validForms.length === 1;
        result.routeUi = result.passed ? "login_form" : "";
        result.dom = {
          loginFormCount: forms.length,
          passwordCount,
          submitCount,
          usernameCount,
        };
        if (!result.passed) {
          result.failureCodes.push("account_surface");
        }
        return result;
      }

      if (mode === "checkout" && renderedPath === "/cart/") {
        const cartForms = visibleMatches(
          "form.woocommerce-cart-form,.wc-block-cart form",
        );
        const classicEmpty = visibleMatches(".cart-empty").filter(
          (element) => text(element).includes("Your cart is currently empty"),
        );
        const returnLinks = visibleMatches(
          ".return-to-shop a[href],a.return-to-shop[href]",
        ).filter((link) => (
          safeHref(link.getAttribute("href"), "/shop/")
        ));
        const blockEmpty = visibleMatches(
          ".wp-block-woocommerce-empty-cart-block",
        ).filter(
          (element) => text(element).includes("Your cart is currently empty"),
        );
        result.passed = (
          cartForms.length === 0
          && (
            (classicEmpty.length === 1 && returnLinks.length > 0)
            || blockEmpty.length === 1
          )
        );
        result.routeUi = result.passed ? "empty_cart_redirect" : "";
        result.dom = {
          cartFormCount: cartForms.length,
          dataInputCount: 0,
          submitCount: 0,
        };
        if (!result.passed) {
          result.failureCodes.push("cart_surface");
        }
        return result;
      }

      const classicForms = visibleMatches("form.checkout");
      const blockScopes = visibleMatches(".wc-block-checkout");
      const blockForms = blockScopes.flatMap((scope) => (
        [...scope.querySelectorAll("form")].filter(
          (form) => rendered(form),
        )
      ));
      const allForms = [...classicForms, ...blockForms];
      const validForms = allForms.filter((form) => {
        const controls = ownedControls(form);
        const blockCheckout = (
          form.closest(".wc-block-checkout") instanceof HTMLElement
        );
        const dataInputs = routeDataInputs(controls, "checkout");
        const submits = routeSubmitControls(form, "checkout");
        return (
          formIsSafe(form, "/checkout/", true)
          && dataInputs.length >= 6
          && checkoutDataIsCoherent(controls, blockCheckout)
          && submits.length > 0
          && submits.every((control) => (
            submitterIsSafe(control, form, "/checkout/", true)
          ))
          && (
            blockCheckout
            || ownedNonce(
              form,
              "woocommerce-process-checkout-nonce",
            )
          )
        );
      });
      const reviewedForm = validForms[0] || null;
      const controls = reviewedForm ? ownedControls(reviewedForm) : [];
      result.passed = allForms.length === 1 && validForms.length === 1;
      result.routeUi = result.passed ? "checkout" : "";
      result.dom = {
        checkoutFormCount: allForms.length,
        dataInputCount: routeDataInputs(controls, "checkout").length,
        submitCount: reviewedForm
          ? routeSubmitControls(reviewedForm, "checkout").length
          : 0,
      };
      if (!result.passed) {
        result.failureCodes.push("checkout_surface");
      }
      return result;
    },
    {
      expectedOrigin: input.expectedOrigin,
      expectedPath: input.expectedPath,
      mode: input.mode,
      productId: input.productId,
      renderedPath: input.renderedPath,
    },
  );
}

async function probeInteractiveStates(page, input, baseline) {
  if (
    !baseline.passed
    || ["empty_cart_redirect", "reviewed_empty_state"].includes(
      baseline.routeUi,
    )
  ) {
    return baseline;
  }
  const selector = {
    account: (
      "form.woocommerce-form-login button,"
      + "form.woocommerce-form-login input[type=submit],"
      + "form.woocommerce-form-login input[type=image],"
      + "form.woocommerce-form-login input[name=username],"
      + "form.woocommerce-form-login input[name=password]"
    ),
    cart: (
      "form.woocommerce-cart-form button,"
      + "form.woocommerce-cart-form input[type=submit],"
      + "form.woocommerce-cart-form input[type=image],"
      + ".wc-block-cart form button,"
      + ".wc-block-cart form input[type=submit],"
      + ".wc-block-cart form input[type=image],"
      + "form.woocommerce-cart-form input:not([type=hidden]),"
      + ".wc-block-cart form input:not([type=hidden])"
    ),
    checkout: (
      "form.checkout button,"
      + "form.checkout input[type=submit],"
      + "form.checkout input[type=image],"
      + ".wc-block-checkout form button,"
      + ".wc-block-checkout form input[type=submit],"
      + ".wc-block-checkout form input[type=image],"
      + "form.checkout input:not([type=hidden]),"
      + ".wc-block-checkout form input:not([type=hidden])"
    ),
    product: (
      "form.cart button,"
      + "form.cart input[type=submit],"
      + "form.cart input[type=image]"
    ),
    shop: (
      ".products .product a[href],"
      + ".wc-block-grid__products .wc-block-grid__product a[href],"
      + ".wc-block-product-template .wc-block-product a[href]"
    ),
  }[input.mode];
  const marker = "data-robbottx-proof-interaction";
  const count = await page.evaluate(
    ({ markerName, selectorValue }) => {
      for (const candidate of document.querySelectorAll(`[${markerName}]`)) {
        candidate.removeAttribute(markerName);
      }
      const candidates = [...document.querySelectorAll(selectorValue)]
        .filter((candidate) => {
          if (!(candidate instanceof HTMLElement)) {
            return false;
          }
          const style = getComputedStyle(candidate);
          const rectangle = candidate.getBoundingClientRect();
          return (
            !candidate.matches(":disabled")
            && candidate.getAttribute("aria-disabled")
              ?.trim().toLowerCase() !== "true"
            && style.display !== "none"
            && style.visibility === "visible"
            && Number.parseFloat(style.opacity) > 0
            && rectangle.width >= 1
            && rectangle.height >= 1
          );
        });
      candidates.forEach((candidate, index) => {
        candidate.setAttribute(markerName, String(index));
      });
      return candidates.length;
    },
    { markerName: marker, selectorValue: selector },
  );
  if (!Number.isInteger(count) || count < 1 || count > 64) {
    return {
      passed: false,
      routeUi: "",
      failureCodes: [{
        account: "account_surface",
        cart: "cart_surface",
        checkout: "checkout_surface",
        product: "product_action",
        shop: "shop_surface",
      }[input.mode]],
      dom: baseline.dom,
    };
  }
  for (let index = 0; index < count; index += 1) {
    let handle = await page.$(`[${marker}="${index}"]`);
    if (handle === null) {
      return {
        ...baseline,
        passed: false,
        routeUi: "",
      };
    }
    await handle.hover();
    let state = await inspectDom(page, input);
    if (!state.passed) {
      return state;
    }
    await page.mouse.move(0, 0);
    await page.evaluate(() => {
      if (document.activeElement instanceof HTMLElement) {
        document.activeElement.blur();
      }
    });
    handle = await page.$(`[${marker}="${index}"]`);
    if (handle === null) {
      return {
        ...baseline,
        passed: false,
        routeUi: "",
      };
    }
    await handle.focus();
    const retainedFocus = await page.evaluate(
      ({ markerName, markerValue }) => {
        const candidate = document.querySelector(
          `[${markerName}="${markerValue}"]`,
        );
        return (
          candidate instanceof HTMLElement
          && document.activeElement === candidate
          && candidate.matches(":focus")
        );
      },
      { markerName: marker, markerValue: String(index) },
    );
    if (!retainedFocus) {
      return {
        ...baseline,
        passed: false,
        routeUi: "",
      };
    }
    state = await inspectDom(page, input);
    if (!state.passed) {
      return state;
    }
    await page.evaluate(() => {
      if (document.activeElement instanceof HTMLElement) {
        document.activeElement.blur();
      }
    });
  }
  return baseline;
}

async function runProof(argumentsValue, input) {
  const profile = createOwnedProfile(argumentsValue.profile);
  const operationDeadline = Date.now() + argumentsValue.operationTimeoutMs;
  let browser = null;
  let context = null;
  let browserPid = 0;
  let result = failureResult(input.mode, input.source);
  try {
    browser = await withDeadline(
      puppeteer.launch({
        executablePath: argumentsValue.chrome,
        env: safeChildEnvironment(),
        headless: true,
        timeout: Math.min(
          20_000,
          Math.max(1, operationDeadline - Date.now()),
        ),
        userDataDir: profile,
        args: [
          "--disable-background-networking",
          "--disable-component-update",
          "--disable-default-apps",
          "--disable-dev-shm-usage",
          "--disable-extensions",
          "--disable-features=Translate,OptimizationHints,MediaRouter",
          "--disable-sync",
          "--metrics-recording-only",
          "--no-first-run",
          "--no-sandbox",
          "--password-store=basic",
          "--use-mock-keychain",
        ],
      }),
      operationDeadline,
      "operation_timeout",
    );
    browserPid = browser.process()?.pid || 0;
    context = await browser.createBrowserContext();
    const page = await context.newPage();
    const requestState = {
      blockedStylesheets: new Set(),
      failedStylesheets: new Set(),
      loadedStylesheets: new Set(),
      stylesheetRequests: new Set(),
    };
    await configurePage(page, input, requestState);

    const testDelay = process.env.NODE_ENV === "test"
      ? Number(process.env.ROBBOTTX_COMMERCE_PROOF_TEST_DELAY_MS || "0")
      : 0;
    if (Number.isFinite(testDelay) && testDelay > 0) {
      await withDeadline(
        new Promise((resolve) => setTimeout(resolve, testDelay)),
        operationDeadline,
        "operation_timeout",
      );
    }

    let mainStatus = null;
    let redirectStatus = null;
    let finalOrigin = "";
    let finalPath = "";
    let redirectCount = 0;
    if (input.source === "live") {
      const mainResponse = await withDeadline(
        page.goto(input.url, {
          waitUntil: "networkidle0",
          timeout: Math.min(
            30_000,
            Math.max(1, operationDeadline - Date.now()),
          ),
        }),
        operationDeadline,
        "navigation_timeout",
      );
      if (mainResponse !== null) {
        mainStatus = mainResponse.status();
        const redirectChain = mainResponse.request().redirectChain();
        redirectCount = redirectChain.length;
        redirectStatus = redirectCount === 1
          ? redirectChain[0].response()?.status() ?? null
          : null;
      }
      const finalUrl = new URL(page.url());
      finalOrigin = finalUrl.origin;
      finalPath = finalUrl.pathname;
    } else {
      await withDeadline(
        page.setContent(input.html, {
          waitUntil: "domcontentloaded",
          timeout: Math.min(
            10_000,
            Math.max(1, operationDeadline - Date.now()),
          ),
        }),
        operationDeadline,
        "fixture_timeout",
      );
      finalOrigin = input.expectedOrigin;
      finalPath = input.expectedPath;
    }

    const externalStylesheets = await page.evaluate(() => (
      [...document.querySelectorAll('link[rel~="stylesheet" i][href]')]
        .filter((link) => !link.disabled)
        .map((link) => link.href)
    ));
    if (input.source === "fixture" && externalStylesheets.length > 0) {
      for (const stylesheet of externalStylesheets) {
        requestState.blockedStylesheets.add(stylesheet);
      }
    }
    const missingStylesheets = externalStylesheets.filter(
      (stylesheet) => !requestState.loadedStylesheets.has(stylesheet),
    );
    for (const stylesheet of missingStylesheets) {
      requestState.failedStylesheets.add(stylesheet);
    }

    let semantic = await withDeadline(
      inspectDom(page, { ...input, renderedPath: finalPath }),
      operationDeadline,
      "evaluation_timeout",
    );
    semantic = await withDeadline(
      probeInteractiveStates(
        page,
        { ...input, renderedPath: finalPath },
        semantic,
      ),
      operationDeadline,
      "evaluation_timeout",
    );
    const directNavigation = (
      input.source === "live"
      && (
        mainStatus === 200
        && page.url() === input.url
        && finalOrigin === input.expectedOrigin
        && finalPath === input.expectedPath
        && redirectCount === 0
        && redirectStatus === null
      )
    );
    const checkoutRedirectNavigation = (
      input.source === "live"
      && input.mode === "checkout"
      && mainStatus === 200
      && page.url() === `${input.expectedOrigin}/cart/`
      && finalOrigin === input.expectedOrigin
      && finalPath === "/cart/"
      && redirectCount === 1
      && redirectStatus === 302
    );
    const navigationPassed = (
      input.source === "fixture"
      || directNavigation
      || checkoutRedirectNavigation
    );
    const stylesheetsPassed = (
      requestState.failedStylesheets.size === 0
      && requestState.blockedStylesheets.size === 0
      && (
        input.source === "fixture"
        || requestState.loadedStylesheets.size
          === requestState.stylesheetRequests.size
      )
    );
    const failureCodes = [...semantic.failureCodes];
    if (!navigationPassed) {
      failureCodes.push("navigation");
    }
    if (requestState.blockedStylesheets.size > 0) {
      failureCodes.push("stylesheet_blocked");
    }
    if (requestState.failedStylesheets.size > 0) {
      failureCodes.push("stylesheet_failed");
    }
    result = {
      schemaVersion: SCHEMA_VERSION,
      operational: true,
      passed: semantic.passed && navigationPassed && stylesheetsPassed,
      mode: input.mode,
      source: input.source,
      routeUi: semantic.routeUi,
      failureCodes,
      navigation: {
        status: mainStatus,
        redirectStatus,
        finalOrigin,
        finalPath,
        redirectCount,
      },
      stylesheets: {
        externalCount: requestState.stylesheetRequests.size,
        loadedCount: requestState.loadedStylesheets.size,
        failedCount: requestState.failedStylesheets.size,
        blockedCount: requestState.blockedStylesheets.size,
      },
      dom: semantic.dom,
    };
  } catch (error) {
    const code = [
      "evaluation_timeout",
      "fixture_timeout",
      "navigation_timeout",
      "operation_timeout",
    ].includes(error?.message)
      ? error.message
      : "browser_error";
    result = failureResult(input.mode, input.source, code);
  } finally {
    const cleanupPassed = await cleanup(
      browser,
      context,
      browserPid,
      profile,
    );
    if (!cleanupPassed) {
      result.operational = false;
      result.passed = false;
      result.failureCodes = [
        ...(result.failureCodes || []),
        "cleanup_failed",
      ];
    }
  }
  return allowlistedResult(result);
}

async function main() {
  let parsedInput = null;
  let result;
  try {
    const argumentsValue = parseArguments(process.argv.slice(2));
    parsedInput = validateInput(JSON.parse(await readStandardInput()));
    result = await runProof(argumentsValue, parsedInput);
  } catch (error) {
    const code = [
      "input_too_large",
      "invalid_arguments",
      "invalid_fixture_html",
      "invalid_input",
      "invalid_live_url",
      "invalid_product_id",
      "invalid_source",
      "unexpected_product_id",
    ].includes(error?.message)
      ? error.message
      : "browser_error";
    result = failureResult(
      parsedInput?.mode,
      parsedInput?.source,
      code,
    );
  }
  process.stdout.write(`${JSON.stringify(allowlistedResult(result))}\n`);
  if (!result.operational) {
    process.exitCode = 1;
  }
}

await main();
