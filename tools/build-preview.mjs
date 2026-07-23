import fs from 'node:fs/promises';
import path from 'node:path';
import {
  readJson,
  repositoryRoot,
  snapshotPath
} from './lib/canonical.mjs';

const themeRoot = path.join(
  repositoryRoot,
  'wp-content',
  'themes',
  'robbottx'
);
const outputPath = path.join(
  repositoryRoot,
  '.artifacts',
  'preview',
  'index.html'
);

const escapeHtml = (value) =>
  String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');

async function themeFragment(relativePath) {
  return (await fs.readFile(path.join(themeRoot, relativePath), 'utf8'))
    .replace(/<\?php[\s\S]*?\?>/g, '')
    .replace(/<!--\s*\/?wp:[\s\S]*?-->/g, '')
    .trim();
}

function renderGoldenSlice(snapshot) {
  const payload = snapshot.payload;
  const { identity, status, evidence_summary: evidence } = payload;
  const specifications = payload.specifications
    .map(
      (specification) => `
        <div>
          <dt>${escapeHtml(specification.label)}</dt>
          <dd>${escapeHtml(specification.value)}</dd>
        </div>`
    )
    .join('');
  const compatibility = payload.compatibility
    .map(
      (result) => `
        <article class="rbtx-compatibility-card rbtx-state--${escapeHtml(result.state)}">
          <div class="rbtx-card-topline">
            <h4>${escapeHtml(result.label)}</h4>
            <span>${escapeHtml(result.state_label)}</span>
          </div>
          <p>${escapeHtml(result.basis)}</p>
          <p class="rbtx-condition">${escapeHtml(result.conditions)}</p>
        </article>`
    )
    .join('');
  const sources = payload.sources
    .map(
      (source) => `
        <li>
          <a href="${escapeHtml(source.url)}" rel="external noopener">${escapeHtml(source.publisher)} <span aria-hidden="true">↗</span></a>
          <span>${escapeHtml(source.locator)}</span>
          <code>${escapeHtml(source.response_sha256.slice(0, 12))}…</code>
        </li>`
    )
    .join('');
  const disclosures = payload.disclosures
    .map((disclosure) => `<li>${escapeHtml(disclosure)}</li>`)
    .join('');

  return `
    <section class="rbtx-featured-configuration" id="featured-configuration" aria-labelledby="rbtx-featured-configuration-title">
      <div class="rbtx-section-heading">
        <div>
          <p class="rbtx-eyebrow">Featured system configuration</p>
          <h2 id="rbtx-featured-configuration-title">${escapeHtml(identity.name)}</h2>
        </div>
        <span class="rbtx-status rbtx-status--documented"><span aria-hidden="true"></span>${escapeHtml(status.label)}</span>
      </div>
      <p class="rbtx-lede">${escapeHtml(payload.summary)}</p>
      <dl class="rbtx-evidence-ribbon" aria-label="Evidence summary">
        <div><dt>RobbottX record ID</dt><dd><code>${escapeHtml(identity.canonical_id)}</code></dd></div>
        <div><dt>Source documents</dt><dd>${escapeHtml(evidence.primary_sources)}</dd></div>
        <div><dt>Sourced technical claims</dt><dd>${escapeHtml(evidence.assertion_count)}</dd></div>
        <div><dt>System relationships</dt><dd>${escapeHtml(evidence.relationship_count)}</dd></div>
        <div><dt>Last reviewed</dt><dd><time datetime="${escapeHtml(status.verified_on)}">${escapeHtml(status.verified_on)}</time></dd></div>
      </dl>
      <div class="rbtx-slice-grid">
        <div class="rbtx-panel">
          <p class="rbtx-panel-kicker">Manufacturer-published specifications</p>
          <dl class="rbtx-spec-list">${specifications}</dl>
          <p class="rbtx-caption">Values are normalized for comparison. Review the source documents and compatibility conditions below.</p>
        </div>
        <div class="rbtx-panel rbtx-panel--dark">
          <p class="rbtx-panel-kicker">Compatibility notes</p>
          <h3>Confirm the exact Waffle variant before integration.</h3>
          <p>Manufacturer compatibility text names Waffle, while its assembly documentation names Waffle Pi. Check exact revisions, mounting hardware, power, pinout, stability, and safety for the intended application.</p>
          <div class="rbtx-verdict"><span>Configuration status</span><strong>Requires application validation</strong></div>
        </div>
      </div>
      <div class="rbtx-compatibility" id="verify">
        <div class="rbtx-subheading"><p class="rbtx-eyebrow">Compatibility</p><h3>Compatibility across 10 technical areas.</h3></div>
        <div class="rbtx-compatibility-grid">${compatibility}</div>
      </div>
      <div class="rbtx-sources" id="methodology">
        <div class="rbtx-subheading"><p class="rbtx-eyebrow">Technical documents and sources</p><h3>Manufacturer sources for this configuration.</h3></div>
        <ol class="rbtx-source-list">${sources}</ol>
      </div>
      <ul class="rbtx-disclosures" aria-label="Important disclosures">${disclosures}</ul>
    </section>`;
}

const snapshot = await readJson(snapshotPath);
const [header, home, methodology, footer] = await Promise.all([
  themeFragment(path.join('parts', 'header.html')),
  themeFragment(path.join('patterns', 'home-precision-atlas.php')),
  themeFragment(path.join('patterns', 'home-methodology.php')),
  themeFragment(path.join('parts', 'footer.html'))
]);

const document = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex,nofollow">
  <title>RobbottX Precision Atlas: local preview</title>
  <link rel="stylesheet" href="../../wp-content/themes/robbottx/style.css">
</head>
<body>
  <header>${header}</header>
  <main class="rbtx-main" id="main-content">
    ${home}
    ${renderGoldenSlice(snapshot)}
    ${methodology}
  </main>
  <footer>${footer}</footer>
</body>
</html>
`;

await fs.mkdir(path.dirname(outputPath), { recursive: true });
await fs.writeFile(outputPath, document, 'utf8');
process.stdout.write(`Built ${outputPath}\n`);
