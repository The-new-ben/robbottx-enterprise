import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import test from 'node:test';
import { repositoryRoot } from '../../tools/lib/canonical.mjs';

const harness = path.join(
  repositoryRoot,
  'tests',
  'php',
  'assets-policy-harness.php'
);

const run = (scenario) => {
  const result = spawnSync('php', [harness, scenario], {
    cwd: repositoryRoot,
    encoding: 'utf8'
  });

  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
};

test('catalog homepage removes only the reviewed top-level assets', () => {
  const result = run('front');

  assert.deepEqual(result.styles, [
    'searchandfilter',
    'woocommerce-layout',
    'woocommerce-smallscreen',
    'woocommerce-general',
    'woocommerce-blocktheme',
    'woocommerce-inline',
    'brands-styles',
    'wc-blocks-style',
    'site-reviews'
  ]);
  assert.deepEqual(result.scripts, [
    'wc-add-to-cart',
    'woocommerce',
    'sourcebuster-js',
    'wc-order-attribution',
    'site-reviews'
  ]);
});

test('asset discipline leaves admin, ordinary pages, and commerce untouched', () => {
  for (const scenario of [
    'admin',
    'normal',
    'is_woocommerce',
    'is_shop',
    'is_product',
    'is_product_taxonomy',
    'is_cart',
    'is_checkout',
    'is_account_page',
    'is_wc_endpoint_url'
  ]) {
    assert.deepEqual(run(scenario), { styles: [], scripts: [] }, scenario);
  }
});
