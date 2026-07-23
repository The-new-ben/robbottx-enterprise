import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';
import {
  readJson,
  repositoryRoot,
  snapshotPath
} from '../../tools/lib/canonical.mjs';

test('plugin version header, constant, manifest, and block agree', async () => {
  const plugin = await fs.readFile(
    path.join(
      repositoryRoot,
      'wp-content',
      'plugins',
      'robbottx-core',
      'robbottx-core.php'
    ),
    'utf8'
  );
  const block = await readJson(
    path.join(
      repositoryRoot,
      'wp-content',
      'plugins',
      'robbottx-core',
      'blocks',
      'golden-slice',
      'block.json'
    )
  );
  const manifest = await readJson(
    path.join(repositoryRoot, 'plugin-dist', 'robbottx-core.json')
  );

  assert.match(plugin, /\* Version:\s+0\.1\.2/);
  assert.match(plugin, /define\('ROBBOTTX_CORE_VERSION', '0\.1\.2'\)/);
  assert.equal(block.version, '0.1.2');
  assert.equal(manifest.version, '0.1.2');
  assert.ok(manifest.download_url.endsWith('robbottx-core-0.1.2.zip'));
});

test('healthcheck source reports the integrity-bound snapshot', async () => {
  const controller = await fs.readFile(
    path.join(
      repositoryRoot,
      'wp-content',
      'plugins',
      'robbottx-core',
      'src',
      'Rest',
      'HealthController.php'
    ),
    'utf8'
  );
  const snapshot = await readJson(snapshotPath);

  assert.ok(controller.includes("'snapshot_hash'"));
  assert.match(snapshot.payload_sha256, /^[0-9a-f]{64}$/);
  assert.equal(snapshot.projection_state, 'candidate');
});

test('plugin emits a versioned rendered-body marker for deploy verification', async () => {
  const plugin = await fs.readFile(
    path.join(
      repositoryRoot,
      'wp-content',
      'plugins',
      'robbottx-core',
      'src',
      'Plugin.php'
    ),
    'utf8'
  );

  assert.ok(plugin.includes("add_action('wp_footer'"));
  assert.ok(plugin.includes('<!-- robbottx-core:'));
});

test('homepage SEO is deterministic and evidence-conservative', async () => {
  const seo = await fs.readFile(
    path.join(
      repositoryRoot,
      'wp-content',
      'plugins',
      'robbottx-core',
      'src',
      'Presentation',
      'Seo.php'
    ),
    'utf8'
  );

  assert.ok(seo.includes("'rank_math/frontend/description'"));
  assert.ok(seo.includes("'rank_math/json_ld'"));
  assert.ok(seo.includes('$rankMathDescriptionHandled'));
  assert.ok(seo.includes('$rankMathJsonLdHandled'));
  assert.ok(seo.includes('PHP_INT_MAX'));
  assert.ok(seo.includes('<meta name="description"'));
  assert.ok(seo.includes("'@type'       => 'WebSite'"));
  assert.ok(seo.includes("'@type'       => 'WebPage'"));
  assert.ok(!seo.includes("'@type'       => 'Organization'"));
});

test('temporary deploy route is capability-gated and cache-purging', async () => {
  const template = await fs.readFile(
    path.join(
      repositoryRoot,
      'scripts',
      'templates',
      'deploy-route.php.txt'
    ),
    'utf8'
  );

  assert.ok(template.includes("current_user_can('update_plugins')"));
  assert.ok(template.includes("'overwrite_package' => true"));
  assert.ok(template.includes("?nlcb=' . time()"));
  assert.ok(template.includes("do_action('litespeed_purge_all')"));
  assert.ok(template.includes('wp_cache_flush()'));
});

test('deploy cleanup retries deletion and independently proves route absence', async () => {
  const driver = await fs.readFile(
    path.join(repositoryRoot, 'scripts', 'deploy-wordpress.py'),
    'utf8'
  );

  assert.ok(driver.includes('def delete_temporary_snippet('));
  assert.ok(driver.includes('def prove_deploy_route_absent('));
  assert.ok(driver.includes('attempts: int = 3'));
  assert.ok(driver.includes('f"{snippet_id}?_method=DELETE"'));
  assert.ok(driver.includes('snippet_deleted and route_absent'));
  assert.ok(driver.includes('Temporary deploy route cleanup was not proven.'));
});

test('one-time theme bootstrap is gated for hardened external cleanup', async () => {
  const template = await fs.readFile(
    path.join(
      repositoryRoot,
      'scripts',
      'templates',
      'deploy-theme-route.php.txt'
    ),
    'utf8'
  );

  assert.ok(template.includes("current_user_can('install_themes')"));
  assert.ok(template.includes("current_user_can('switch_themes')"));
  assert.ok(template.includes('new Theme_Upgrader($skin)'));
  assert.ok(template.includes("'overwrite_package' => true"));
  assert.ok(template.includes('$result !== true'));
  assert.ok(template.includes("?nlcb=' . time()"));
  assert.ok(template.includes("get('Version') !== $expected_version"));
  assert.ok(template.includes('switch_theme($theme_slug)'));
  assert.ok(template.includes("do_action('litespeed_purge_all')"));
  assert.ok(template.includes('wp_cache_flush()'));
});
