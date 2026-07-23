# ADR 0002: WordPress is a public projection

Status: accepted  
Date: 2026-07-23

## Decision

WordPress owns public URLs, editorial composition, navigation, SEO rendering,
accounts, and future WooCommerce transactions. It does not own canonical
engineering identity, assertions, evidence, BOMs, compatibility rules, 3D asset
rights, or offer history.

Every projected record carries a language-neutral external ID, immutable
snapshot version, payload hash, and publication state. A slug or WordPress post
ID never becomes engineering identity. Projection tables and caches must be
rebuildable.

## First-slice implementation

The repository uses a versioned JSON canonical fixture and deterministic
publication snapshot while the canonical service hosting path is unresolved.
This is a deliberately small implementation of the target
PostgreSQL-plus-object-storage contract, not a decision to make JSON or
WordPress the long-term system of record.

## Consequences

- Unsupported or stale snapshots cannot publish as canonical entity pages.
- Search, graph, WordPress, feeds, and future AI indexes receive the same
  approved snapshot.
- Engineering corrections occur in the canonical review path and then
  regenerate projections.
- The initial plugin creates no custom engineering database tables.
