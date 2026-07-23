import {
  buildSnapshot,
  fixturePath,
  readJson,
  snapshotPath,
  writeJson
} from './lib/canonical.mjs';

const dataset = await readJson(fixturePath);
const snapshot = buildSnapshot(dataset);
await writeJson(snapshotPath, snapshot);

process.stdout.write(
  `Built ${snapshot.snapshot_id} (${snapshot.payload_sha256})\n`
);
