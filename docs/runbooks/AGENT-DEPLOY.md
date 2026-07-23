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
  --require-marker "Featured system configuration"
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

## Deploy the plugin

The deliberate deploy command is:

```text
python scripts/deploy-wordpress.py \
  --version <version> \
  --zip-url <verified-public-raw-zip-url> \
  --zip-size <exact-public-byte-size> \
  --zip-sha256 <exact-public-sha256> \
  --record-hash <exact-record-payload-sha256> \
  --package-marker "<release-specific source marker>" \
  --old-body-marker "<!-- robbottx-core:<previous-version> -->" \
  --execute
```

The driver verifies administrator authority, the public update manifest,
versioned inventory, exact ZIP bytes, hash, root, embedded version, record
hash, and release marker. The one-use callback downloads the package again and
checks its hash and size before installation. The driver requires route and
snippet-name absence before creation, uses a unique route and snippet name,
runs `Plugin_Upgrader` with strict installed-version checks, verifies the
independent healthcheck and rendered body, finds and deletes the snippet by
exact unique name even when the create response is malformed, and proves the
former route returns WordPress JSON `rest_no_route`.

## Deploy the theme

Run the theme driver without `--execute` first. This performs the authenticated
authority, public artifact, unique-route, legacy-route, and snippet-name
preflight without creating a snippet or changing WordPress:

```text
npm run deploy:theme -- \
  --version <version> \
  --zip-url <verified-public-versioned-theme-zip-url> \
  --zip-size <exact-public-byte-size> \
  --zip-sha256 <exact-public-sha256> \
  --package-marker "<release-specific theme source marker>" \
  --new-body-marker "<marker rendered only by the new theme>" \
  --old-body-marker "<marker rendered only by the previous theme>"
```

Repeat the exact reviewed command with `--execute` only after preflight passes.
The driver accepts only `https://robbottx.com` as the WordPress origin and
only the canonical versioned theme ZIP under this repository's
`raw.githubusercontent.com/.../main/plugin-dist/` path.
The driver downloads and validates the exact ZIP locally, then makes the
one-use WordPress callback download and hash-check the same bytes before
installation. The callback body is advisory because a proxy may alter it.
Release truth comes from the authenticated core themes REST endpoint confirming
the exact standalone active block theme and version, plus the rendered new
marker inside the HTML body with the old marker absent.
Evidence may therefore report `callback_confirmed: false` while the deployment
is independently verified; callback bodies and callback errors are never
copied into evidence.

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
