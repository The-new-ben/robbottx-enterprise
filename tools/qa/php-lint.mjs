import { execFileSync } from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import { repositoryRoot } from '../lib/canonical.mjs';

const roots = [
  path.join(repositoryRoot, 'wp-content', 'plugins', 'robbottx-core'),
  path.join(repositoryRoot, 'wp-content', 'themes', 'robbottx')
];
const routeTemplates = [
  path.join(repositoryRoot, 'scripts', 'templates', 'deploy-route.php.txt'),
  path.join(repositoryRoot, 'scripts', 'templates', 'deploy-theme-route.php.txt'),
  path.join(
    repositoryRoot,
    'scripts',
    'templates',
    'deploy-robots-route.php.txt'
  ),
  path.join(
    repositoryRoot,
    'scripts',
    'templates',
    'configure-commerce-route.php.txt'
  )
];

async function walk(directory) {
  const files = [];
  for (const entry of await fs.readdir(directory, { withFileTypes: true })) {
    const fullPath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await walk(fullPath)));
    } else if (entry.isFile() && entry.name.endsWith('.php')) {
      files.push(fullPath);
    }
  }
  return files;
}

const files = (await Promise.all(roots.map(walk))).flat().sort();
const failures = [];

for (const filePath of files) {
  try {
    execFileSync('php', ['-l', filePath], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe']
    });
  } catch (error) {
    failures.push(
      `${path.relative(repositoryRoot, filePath)}: ` +
        String(error.stderr || error.stdout || error.message).trim()
    );
  }
}

for (const templatePath of routeTemplates) {
  const source = await fs.readFile(templatePath, 'utf8');
  const instantiated = source.replace(
    /\{\{([A-Z0-9_]+)\}\}/g,
    (_match, name) => (
      name === 'ZIP_SIZE' || name === 'ROBOTS_SIZE'
        ? '1'
        : 'rbtxtemplatevalue'
    )
  );
  try {
    execFileSync('php', ['-l'], {
      encoding: 'utf8',
      input: `<?php\n${instantiated}`,
      stdio: ['pipe', 'pipe', 'pipe']
    });
  } catch (error) {
    failures.push(
      `${path.relative(repositoryRoot, templatePath)}: ` +
        String(error.stderr || error.stdout || error.message).trim()
    );
  }
}

if (failures.length > 0) {
  throw new Error(`PHP lint failed:\n- ${failures.join('\n- ')}`);
}

process.stdout.write(
  `PHP lint passed for ${files.length} files and ` +
    `${routeTemplates.length} route templates.\n`
);
