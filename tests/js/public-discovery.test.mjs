import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import test from 'node:test';
import { repositoryRoot } from '../../tools/lib/canonical.mjs';

const harness = path.join(
  repositoryRoot,
  'tests',
  'php',
  'public-discovery-harness.php'
);

test('public discovery excludes inherited records without hiding commerce', () => {
  const result = spawnSync('php', [harness], {
    cwd: repositoryRoot,
    encoding: 'utf8'
  });

  assert.equal(result.status, 0, result.stderr);

  const receipt = JSON.parse(result.stdout);
  assert.equal(receipt.status, 'PASS');
  assert.equal(receipt.assertions, 169);
});
