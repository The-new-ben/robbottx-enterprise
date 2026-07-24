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
  'assets/favicon.svg',
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
  'Version: 0.1.6',
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
if (!readme.includes('Version: 0.1.6') || assetLicenses.version !== '0.1.6') {
  throw new Error('Theme style, readme, and asset receipt versions must agree.');
}
if (/url\(\s*['"]?https?:/i.test(style) || /@import/i.test(style)) {
  throw new Error('Theme CSS must not import remote assets.');
}

const favicon = await fs.readFile(
  path.join(themeRoot, 'assets', 'favicon.svg'),
  'utf8'
);
if (
  !/<svg\b/i.test(favicon) ||
  /<script\b|<foreignObject\b|(?:href|src)\s*=\s*["']https?:/i.test(favicon)
) {
  throw new Error('Theme favicon must be a local, inert SVG.');
}

const toLinear = (channel) => {
  const normalized = channel / 255;
  return normalized <= 0.04045
    ? normalized / 12.92
    : ((normalized + 0.055) / 1.055) ** 2.4;
};
const luminance = (hex) => {
  const channels = hex
    .slice(1)
    .match(/.{2}/g)
    .map((channel) => Number.parseInt(channel, 16));
  return (
    0.2126 * toLinear(channels[0]) +
    0.7152 * toLinear(channels[1]) +
    0.0722 * toLinear(channels[2])
  );
};
const contrast = (foreground, background) => {
  const lighter = Math.max(luminance(foreground), luminance(background));
  const darker = Math.min(luminance(foreground), luminance(background));
  return (lighter + 0.05) / (darker + 0.05);
};
if (contrast('#56666a', '#f7f7f2') < 5.5) {
  throw new Error('Muted small text must retain at least 5.5:1 contrast.');
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
const frontPage = await fs.readFile(
  path.join(themeRoot, 'templates', 'front-page.html'),
  'utf8'
);
if (!frontPage.includes('wp:robbottx/flagship-system')) {
  throw new Error('Homepage must render the plugin-owned flagship system block.');
}
if (
  frontPage.includes('wp:pattern {"slug":"robbottx/home-precision-atlas"}') ||
  frontPage.includes('wp:robbottx/golden-slice')
) {
  throw new Error('Homepage still renders the superseded atlas or featured configuration.');
}
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
