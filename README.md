# RobbottX Enterprise

RobbottX is an evidence-backed global robotics knowledge, engineering,
configuration, procurement, lifecycle, and governance platform.

This repository is a clean implementation. The retired catalog CSV files,
placeholder images, inherited public design, and inherited WordPress content
are not source material.

## Repository boundaries

- `wp-content/themes/robbottx/` - original block theme and public design system.
- `wp-content/plugins/robbottx-core/` - WordPress projection, publishing gates,
  dynamic blocks, and administrative integration.
- `packages/` - canonical schemas, fixtures, compatibility rules, and
  publication contracts that do not belong in WordPress posts or taxonomies.
- `docs/` - mission, decisions, research receipts, data contracts, release
  evidence, and QA records.
- `tools/` and `tests/` - deterministic build and local verification.

## Non-negotiable model

Human navigation uses a hierarchy. Engineering reuse uses a versioned knowledge
graph. Compatibility uses explicit dimension-specific rules. WordPress is a
public projection, not the canonical engineering system of record.

## First executable slice

The candidate mobile-manipulator dataset exercises the path from official
source evidence to a deterministic WordPress projection. It deliberately
remains non-eligible for canonical publication until exact hardware/software
revisions, compatibility gaps, asset rights, and commercial scope are frozen.

Run:

```text
npm run qa
```

Generated local visual preview:

```text
.artifacts/preview/index.html
```

## Production constraint

The owner requires direct production work with no staging environment and no
backup. This is an explicit project override. Releases must therefore be small,
locally validated, additive, reversible through versioned package activation,
and immediately verified live. This repository must not store secrets,
database exports, credentials, customer records, or production media.
