# ADR 0001: Clean RobbottX foundation

Status: accepted  
Date: 2026-07-23

## Decision

Create a new repository, original block theme, and new core integration plugin.
Use the inherited live WordPress installation only as an environment to audit
and progressively replace.

## Exclusions

- Retired catalog CSVs and placeholder images.
- Inherited visual design and template code.
- Unsupported catalog claims.
- A WordPress-only canonical data model.

## Consequences

- Early delivery is slower than repainting the current site, but every released
  element can participate in the long-term graph, compatibility, commerce, 3D,
  lifecycle, and planetary architecture.
- The live installation must be changed through small versioned packages because
  the owner prohibits staging and backups.
- Existing users, orders, settings, and operational services remain untouched
  until a separately verified migration or replacement requires them.

