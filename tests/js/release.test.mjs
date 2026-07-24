import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';
import {
  packagedSnapshotPath,
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
  const inventory = await readJson(
    path.join(
      repositoryRoot,
      'plugin-dist',
      'robbottx-core-0.1.8.inventory.json'
    )
  );
  const snapshot = await readJson(snapshotPath);

  assert.match(plugin, /\* Version:\s+0\.1\.8/);
  assert.match(plugin, /define\('ROBBOTTX_CORE_VERSION', '0\.1\.8'\)/);
  assert.equal(block.version, '0.1.8');
  assert.equal(manifest.version, '0.1.8');
  assert.ok(manifest.download_url.endsWith('robbottx-core-0.1.8.zip'));
  assert.equal(manifest.download_sha256, inventory.zip_sha256);
  assert.equal(manifest.download_size, inventory.zip_bytes);
  assert.ok(
    manifest.inventory_url.endsWith(
      'robbottx-core-0.1.8.inventory.json'
    )
  );
  assert.equal(manifest.record_hash, snapshot.payload_sha256);
});

test('healthcheck reports the integrity-bound catalog record without internal state', async () => {
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

  assert.ok(controller.includes("'record_hash'"));
  assert.ok(controller.includes("'record_state'"));
  assert.ok(controller.includes("'documentation_reviewed'"));
  assert.ok(!controller.includes("'snapshot_id'"));
  assert.ok(!controller.includes("'snapshot_hash'"));
  assert.ok(!controller.includes("'projection_state'"));
  assert.match(snapshot.payload_sha256, /^[0-9a-f]{64}$/);
  assert.equal(snapshot.projection_state, 'candidate');
});

test('the deployed record is executable PHP, not a directly readable JSON asset', async () => {
  const packaged = await fs.readFile(packagedSnapshotPath, 'utf8');
  const publicJsonPath = packagedSnapshotPath.replace(/\.php$/, '.json');

  assert.match(packaged, /^<\?php/);
  assert.ok(packaged.includes("if (! defined('ABSPATH'))"));
  assert.ok(packaged.includes("<<<'ROBBOTTX_RECORD'"));
  assert.ok(!packaged.includes('"projection_state"'));
  assert.ok(!packaged.includes('"snapshot_id"'));
  assert.ok(!packaged.includes('"source_dataset_id"'));
  assert.ok(!packaged.includes('"source_dataset_sha256"'));
  await assert.rejects(fs.access(publicJsonPath));
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

test('the hosting root carries the exact public robots policy', async () => {
  const robots = await fs.readFile(
    path.join(repositoryRoot, 'hosting', 'robots.txt'),
    'utf8'
  );

  assert.equal(
    robots.replaceAll('\r\n', '\n'),
    [
      'User-agent: *',
      'Disallow:',
      '',
      'Sitemap: https://robbottx.com/wp-sitemap.xml',
      ''
    ].join('\n')
  );
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
  for (const socialTag of [
    'og:title',
    'og:type',
    'og:url',
    'og:description',
    'og:site_name',
    'og:locale',
    'twitter:card',
    'twitter:title',
    'twitter:description'
  ]) {
    assert.ok(seo.includes(socialTag));
  }
  assert.ok(seo.includes('$rankMathFacebookHandled'));
  assert.ok(seo.includes('$rankMathTwitterHandled'));
  assert.ok(seo.includes("'summary'"));
  assert.ok(!seo.includes('summary_large_image'));
  assert.ok(!seo.includes(' — '));
});

test('dynamic engineering identifiers wrap on narrow viewports', async () => {
  const assets = await fs.readFile(
    path.join(
      repositoryRoot,
      'wp-content',
      'plugins',
      'robbottx-core',
      'src',
      'Presentation',
      'Assets.php'
    ),
    'utf8'
  );

  assert.ok(assets.includes('#rbtx-featured-configuration-title'));
  assert.ok(assets.includes('overflow-wrap: anywhere'));
  assert.ok(assets.includes('ROBBOTTX_CORE_VERSION'));
});

test('homepage asset discipline preserves every commerce context', async () => {
  const assets = await fs.readFile(
    path.join(
      repositoryRoot,
      'wp-content',
      'plugins',
      'robbottx-core',
      'src',
      'Presentation',
      'Assets.php'
    ),
    'utf8'
  );
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

  assert.ok(plugin.includes("'dequeueUnusedFrontPageAssets'"));
  assert.ok(plugin.includes('PHP_INT_MAX'));
  assert.ok(assets.includes('is_admin()'));
  assert.ok(assets.includes('is_front_page()'));
  for (const conditional of [
    'is_woocommerce',
    'is_shop',
    'is_product',
    'is_product_taxonomy',
    'is_cart',
    'is_checkout',
    'is_account_page',
    'is_wc_endpoint_url'
  ]) {
    assert.ok(assets.includes(`'${conditional}'`));
  }
  for (const handle of [
    'searchandfilter',
    'woocommerce-layout',
    'woocommerce-smallscreen',
    'woocommerce-general',
    'woocommerce-blocktheme',
    'woocommerce-inline',
    'brands-styles',
    'wc-blocks-style',
    'site-reviews',
    'wc-add-to-cart',
    'woocommerce',
    'sourcebuster-js',
    'wc-order-attribution'
  ]) {
    assert.ok(assets.includes(`'${handle}'`));
  }
  assert.ok(assets.includes('wp_dequeue_style'));
  assert.ok(assets.includes('wp_dequeue_script'));
  assert.ok(!assets.includes('wp_deregister_'));
  for (const sharedHandle of [
    "'jquery'",
    "'jquery-core'",
    "'jquery-migrate'",
    "'jquery-blockui'",
    "'js-cookie'"
  ]) {
    assert.ok(!assets.includes(sharedHandle));
  }
});

test('theme release preserves the catalog container and exposes deployment identity', async () => {
  const style = await fs.readFile(
    path.join(
      repositoryRoot,
      'wp-content',
      'themes',
      'robbottx',
      'style.css'
    ),
    'utf8'
  );
  const functions = await fs.readFile(
    path.join(
      repositoryRoot,
      'wp-content',
      'themes',
      'robbottx',
      'functions.php'
    ),
    'utf8'
  );
  const frontPage = await fs.readFile(
    path.join(
      repositoryRoot,
      'wp-content',
      'themes',
      'robbottx',
      'templates',
      'front-page.html'
    ),
    'utf8'
  );

  assert.ok(style.includes('Version: 0.1.6'));
  assert.ok(style.includes('.rbtx-golden-slice'));
  assert.ok(style.includes('.rbtx-featured-configuration'));
  assert.ok(functions.includes("'wp_body_open'"));
  assert.ok(functions.includes('<!-- robbottx-theme:%s -->'));
  assert.ok(frontPage.includes('rbtx-main rbtx-atlas-home'));
  assert.ok(frontPage.includes('wp:robbottx/flagship-system'));
  assert.ok(!frontPage.includes('wp:robbottx/golden-slice'));
});

test('theme ships an original cache-versioned favicon with guarded output', async () => {
  const themeRoot = path.join(
    repositoryRoot,
    'wp-content',
    'themes',
    'robbottx'
  );
  const functions = await fs.readFile(
    path.join(themeRoot, 'functions.php'),
    'utf8'
  );
  const favicon = await fs.readFile(
    path.join(themeRoot, 'assets', 'favicon.svg'),
    'utf8'
  );
  const receipt = await readJson(
    path.join(themeRoot, 'ASSET-LICENSES.json')
  );

  assert.ok(functions.includes('has_site_icon()'));
  assert.ok(functions.includes("get_theme_file_uri('assets/favicon.svg')"));
  assert.ok(functions.includes('add_query_arg('));
  assert.ok(functions.includes('rel="icon"'));
  assert.match(favicon, /<svg\b/);
  assert.ok(favicon.includes('#52e8d6'));
  assert.ok(
    !/<script\b|<foreignObject\b|(?:href|src)\s*=\s*["']https?:/i.test(
      favicon
    )
  );
  assert.equal(receipt.version, '0.1.6');
  assert.equal(receipt.assets[0].path, 'assets/favicon.svg');
});

test('public configuration copy uses established catalog language', async () => {
  const view = await fs.readFile(
    path.join(
      repositoryRoot,
      'wp-content',
      'plugins',
      'robbottx-core',
      'views',
      'golden-slice.php'
    ),
    'utf8'
  );
  const snapshot = await readJson(snapshotPath);
  const publicText = JSON.stringify({
    status: snapshot.payload.status.label,
    summary: snapshot.payload.summary,
    compatibility: snapshot.payload.compatibility,
    disclosures: snapshot.payload.disclosures
  });

  for (const required of [
    'Featured system configuration',
    'RobbottX record ID',
    'Sourced technical claims',
    'Compatibility across 10 technical areas.',
    'Technical documents and sources'
  ]) {
    assert.ok(view.includes(required));
  }
  assert.equal(snapshot.payload.status.label, 'Documentation reviewed');
  assert.ok(publicText.includes('Requires validation'));
  assert.ok(!view.includes("$payload['blockers']"));
  assert.ok(!view.includes('$blockers'));
  assert.ok(!/—/u.test(view + publicText));
  assert.ok(
    !/Golden vertical slice|Research candidate|Canonical ID|Unsupported passes|Publication gate|Engineering closure|open items/i.test(
      view + publicText
    )
  );
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
  assert.ok(template.includes("'/run-{{ROUTE_TOKEN}}'"));
  assert.ok(template.includes("str_contains($zip_url, '?')"));
  assert.ok(template.includes("'?nlcb=' . time()"));
  assert.ok(template.includes("base64_decode('{{RAW_ZIP_URL_B64}}'"));
  assert.ok(template.includes("$expected_sha256 = '{{ZIP_SHA256}}'"));
  assert.ok(template.includes('$expected_size = {{ZIP_SIZE}}'));
  assert.ok(template.includes('download_url($zip_url, 300)'));
  assert.ok(template.includes("hash_file('sha256', $package)"));
  assert.ok(template.includes('is_wp_error($result)'));
  assert.ok(template.includes('$result !== true'));
  assert.ok(template.includes('get_plugin_data($plugin_path'));
  assert.ok(template.includes('$installed_version !== $expected_version'));
  assert.ok(template.includes("do_action('litespeed_purge_all')"));
  assert.ok(template.includes('wp_cache_flush()'));
});

test('deploy cleanup retries deletion and independently proves route absence', async () => {
  const driver = await fs.readFile(
    path.join(repositoryRoot, 'scripts', 'deploy-wordpress.py'),
    'utf8'
  );

  assert.ok(driver.includes('def delete_temporary_snippet('));
  assert.ok(driver.includes('def find_snippet_ids_by_name('));
  assert.ok(driver.includes('def cleanup_temporary_snippets('));
  assert.ok(driver.includes('def prove_deploy_route_absent('));
  assert.ok(driver.includes('def require_deploy_route_absent('));
  assert.ok(driver.includes('def require_route_not_registered('));
  assert.ok(driver.includes('def verify_plugin_zip('));
  assert.ok(driver.includes('attempts: int = 3'));
  assert.ok(driver.includes('f"{snippet_id}?_method=DELETE"'));
  assert.ok(driver.includes('Pre-create verification'));
  assert.ok(driver.includes('expected_sha256=args.zip_sha256'));
  assert.ok(driver.includes('snippet_name,'));
  assert.ok(driver.includes('snippet_deleted'));
  assert.ok(driver.includes('and route_absent'));
  assert.ok(driver.includes('and legacy_route_absent'));
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
  assert.ok(template.includes("current_user_can('update_themes')"));
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

test('package builders enforce reviewed inventories and emit checksums', async () => {
  const pluginBuilder = await fs.readFile(
    path.join(repositoryRoot, 'scripts', 'build-plugin-zip.py'),
    'utf8'
  );
  const themeBuilder = await fs.readFile(
    path.join(repositoryRoot, 'scripts', 'build-theme-zip.py'),
    'utf8'
  );

  assert.ok(pluginBuilder.includes('ALLOWED_APPLICATION_FILES'));
  assert.ok(pluginBuilder.includes('VENDORED_TREE_SHA256'));
  assert.ok(pluginBuilder.includes('Unexpected plugin package files'));
  assert.ok(pluginBuilder.includes('.inventory.json'));
  assert.ok(pluginBuilder.includes('"zip_sha256": digest'));
  assert.ok(themeBuilder.includes('ALLOWED_THEME_FILES'));
  assert.ok(themeBuilder.includes('Unexpected theme package files'));
  assert.ok(themeBuilder.includes('.inventory.json'));
  assert.ok(themeBuilder.includes('"zip_sha256": digest'));
});

test('flagship release is interactive, count-bound, original, and public-safe', async () => {
  const pluginRoot = path.join(
    repositoryRoot,
    'wp-content',
    'plugins',
    'robbottx-core'
  );
  const renderer = await fs.readFile(
    path.join(pluginRoot, 'src', 'Presentation', 'FlagshipSystemRenderer.php'),
    'utf8'
  );
  const view = await fs.readFile(
    path.join(pluginRoot, 'views', 'flagship-system.php'),
    'utf8'
  );
  const script = await fs.readFile(
    path.join(pluginRoot, 'assets', 'flagship-system.js'),
    'utf8'
  );
  const style = await fs.readFile(
    path.join(pluginRoot, 'assets', 'flagship-system.css'),
    'utf8'
  );
  const block = await readJson(
    path.join(pluginRoot, 'blocks', 'flagship-system', 'block.json')
  );
  const assetReceipt = await readJson(
    path.join(pluginRoot, 'assets', 'ASSET-LICENSES.json')
  );
  const image = await fs.readFile(
    path.join(pluginRoot, 'assets', 'flagship-concept-v1.png')
  );
  const publicSource = [renderer, view, script, style].join('\n');

  assert.equal(block.name, 'robbottx/flagship-system');
  assert.equal(block.version, '0.1.8');
  assert.equal([...renderer.matchAll(/'id'\s*=>/g)].length, 8);
  for (const runtimeCount of [
    "$counts['systems'] !== 8",
    "$counts['assemblies'] !== 28",
    "$counts['components'] !== 48",
    "$counts['materials'] !== 12"
  ]) {
    assert.ok(renderer.includes(runtimeCount));
  }
  for (const marker of [
    'interactive-bom-pyramid',
    'rbtx-flagship-stage',
    'data-rbtx-canvas',
    'data-rbtx-system',
    'data-rbtx-build-brief',
    'Concept system'
  ]) {
    assert.ok(view.includes(marker));
  }
  for (const behavior of [
    'pointerdown',
    'pointermove',
    'wheel',
    'keydown',
    'prefers-reduced-motion',
    'IntersectionObserver'
  ]) {
    assert.ok(script.includes(behavior));
  }
  assert.ok(!/https?:\/\//i.test(script + style));
  assert.ok(!/\u2014/u.test(publicSource));
  assert.ok(!/\bRBTX-(?:RS|RP)-\d{3}\b/i.test(publicSource));
  assert.ok(!/\b(?:Tesla|Atlas|Figure|Unitree|Apptronik)\b/.test(publicSource));
  assert.equal(assetReceipt.version, '0.1.8');
  assert.equal(assetReceipt.assets[0].bytes, image.byteLength);
  assert.equal(
    assetReceipt.assets[0].sha256,
    crypto.createHash('sha256').update(image).digest('hex')
  );
});
