import path from 'node:path';
import {
  buildSnapshot,
  fixturePath,
  readJson,
  repositoryRoot,
  sha256,
  snapshotPath,
  stableStringify,
  validateDataset
} from '../lib/canonical.mjs';

const schema = await readJson(
  path.join(
    repositoryRoot,
    'packages',
    'contracts',
    'schema',
    'canonical-slice.schema.json'
  )
);
const dataset = await readJson(fixturePath);
const storedSnapshot = await readJson(snapshotPath);

if (schema.$schema !== 'https://json-schema.org/draft/2020-12/schema') {
  throw new Error('Canonical schema must use JSON Schema 2020-12.');
}

const errors = validateDataset(dataset);
if (errors.length > 0) {
  throw new Error(`Dataset validation failed:\n- ${errors.join('\n- ')}`);
}

const expectedSnapshot = buildSnapshot(dataset);
if (stableStringify(storedSnapshot) !== stableStringify(expectedSnapshot)) {
  throw new Error('Stored publication snapshot is stale or non-deterministic.');
}

if (
  storedSnapshot.payload_sha256 !==
  sha256(stableStringify(storedSnapshot.payload))
) {
  throw new Error('Publication payload SHA-256 does not match.');
}

process.stdout.write(
  `Contracts valid: ${dataset.entities.length} entities, ` +
    `${dataset.assertions.length} assertions, ` +
    `${dataset.compatibility.results.length} compatibility dimensions.\n`
);
