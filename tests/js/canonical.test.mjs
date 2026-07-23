import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildSnapshot,
  fixturePath,
  readJson,
  sha256,
  stableStringify,
  validateDataset
} from '../../tools/lib/canonical.mjs';

test('candidate dataset is internally consistent', async () => {
  const dataset = await readJson(fixturePath);
  assert.deepEqual(validateDataset(dataset), []);
});

test('publication snapshot is deterministic and hash-bound', async () => {
  const dataset = await readJson(fixturePath);
  const left = buildSnapshot(dataset);
  const right = buildSnapshot(dataset);

  assert.equal(stableStringify(left), stableStringify(right));
  assert.equal(left.payload_sha256, sha256(stableStringify(left.payload)));
  assert.equal(
    left.snapshot_id,
    'RBTX:S:019f8ff9-bcc4-7872-ab79-4a4d594d0aa3'
  );
  assert.notEqual(
    left.snapshot_id,
    'RBTX:S:019f8fee-8c61-715b-b234-5afe045fe9f9'
  );
  assert.notEqual(
    left.snapshot_id,
    'RBTX:S:019f8fe1-e3ee-7e99-98a6-72ada29c119d'
  );
  assert.notEqual(
    left.snapshot_id,
    'RBTX:S:019f8f7d-996f-7937-a365-c1dd812cb0db'
  );
  assert.equal(left.generated_at, '2026-07-23T17:15:36.522Z');
});

test('unknown compatibility cannot become a public pass', async () => {
  const dataset = await readJson(fixturePath);
  const unsafe = structuredClone(dataset);
  unsafe.publication.eligible = true;
  unsafe.publication.indexability = 'index';
  unsafe.dataset_status = 'approved';
  unsafe.compatibility.overall_state = 'confirmed';

  const errors = validateDataset(unsafe);
  assert.ok(errors.some((error) => error.includes('blocking publication issues')));
});

test('numeric assertions always carry units', async () => {
  const dataset = await readJson(fixturePath);
  const broken = structuredClone(dataset);
  const numeric = broken.assertions.find(
    (assertion) => typeof assertion.value.normalized === 'number'
  );
  numeric.value.unit = null;

  const errors = validateDataset(broken);
  assert.ok(errors.some((error) => error.includes('numeric value requires unit')));
});
