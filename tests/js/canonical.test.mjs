import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildSnapshot,
  fixturePath,
  readJson,
  sha256,
  stableStringify,
  validateCanonicalSchema,
  validateDataset
} from '../../tools/lib/canonical.mjs';

test('candidate dataset is internally consistent', async () => {
  const dataset = await readJson(fixturePath);
  assert.deepEqual(validateCanonicalSchema(dataset), []);
  assert.deepEqual(validateDataset(dataset), []);
});

test('JSON Schema validation rejects missing required assertion review state', async () => {
  const dataset = await readJson(fixturePath);
  const broken = structuredClone(dataset);
  delete broken.assertions[0].review_status;

  const errors = validateDataset(broken);
  assert.ok(
    errors.some((error) =>
      error.includes(
        "schema /assertions/0/review_status: must have required property 'review_status'"
      )
    )
  );
});

test('JSON Schema validation enforces declared date-time formats', async () => {
  const dataset = await readJson(fixturePath);
  const broken = structuredClone(dataset);
  broken.created_at = 'not-a-date';

  const errors = validateDataset(broken);
  assert.ok(
    errors.some((error) =>
      error.includes('schema /created_at: must match format "date-time"')
    )
  );
});

test('JSON Schema validation rejects unknown fields and invalid evidence URIs', async () => {
  const dataset = await readJson(fixturePath);
  const broken = structuredClone(dataset);
  broken.entities[0].unreviewed_field = true;
  broken.evidence[0].url = 'not a URI';

  const errors = validateDataset(broken);
  assert.ok(
    errors.some((error) =>
      error.includes(
        'schema /entities/0/unreviewed_field: must NOT have additional properties'
      )
    )
  );
  assert.ok(
    errors.some((error) =>
      error.includes('schema /evidence/0/url: must match format "uri"')
    )
  );
});

test('graph edges reject unresolved subject and object endpoints', async () => {
  const dataset = await readJson(fixturePath);
  const broken = structuredClone(dataset);
  broken.edges[0].subject_id =
    'RBTX:R:019f8f7d-ffff-7fff-8fff-ffffffffffff';
  broken.edges[1].object_id =
    'RBTX:E:019f8f7d-eeee-7eee-8eee-eeeeeeeeeeee';

  const errors = validateDataset(broken);
  assert.ok(
    errors.some((error) =>
      error.includes(
        `edge ${broken.edges[0].edge_id}: missing subject ${broken.edges[0].subject_id}`
      )
    )
  );
  assert.ok(
    errors.some((error) =>
      error.includes(
        `edge ${broken.edges[1].edge_id}: missing object ${broken.edges[1].object_id}`
      )
    )
  );
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
