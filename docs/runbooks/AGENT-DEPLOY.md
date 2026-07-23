# RobbottX agent deployment runbook

The globally installed `wordpress-agent-deploy` skill is mandatory.

## Release endpoints

- Plugin manifest:
  `https://raw.githubusercontent.com/The-new-ben/robbottx-enterprise/main/plugin-dist/robbottx-core.json`
- Versioned plugin ZIP:
  `https://raw.githubusercontent.com/The-new-ben/robbottx-enterprise/main/plugin-dist/robbottx-core-<version>.zip`
- Public healthcheck:
  `https://robbottx.com/wp-json/robbottx/v1/healthcheck`
- Temporary deploy route:
  `https://robbottx.com/wp-json/agentdeploy/v1/run`

The temporary route must return 404 before and after every deployment.

## Local build

```text
npm run qa
python scripts/build-plugin-zip.py \
  --plugin-dir wp-content/plugins/robbottx-core \
  --slug robbottx-core \
  --version 0.1.2 \
  --main-file robbottx-core.php \
  --version-constant ROBBOTTX_CORE_VERSION \
  --output-dir plugin-dist \
  --require-marker "RobbottX kept this projection as a draft"
python scripts/build-theme-zip.py \
  --theme-dir wp-content/themes/robbottx \
  --slug robbottx \
  --version 0.1.1 \
  --output-dir plugin-dist
```

Reopen and inspect both ZIPs. The theme is a one-time static chrome install;
subsequent evolving behavior ships in `robbottx-core`.

## Runtime secrets

The deploy driver reads only:

- `WP_BASE_URL`
- `WP_USER`
- `WP_APP_PASSWORD`

They are runtime environment variables, never repository files. Do not print
them. Do not store them in release evidence.

## Deploy

The deliberate deploy command is:

```text
python scripts/deploy-wordpress.py \
  --version <version> \
  --zip-url <verified-public-raw-zip-url> \
  --execute
```

The driver verifies the administrator identity and ZIP, creates the temporary
Code Snippets route, runs `Plugin_Upgrader`, checks the independent healthcheck
and rendered body, deletes the snippet in a `finally` path, and requires the
former route to return 404.
