import fs from 'node:fs/promises';
import path from 'node:path';
import { repositoryRoot } from '../lib/canonical.mjs';

const themeRoot = path.join(
  repositoryRoot,
  'wp-content',
  'themes',
  'robbottx'
);
const requiredFiles = [
  'style.css',
  'theme.json',
  'functions.php',
  'templates/index.html',
  'templates/front-page.html',
  'parts/header.html',
  'parts/footer.html'
];

for (const relative of requiredFiles) {
  await fs.access(path.join(themeRoot, relative));
}

const themeJson = JSON.parse(
  await fs.readFile(path.join(themeRoot, 'theme.json'), 'utf8')
);
if (themeJson.version !== 3) {
  throw new Error('theme.json must use version 3.');
}
if (!String(themeJson.$schema).includes('/wp/6.9/')) {
  throw new Error('theme.json must target the minimum-supported WordPress 6.9 schema.');
}

const style = await fs.readFile(path.join(themeRoot, 'style.css'), 'utf8');
for (const header of [
  'Theme Name: RobbottX Precision Atlas',
  'Version: 0.1.2',
  'Requires at least: 6.9',
  'Requires PHP: 8.3'
]) {
  if (!style.includes(header)) {
    throw new Error(`Theme header is missing: ${header}`);
  }
}
const readme = await fs.readFile(path.join(themeRoot, 'readme.txt'), 'utf8');
const assetLicenses = JSON.parse(
  await fs.readFile(path.join(themeRoot, 'ASSET-LICENSES.json'), 'utf8')
);
if (!readme.includes('Version: 0.1.2') || assetLicenses.version !== '0.1.2') {
  throw new Error('Theme style, readme, and asset receipt versions must agree.');
}
if (/url\(\s*['"]?https?:/i.test(style) || /@import/i.test(style)) {
  throw new Error('Theme CSS must not import remote assets.');
}

const files = await fs.readdir(path.join(themeRoot, 'templates'));
for (const filename of files.filter((file) => file.endsWith('.html'))) {
  const markup = await fs.readFile(path.join(themeRoot, 'templates', filename), 'utf8');
  const openings = [...markup.matchAll(/<!-- wp:/g)].length;
  const selfClosing = [...markup.matchAll(/\/-->/g)].length;
  const closings = [...markup.matchAll(/<!-- \/wp:/g)].length;
  if (openings !== selfClosing + closings) {
    throw new Error(`${filename}: unbalanced WordPress block comments.`);
  }
  const mainElements = [...markup.matchAll(/<main\b/gi)].length;
  const mainTargets = [...markup.matchAll(/<main\b[^>]*\bid=["']main-content["']/gi)].length;
  if (mainElements !== 1 || mainTargets !== 1) {
    throw new Error(
      `${filename}: exactly one <main id="main-content"> landmark is required.`
    );
  }
}

const publicMarkup = await Promise.all(
  [
    'parts/header.html',
    'parts/footer.html',
    'patterns/home-precision-atlas.php',
    'patterns/home-methodology.php'
  ].map((relative) => fs.readFile(path.join(themeRoot, relative), 'utf8'))
);
const combined = publicMarkup.join('\n');
if (/href\s*=\s*["']#main-content["']/i.test(combined)) {
  throw new Error(
    'Theme-owned skip links are forbidden; WordPress core inserts the single main landmark link.'
  );
}
if (/href\s*=\s*["']#["']/i.test(combined)) {
  throw new Error('Placeholder href="#" links are forbidden.');
}
if (/example\.com/i.test(combined)) {
  throw new Error('Placeholder domains are forbidden.');
}

process.stdout.write(
  `Block theme valid: ${requiredFiles.length} required files, ` +
    `${files.length} templates, no remote assets.\n`
);
