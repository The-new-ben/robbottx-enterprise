import {
  buildSnapshot,
  fixturePath,
  packagedSnapshotPath,
  readJson,
  snapshotPath,
  stableStringify,
  writeJson
} from './lib/canonical.mjs';
import fs from 'node:fs/promises';
import path from 'node:path';

const dataset = await readJson(fixturePath);
const snapshot = buildSnapshot(dataset);
await writeJson(snapshotPath, snapshot);
await fs.mkdir(path.dirname(packagedSnapshotPath), { recursive: true });
await fs.writeFile(
  packagedSnapshotPath,
  `<?php

declare(strict_types=1);

if (! defined('ABSPATH')) {
    exit;
}

return json_decode(
    <<<'ROBBOTTX_RECORD'
${stableStringify(snapshot, 2)}
ROBBOTTX_RECORD,
    true,
    512,
    JSON_THROW_ON_ERROR
);
`,
  'utf8'
);

process.stdout.write(
  `Built ${snapshot.snapshot_id} (${snapshot.payload_sha256})\n`
);
