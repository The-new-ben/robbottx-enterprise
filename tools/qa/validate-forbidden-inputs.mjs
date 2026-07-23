import fs from 'node:fs/promises';
import path from 'node:path';
import { repositoryRoot } from '../lib/canonical.mjs';

const ignoredDirectories = new Set([
  '.git',
  '.artifacts',
  'node_modules'
]);
const forbiddenNames = [
  /\.csv$/i,
  /\.sql$/i,
  /\.sqlite$/i,
  /\.pem$/i,
  /\.key$/i,
  /\.p12$/i,
  /^\.env(?:\.|$)/i,
  /cookies/i,
  /credentials/i,
  /legacy-catalog/i,
  /old-catalog/i,
  /robot-catalog/i,
  /catalog-images/i,
  /handoff.*\.zip/i
];
const textExtensions = new Set([
  '.css',
  '.html',
  '.js',
  '.json',
  '.md',
  '.mjs',
  '.php',
  '.py',
  '.txt',
  '.yaml',
  '.yml'
]);
const secretPatterns = [
  /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/,
  /\bgh[oprsu]_[A-Za-z0-9_]{30,}\b/,
  /\bWP_APP_PASSWORD\s*=\s*['"][^'"]+['"]/,
  /\b(?:api[_-]?key|secret|password)\s*[:=]\s*['"][A-Za-z0-9/+_=.-]{16,}['"]/i
];

async function walk(directory) {
  const files = [];

  for (const entry of await fs.readdir(directory, { withFileTypes: true })) {
    if (entry.isDirectory() && ignoredDirectories.has(entry.name)) {
      continue;
    }

    const fullPath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await walk(fullPath)));
    } else if (entry.isFile()) {
      files.push(fullPath);
    }
  }

  return files;
}

const failures = [];
const files = await walk(repositoryRoot);

for (const filePath of files) {
  const relative = path.relative(repositoryRoot, filePath).replaceAll('\\', '/');
  const isPolicyFile = relative === 'governance/FORBIDDEN-INPUTS.txt';

  if (!isPolicyFile && forbiddenNames.some((pattern) => pattern.test(relative))) {
    failures.push(`Forbidden path: ${relative}`);
  }

  if (textExtensions.has(path.extname(filePath).toLowerCase())) {
    const content = await fs.readFile(filePath, 'utf8');
    for (const pattern of secretPatterns) {
      if (pattern.test(content)) {
        failures.push(`Possible secret in ${relative}: ${pattern.source}`);
      }
    }
  }
}

if (failures.length > 0) {
  throw new Error(`Forbidden-input validation failed:\n- ${failures.join('\n- ')}`);
}

process.stdout.write(`Forbidden-input scan passed across ${files.length} files.\n`);
