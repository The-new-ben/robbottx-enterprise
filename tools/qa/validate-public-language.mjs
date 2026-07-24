import fs from 'node:fs/promises';
import path from 'node:path';
import {
  packagedSnapshotPath,
  readJson,
  repositoryRoot,
  snapshotPath
} from '../lib/canonical.mjs';

const publicFiles = [
  'wp-content/themes/robbottx/parts/header.html',
  'wp-content/themes/robbottx/parts/footer.html',
  'wp-content/themes/robbottx/patterns/home-precision-atlas.php',
  'wp-content/themes/robbottx/patterns/home-methodology.php',
  'wp-content/themes/robbottx/templates/404.html',
  'wp-content/themes/robbottx/templates/search.html',
  'wp-content/themes/robbottx/style.css',
  'wp-content/plugins/robbottx-core/views/golden-slice.php',
  'wp-content/plugins/robbottx-core/views/flagship-system.php',
  'wp-content/plugins/robbottx-core/src/Presentation/FlagshipSystemRenderer.php',
  'wp-content/plugins/robbottx-core/assets/flagship-system.css',
  'wp-content/plugins/robbottx-core/assets/flagship-system.js',
  'wp-content/plugins/robbottx-core/assets/ASSET-LICENSES.json',
  'wp-content/plugins/robbottx-core/src/Presentation/Seo.php',
  'wp-content/plugins/robbottx-core/readme.txt',
  'wp-content/plugins/robbottx-core/blocks/golden-slice/block.json',
  'wp-content/plugins/robbottx-core/blocks/flagship-system/block.json',
  'plugin-dist/robbottx-core.json',
  'wp-content/themes/robbottx/readme.txt',
  'wp-content/themes/robbottx/ASSET-LICENSES.json',
  'tools/build-preview.mjs'
];

const forbidden = [
  ['em dash character', /\u2014/u],
  ['em dash', /—/u],
  ['golden vertical slice', /\bgolden vertical slice\b/i],
  ['visible golden slice', />[^<]*\bgolden slice\b[^<]*</i],
  ['research candidate', /\bresearch candidate\b/i],
  ['canonical ID', /\bcanonical ID\b/i],
  ['unsupported passes', /\bunsupported passes\b/i],
  ['publication gate', /\bpublication gate\b/i],
  ['engineering closure', /\bengineering closure\b/i],
  ['open items', /\bopen items\b/i],
  ['no hidden unknowns', /\bno hidden unknowns\b/i],
  ['evidence slogan', /\bevidence,\s*not decoration\b/i],
  ['project language', /\bproject,\s*never duplicate\b/i],
  ['launch language', /\b(?:english launch|launch phase|source-ready)\b/i],
  ['unfinished-platform language', /\b(?:beta|roadmap|coming soon|work in progress|evolving project)\b/i],
  ['unsupported search coverage', /\b(?:searchable atlas|part number,\s*task,\s*protocol|native language\s*[·|]\s*interfaces)\b/i],
  ['unsupported absolute', /\bevery layer\b/i],
  ['unfinished page language', /\b(?:not yet passed|exact revisions pending)\b/i],
  ['generated filler', /\b(?:at its core|in today'?s landscape|unlock|delve|seamless|revolutionary|game-changing)\b/i],
  ['not just construction', /\bnot just\b[\s\S]{0,100}\bbut\b/i]
];

const failures = [];

for (const relative of publicFiles) {
  const content = await fs.readFile(path.join(repositoryRoot, relative), 'utf8');

  for (const [label, pattern] of forbidden) {
    if (pattern.test(content)) {
      failures.push(`${relative}: ${label}`);
    }
  }
}

const snapshot = await readJson(snapshotPath);
const publicPayload = snapshot.payload;
const payloadText = JSON.stringify(publicPayload);

for (const [label, pattern] of forbidden) {
  if (pattern.test(payloadText)) {
    failures.push(`publication payload: ${label}`);
  }
}

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

for (const required of [
  'Featured system configuration',
  'Documentation reviewed',
  'RobbottX record ID',
  'Sourced technical claims',
  'Compatibility across 10 technical areas.',
  'Technical documents and sources'
]) {
  const source = required === 'Documentation reviewed' ? payloadText : view;
  if (!source.includes(required)) {
    failures.push(`required public language missing: ${required}`);
  }
}

if (view.includes("$payload['blockers']") || view.includes('$blockers')) {
  failures.push('public view renders internal publication blockers');
}

for (const [label, pattern] of [
  ['candidate state', /\bcandidate\b/i],
  ['research mission', /\bresearch mission\b/i],
  ['publication vocabulary', /\bpublication\b/i],
  ['projection vocabulary', /\bprojection\b/i],
  ['snapshot vocabulary', /\bsnapshot\b/i]
]) {
  if (pattern.test(payloadText)) {
    failures.push(`deployable record payload: ${label}`);
  }
}

const packagedSnapshot = await fs.readFile(packagedSnapshotPath, 'utf8');
if (!packagedSnapshot.startsWith('<?php')) {
  failures.push('deployable record must be an executable PHP resource');
}
if (!packagedSnapshot.includes("if (! defined('ABSPATH'))")) {
  failures.push('deployable record lacks a direct-request guard');
}
try {
  await fs.access(packagedSnapshotPath.replace(/\.php$/, '.json'));
  failures.push('directly readable publication JSON remains in the plugin');
} catch {
  // Expected: the deployable record is not a public static JSON file.
}

if (failures.length > 0) {
  throw new Error(
    `Public language validation failed:\n- ${[...new Set(failures)].join('\n- ')}`
  );
}

process.stdout.write(
  `Public language valid: ${publicFiles.length} surfaces and publication payload checked.\n`
);
