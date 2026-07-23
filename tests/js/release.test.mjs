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

  assert.match(plugin, /\* Version:\s+0\.1\.1/);
  assert.match(plugin, /define\('ROBBOTTX_CORE_VERSION', '0\.1\.1'\)/);
  assert.equal(block.version, '0.1.1');
  assert.equal(manifest.version, '0.1.1');
  assert.ok(manifest.download_url.endsWith('robbottx-core-0.1.1.zip'));
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
