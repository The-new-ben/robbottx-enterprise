# RobbottX agent deployment runbook

The globally installed `wordpress-agent-deploy` skill is mandatory.

## Release endpoints

- Plugin manifest:
  `https://raw.githubusercontent.com/The-new-ben/robbottx-enterprise/main/plugin-dist/robbottx-core.json`
- Versioned plugin ZIP:
  `https://raw.githubusercontent.com/The-new-ben/robbottx-enterprise/main/plugin-dist/robbottx-core-<version>.zip`
- Versioned theme ZIP:
  `https://raw.githubusercontent.com/The-new-ben/robbottx-enterprise/main/plugin-dist/robbottx-<version>.zip`
- Public healthcheck:
  `https://robbottx.com/wp-json/robbottx/v1/healthcheck`
- Temporary plugin deploy route:
  `https://robbottx.com/wp-json/agentdeploy/v1/run-<unique-release-token>`
- Temporary theme deploy route:
  `https://robbottx.com/wp-json/agenttheme/v1/run-<unique-release-token>`

Each unique temporary route must return the WordPress JSON `rest_no_route`
404 before creation and after cleanup. The legacy fixed plugin and theme
routes must not be registered.

## Local build

```text
npm run qa
python scripts/build-plugin-zip.py \
  --plugin-dir wp-content/plugins/robbottx-core \
  --slug robbottx-core \
  --version <version> \
  --main-file robbottx-core.php \
  --version-constant ROBBOTTX_CORE_VERSION \
  --output-dir plugin-dist \
  --require-marker "<release-specific plugin source marker>"
python scripts/build-theme-zip.py \
  --theme-dir wp-content/themes/robbottx \
  --slug robbottx \
  --version <version> \
  --output-dir plugin-dist
```

Each builder rejects files outside its reviewed inventory and writes a
versioned inventory JSON containing every packaged path, byte size, and
SHA-256. Reopen and inspect both ZIPs. The theme owns static chrome. Ongoing
dynamic records and customer-facing behavior ship in `robbottx-core`.

## Runtime secrets

The deploy driver reads only:

- `WP_BASE_URL`
- `WP_USER`
- `WP_APP_PASSWORD`

They are runtime environment variables, never repository files. Do not print
them. Do not store them in release evidence.

Create a new temporary WordPress Application Password at action time for each
theme release. Use the already authenticated primary administrator browser
session, name it with the release version and UTC timestamp, and retain its
WordPress password UUID only in the active operator session. Capture the
one-time returned password value from
`POST /wp-json/wp/v2/users/<user-id>/application-passwords` directly into
`WP_APP_PASSWORD`; do not place it in shell
history, a command file, chat, clipboard history, or release evidence. Set
`WP_USER` to that exact administrator and verify `/wp-json/wp/v2/users/me`
through the temporary credential before preflight.

Treat the full preflight, deploy, verification, and evidence sequence as one
`try` block. Its `finally` block must revoke the exact temporary password UUID
using the independently authenticated primary administrator browser session,
then clear `WP_APP_PASSWORD`, `WP_USER`, and `WP_BASE_URL` from the process.
The temporary password cannot prove its own revocation. After deletion, use
the primary administrator session to list
`/wp-json/wp/v2/users/<user-id>/application-passwords` and independently prove
that the exact UUID is absent. The revocation target is
`/wp-json/wp/v2/users/<user-id>/application-passwords/<uuid>`. Authenticate
both operations with the primary browser session and its WordPress REST nonce,
not with the temporary password. Record only the
revocation result and UUID fingerprint, never the password. Release acceptance
remains incomplete until this independent absence proof passes. If the API or
browser proof is unavailable, revoke the named password manually in the
administrator profile, repeat the independent list proof, and do not accept
the release while its status is uncertain.

## Deploy the plugin

From the current clean reviewed checkout, generate a new ignored release
receipt immediately before each plugin-driver invocation:

```text
python scripts/validate-proprietary-boundary.py \
  --root . \
  --release \
  --expected-commit <current-40-character-lowercase-Git-HEAD> \
  --artifact-path plugin-dist/robbottx-core-<version>.zip \
  --artifact-sha256 <exact-local-and-public-sha256> \
  --receipt work/boundary-release-<version>-<unique-UTC-time>.json
```

The receipt path must not exist. The scanner writes it only after proving a
clean index and worktree, the expected HEAD, the complete repository
inventory, approved-asset manifest, public snapshot payload, and exact
artifact path and hash.

The deliberate deploy command is:

```text
python scripts/deploy-wordpress.py \
  --version <version> \
  --zip-url <verified-public-raw-zip-url> \
  --zip-size <exact-public-byte-size> \
  --zip-sha256 <exact-public-sha256> \
  --record-hash <exact-record-payload-sha256> \
  --boundary-receipt work/boundary-release-<version>-<unique-UTC-time>.json \
  --package-marker "<release-specific source marker>" \
  --old-body-marker "<!-- robbottx-core:<previous-version> -->" \
  --execute
```

Before reading WordPress environment variables or making a network request,
the driver requires the receipt to be no more than 15 minutes old and not in
the future relative to the local UTC clock. It directly reruns the reviewed
boundary scanner and requires the current clean HEAD, index, worktree,
repository inventory, approved-asset manifest, public snapshot, and exact
artifact path and hash to match the receipt. A self-consistent JSON document
cannot substitute for this current scan. Scanner Git calls use a protected
absolute executable, an allowlisted read-only command set, a credential-free
child environment, bounded output, and a fixed timeout. If the driver cannot
establish that execution contract, it fails before WordPress credentials or
network access.

The driver then verifies administrator authority, the public update manifest,
versioned inventory, exact ZIP bytes, hash, root, embedded version, record
hash, and release marker. The one-use callback downloads the package again and
checks its hash and size before installation. Success requires an exact,
unambiguous callback confirmation of the result, active plugin, installed
version, and bound artifact. A health marker cannot replace a missing,
malformed, or mismatched callback confirmation. The driver requires route and
snippet-name absence before creation, uses a unique route and snippet name,
runs `Plugin_Upgrader` with strict installed-version checks, verifies the
independent healthcheck and rendered body, finds and deletes the snippet by
exact unique name even when the create response is malformed, and proves the
former route returns WordPress JSON `rest_no_route`.

## Deploy the theme

Generate a separate new ignored boundary receipt immediately before each theme
preflight or execution:

```text
python scripts/validate-proprietary-boundary.py \
  --root . \
  --release \
  --expected-commit <current-40-character-lowercase-Git-HEAD> \
  --artifact-path plugin-dist/robbottx-<version>.zip \
  --artifact-sha256 <exact-local-and-public-sha256> \
  --receipt work/theme-boundary-release-<version>-<unique-UTC-time>.json
```

Run the theme driver without `--execute` first. This performs the authenticated
authority, public artifact, unique-route, legacy-route, and snippet-name
preflight without creating a snippet or changing WordPress:

```text
npm run deploy:theme -- \
  --version <version> \
  --previous-version <exact-current-production-theme-version> \
  --zip-url <verified-public-versioned-theme-zip-url> \
  --zip-size <exact-public-byte-size> \
  --zip-sha256 <exact-public-sha256> \
  --boundary-receipt work/theme-boundary-release-<version>-<unique-UTC-time>.json \
  --package-marker "<release-specific theme source marker>" \
  --new-body-marker "<marker rendered only by the new theme>" \
  --old-body-marker "<marker rendered only by the previous theme>" \
  --expect-fallback-favicon \
  --output <new-private-preflight-evidence-path>.json
```

After preflight passes, generate another fresh boundary receipt at a new path,
then repeat the reviewed arguments with `--execute`, that new receipt, and a
second new `--output` path. Every output path is required and must not exist.
The driver writes both success and failure receipts atomically and refuses to
overwrite earlier evidence.

Before reading WordPress environment variables or making a network request,
the theme driver applies the same reviewed 15-minute, non-future,
current-clean-repository boundary gate used by the plugin driver. It requires
the current HEAD, index, worktree, repository inventory, approved-asset
manifest, public snapshot, and exact
`plugin-dist/robbottx-<version>.zip` SHA-256 to match the receipt. The sibling
boundary verifier executes only from its ordinary Git-index blob when that
blob exactly matches the same HEAD. The one-use PHP template is likewise
loaded from clean index bytes, hash-checked, and frozen in memory before
credentials or network access. The driver repeats the complete fresh receipt,
current repository, artifact, verifier, and template proof immediately before
the Code Snippets creation request. A change during preflight therefore blocks
the mutation.

The driver then accepts only `https://robbottx.com` as the WordPress origin
and only the canonical versioned theme ZIP under this repository's
`raw.githubusercontent.com/.../main/plugin-dist/` path.
The driver downloads and validates the exact ZIP locally, then makes the
one-use WordPress callback download and hash-check the same bytes before
installation. A successful release requires the callback to confirm the exact
artifact-bound route result in a duplicate-free JSON object with exactly the
reviewed fields and exact boolean and string types. An unavailable, malformed,
extra-field, duplicate-key, or mismatched callback is a failed release even
when later state reads show the target version.

Before mutation, the driver authenticates the exact standalone active block
theme at `--previous-version`, proves the old body marker is present and the
new marker absent, reads the WordPress site-icon identity, fetches the exact
stylesheet and icon resources, and requires no more than 98 Code Snippets
records. After the callback, it authenticates the target theme version, proves
the marker state has inverted, requires the site-icon identity to be unchanged,
and fetches the exact target assets again. Relative asset URLs are resolved as
a browser resolves them against the rendered document URL. External, unsafe,
or mixed `<base>` values fail closed. Theme asset queries must contain only the
exact `ver=<theme-version>` pair.

`--expect-fallback-favicon` requires WordPress to have no configured site icon
and requires the one exact versioned theme SVG. The mutually exclusive
`--no-expect-fallback-favicon` mode requires a positive authenticated
WordPress `site_icon` ID and accepts only icon URLs from that exact media
record and its registered sizes. A same-origin image that is not part of that
authenticated identity does not pass.

Cleanup is mandatory even after an ambiguous creation or failed verification.
The driver recovers the snippet by its exact unique name, proves each snippet
record is gone, proves the one-use route returns WordPress JSON
`rest_no_route`, and proves the legacy theme route remains absent. Its final
JSON evidence is allowlisted and does not contain credentials, route tokens,
snippet code, server paths, upgrader messages, or response bodies.
The fixed legacy callback is checked by exact absence from the WordPress REST
route inventory. This read-only inventory proof is authoritative because the
production edge closes `OPTIONS` before WordPress receives it. The driver
never calls or posts to a legacy deployment route.

## Deploy the root robots file

The root `robots.txt` is a hosting artifact. It is deliberately absent from
both WordPress ZIPs, so changing `hosting/robots.txt` does not deploy it. Commit
the reviewed file first, then record its exact byte count and SHA-256. Its
source URL must use the immutable 40-character commit, never `main`, a tag, a
redirect, or a query string:

```text
https://raw.githubusercontent.com/The-new-ben/robbottx-enterprise/<commit>/hosting/robots.txt
```

Generate a new ignored boundary receipt immediately before the read-only
preflight:

```text
python scripts/validate-proprietary-boundary.py \
  --root . \
  --release \
  --expected-commit <current-40-character-lowercase-Git-HEAD> \
  --artifact-path hosting/robots.txt \
  --artifact-sha256 <exact-robots-sha256> \
  --receipt work/robots-boundary-<commit>-<unique-UTC-time>.json
```

Run the driver without `--execute` first:

```text
npm run deploy:robots -- \
  --commit <current-40-character-lowercase-Git-HEAD> \
  --robots-url https://raw.githubusercontent.com/The-new-ben/robbottx-enterprise/<commit>/hosting/robots.txt \
  --robots-size <exact-byte-count> \
  --robots-sha256 <exact-robots-sha256> \
  --boundary-receipt work/robots-boundary-<commit>-<unique-UTC-time>.json \
  --output <new-private-robots-preflight-evidence-path>.json
```

The preflight verifies the clean current repository and receipt before any
credential or network access, downloads the exact immutable raw bytes without
redirects, verifies administrator `update_plugins` and `manage_options`
authority, bounds Code Snippets at 98 records, proves the complete
`/agentrobots` namespace and exact snippet name absent, and accepts the public
root response only when it is either a real 404 or already exact `text/plain`
bytes.

After preflight, generate another fresh receipt at a new ignored path and
repeat the exact command with `--execute` and a second new `--output` path. The
driver loads the verifier, shared WordPress operations, route template, and
`hosting/robots.txt` only from ordinary Git-index blobs matching the same HEAD.
It freezes and hash-checks those bytes before credentials, then repeats the
complete fresh receipt, current scan, commit, helper, template, and artifact
proof immediately before snippet creation.

The one-use callback downloads the same commit-pinned source with redirects
disabled and requires exact `text/plain`, byte count, and SHA-256. It accepts
an existing `ABSPATH/robots.txt` only when it is an ordinary file with the
exact bytes. A different file, symlink, special file, or race is never
overwritten. When absent, the callback writes and syncs an exclusive temporary
file, verifies it, and atomically hard-links it to the root name; it then
removes the temporary name and proves no robots temporary file remains. It
purges LiteSpeed and WordPress caches.

Success requires a duplicate-free exact callback when usable, an independent
authenticated file-state GET, and a cache-busted public HTTP 200 response with
`text/plain` and byte-for-byte equality. A proxy-obscured callback may be
recorded as unconfirmed only when both independent proofs pass. The driver
always deletes the temporary snippet by exact ID or unique name, requires the
former route to return exact WordPress `rest_no_route` 404 JSON, and proves the
complete namespace absent. Evidence is allowlisted and never stores
credentials, route tokens, snippet code, response bodies, or server paths.

## Configure the reviewed commerce surface

This is an activation tool for a later release with reviewed products and
current orderable offers. Do not run it while commerce is inactive. The
inactive release keeps shop, cart, checkout, account, product, product
taxonomy, and Store API discovery unavailable to the public while preserving
authorized administration.

After plugin and theme verification, generate a new ignored boundary receipt
for the exact current `robbottx-core` artifact:

```text
python scripts/validate-proprietary-boundary.py \
  --root . \
  --release \
  --expected-commit <current-40-character-lowercase-Git-HEAD> \
  --artifact-path plugin-dist/robbottx-core-<plugin-version>.zip \
  --artifact-sha256 <exact-plugin-zip-sha256> \
  --receipt work/commerce-boundary-release-<plugin-version>-<unique-UTC-time>.json
```

Then run the read-only commerce preflight:

```text
npm run configure:commerce -- \
  --plugin-version <plugin-version> \
  --plugin-zip-sha256 <exact-plugin-zip-sha256> \
  --boundary-receipt work/commerce-boundary-release-<plugin-version>-<unique-UTC-time>.json \
  --output <new-private-commerce-preflight-receipt>.json
```

The preflight requires an administrator with `update_plugins`,
`manage_options`, `manage_woocommerce`, `edit_pages`, and
`edit_published_pages`; no more than 98 Code Snippets records; the exact
published Shop, Cart, Checkout, and My account page identities; and absence of
the complete `/agentconfigure` temporary route family in the REST inventory.
The route-family check fails closed for every version, standing parameterized
route, and regex route, not only exact `agentconfigure/v1` route keys.
Preflight never creates a snippet, calls a temporary callback, or changes
WordPress. The live callback also checks `edit_post` for each exact page and
verifies WooCommerce's configured system-page mapping before any write.

Only after immediate production confirmation, generate another boundary
receipt at a new path and run:

```text
npm run configure:commerce -- \
  --execute \
  --plugin-version <plugin-version> \
  --plugin-zip-sha256 <exact-plugin-zip-sha256> \
  --boundary-receipt work/commerce-boundary-release-<plugin-version>-<new-unique-UTC-time>.json \
  --output <new-private-commerce-execution-receipt>.json
```

Before credentials or network access, the commerce driver requires the same
fresh, non-future, current-clean full-boundary proof and exact
`plugin-dist/robbottx-core-<plugin-version>.zip` binding as the plugin driver.
Shared WordPress operations execute only from an ordinary Git-index blob that
matches the same HEAD. The commerce PHP template is loaded from that HEAD,
hash-checked, and frozen in memory before the scan. Immediately before snippet
creation, the driver repeats the complete receipt, current repository,
artifact, helper, and template proof and requires the frozen bytes to remain
identical.

The one-use administrator-gated callback snapshots the exact original titles
and visibility option, then begins a database transaction before its first
write. It sets `woocommerce_coming_soon = no`, applies only titles that differ
from the reviewed English values, purges cache, and returns no credentials or
private data. It deliberately leaves `woocommerce_store_pages_only` unchanged
because that option controls the protection scope only if Coming soon mode is
enabled again. It validates every page and WooCommerce page mapping before any
write, updates only titles that differ, validates the complete page state
again, and sets Coming soon to `no` only as the last database write. It commits
only after every title and option postcondition passes. A failed write,
postcondition, transaction start, or commit fails closed. Every rollback clears
the four post caches and the relevant WordPress option caches, then verifies
the original state. A rollback command or restoration that cannot be proven is
a hard cleanup failure.

The execution receipt records the authenticated visibility options and exact
Shop, Cart, Checkout, and My account mapping IDs immediately before and after
the callback. It fails if `woocommerce_store_pages_only` or any mapping
changes. The external driver independently verifies the exact option state,
mapping IDs, and exact title values. If the callback reports an error or its
response is ambiguous, the driver independently proves either the complete
intended state or the exact original state. Any third or partial state fails.
When the callback is recorded as confirmed, its JSON must be duplicate-free
and contain exactly the reviewed fields, nested keys, values, and boolean
types; proxy ambiguity is never misreported as callback confirmation.
It then requires the public Shop to render a linked, customer-visible product
catalog. An empty-store message, title, heading, body class, empty product
shell, or hidden product card cannot pass. Content inside a `<template>`,
closed `<dialog>`, closed `<details>`, `hidden`, `inert`, `aria-hidden`, or an
inline concealment declaration is not visible proof.

The static verifier parses all inline CSS and every same-origin linked
stylesheet with the repository-pinned `css-tree` dependency. It follows
same-origin HTTPS `@import` edges with fixed URL, byte, file-count, and depth
bounds. Redirects, cross-origin sheets, bad media types, parse errors, unsafe
raw syntax, and cycles fail closed. Declaration parsing is token-aware, so
quoted semicolons, data URLs, escaped tokens, custom properties, `var()`,
`env()`, and `calc()` are not split or reconstructed as strings. Standard and
vendor keyframe selectors are validated exactly. Hiding declarations in nested
conditional blocks are reviewed too. A selector the static matcher cannot
model is deferred to the mandatory browser proof. It is never treated as proof
that an element is visible. The live `#end-resizable-editor-section` rule is
allowed only when that exact unrelated target exists.

After every HTTP, HTML, stylesheet, schema, and product check passes, the
driver runs the exact hash-pinned `verify-commerce-dom.mjs` helper with
lockfile-pinned `puppeteer-core` 25.3.0 and an absolute Chrome executable. The
child process receives only an allowlisted operating-system environment, so
WordPress credentials and unrelated tokens are not inherited. Its JSON input
and output are bounded and schema-checked. Raw browser output is never copied
into a receipt or operator error. The accepted helper SHA-256 is
`e3d3fdbfe678fd9f2f637db0814c6dadbe14cde2c6e44cdd41b9cbdaee597df4`.

The browser opens a fresh isolated profile with JavaScript, browser cache, and
service workers disabled. It makes no click and submits no form. It permits
only the exact main navigation and same-origin HTTPS stylesheet, font, and
image resources required for computed rendering. Every external stylesheet
must load. The Python caller creates the exact temporary profile, starts Node
in an owned process group, and gives the profile path to the helper. The helper
has one 45-second operation deadline and a separate 15-second cleanup deadline.
The caller allows a 15-second margin, verifies the profile is absent, and kills
the owned process tree plus removes only that validated profile after a
timeout. Every browser process must terminate. Any operational, cleanup,
navigation, resource, schema, or semantic failure rejects the commerce
configuration.

JavaScript is disabled by the approved browser-proof contract so verification
cannot execute a production-side action. The final public release verifier
separately bounds, fetches, and parses executable scripts, rejects inline
event handlers, and checks reviewed active-content failures. It does not claim
that arbitrary production JavaScript was executed or that every possible
runtime DOM mutation was observed. That residual limitation must remain
explicit in release acceptance.

The browser proves the exact cache-busted Shop, Cart, My account, and Checkout
routes plus every statically reviewed product URL and product ID. It uses the
browser-repaired DOM, computed styles, viewport geometry, native
`control.form` ownership, and native disabled state. Shop must expose a
visible linked catalog. Cart must expose one usable cart form or its reviewed
empty state. My account must expose one usable login form. Checkout must expose
one usable checkout form, or an empty session may make exactly one same-origin
302 redirect to Cart where the reviewed empty-cart state is visible.

When products exist, the static driver follows every unique product link on
the Shop, up to the reviewed 100-link bound. The browser then requires one
primary visible product scope with one meaningful title, one positive stock
state, and one canonical POST cart form. Its rendered enabled submit control
and identifier controls must belong to that exact form and agree with the
statically verified positive product ID. A hidden input may carry the ID but
never counts as the visible submit. Duplicate attributes or IDs, nested forms,
disabled fieldsets, reassigned controls, template content, concealed or
offscreen controls, mismatched IDs, and error shells cannot pass.

The same product summary must contain exactly one visible offer-evidence
element with a nonempty supplier, uppercase two-letter region, positive unit
quantity basis, strict UTC checked timestamp, and lowercase 64-character
offer-record SHA-256. The visible text must repeat the supplier, region,
quantity basis, and checked time. The checked time may not be older than 24
hours or more than five minutes in the future. A bare `In stock` label is not
offer evidence.

The repository CSS validator is also checked against all 425 CSS files in the
official WooCommerce 10.0.6 archive. The reviewed archive SHA-256 is
`53ac345e2f3c630b43e362815164c24dd972526b5be8e4f484e8a7275b20cc4f`.
Malformed raw syntax and invalid keyframe controls remain required negative
tests. `public_store_verified` is set only after the complete static and
browser sequence succeeds.

An unavailable, malformed, or proxy-altered callback body is recorded as
unconfirmed. It can pass only when the independent authenticated reads, parsed
public Shop, and complete cleanup all prove the intended result. The cleanup
path recovers an ambiguously created snippet by its exact one-use name, deletes
it, proves the unique GET and POST route absent, and checks the retired fixed
route by REST inventory without calling it.

Both commands require a new output path. Success and failure receipts are
allowlisted, written atomically, and never overwritten. They contain no
credential, route token, snippet source, server path, or raw response body.
Keep them in the private release-evidence location, and revoke the temporary
Application Password in the outer release `finally` procedure.

WooCommerce documents the visibility options and recommends clearing server
cache when they change:

- https://developer.woocommerce.com/docs/extensions/extension-onboarding/integrating-coming-soon-mode/
- https://developer.woocommerce.com/2025/01/17/developer-advisory-coming-soon-mode-by-default/

## Verify the public release

After both deployments and route cleanup, run the independent public verifier:

```text
python scripts/verify-live-release.py \
  --plugin-version <plugin-version> \
  --theme-version <theme-version> \
  --record-hash <exact-record-payload-sha256> \
  --previous-plugin-version <previous-plugin-version> \
  --expect-fallback-favicon \
  --samples 5 \
  --output <dated-private-evidence-path>.json
```

The previous plugin version is the exact version rendered by production before
deployment, even when a newer intermediate package exists in Git. Use
`--expect-fallback-favicon` for the reviewed theme fallback icon. Use
`--no-expect-fallback-favicon` only for a reviewed configured WordPress site
icon. Fallback mode permits no `--configured-site-icon-url` arguments.
Configured mode requires one repeatable
`--configured-site-icon-url <exact-authenticated-media-url>` argument for
every authenticated WordPress site-icon media URL that is emitted as an icon
link in the public head. Do not accept an unlisted same-origin image or omit
one of the emitted authenticated media URLs.

This verifier uses only unauthenticated HTTPS. It checks the health record,
rendered release marker, canonical and social metadata, structured data,
featured configuration, landmarks, public-language boundary, exact theme
assets, homepage asset discipline, temporary-route cleanup, inherited REST and
HTML suppression, the selected commerce state, WordPress and SEO sitemaps,
search and feed surfaces, root robots policy, and repeated warm response
timing. In inactive-commerce releases it requires uncached noindex 410 HTML
for the four system routes and no public product, taxonomy, Store API, search,
feed, sitemap, or navigation discovery. A hard failure stops release
acceptance. A warning must be recorded with its owner and follow-up decision.

Run the complete pinned Lighthouse gate once:

```text
npm run verify:lighthouse -- \
  --output-dir <new-private-evidence-directory>
```

The output directory must not already exist. The wrapper creates three
immutable desktop reports and three immutable mobile reports with distinct
cache-busting URLs, then writes
`lighthouse-release-receipt.json`. Every report must identify the exact
requested and final canonical URL, pinned Lighthouse 13.4.1, Chrome version,
fetch time, form factor, viewport, the complete pinned simulated-throttling
profile, the pinned emulated user agent, English locale, and the four reviewed
categories. Each must have no runtime error, score at least 90 for performance
and exactly 100 for accessibility, best practices, and SEO, and pass the
color-contrast and browser-console audits.

The aggregate receipt contains all six report SHA-256 values, the original
process status and stderr hash for each run, and the computed desktop and
mobile median performance scores. One failing report fails the release even
when the median remains above 90.

Each run owns a unique Chrome profile and temporary directory. A timeout
terminates the complete process tree and cleans that directory with bounded
retries. On Windows, the wrapper accepts only the reviewed Chrome-launcher
`EPERM` cleanup signature for its exact owned directory, only with process
status 1 and a fully passing report. Any additional diagnostic line or
different nonzero status remains a hard error. The receipt records every
accepted cleanup warning.
