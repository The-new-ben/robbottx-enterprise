=== RobbottX Core ===
Contributors: robbottx
Requires at least: 6.9
Tested up to: 7.0
Requires PHP: 8.3
Stable tag: 0.1.2
License: GPLv2 or later

Projection-only publishing gates and evidence components for RobbottX.

== Description ==

Registers the minimal public projection types, integrity-checks deterministic
publication snapshots, renders the golden-slice evidence component, blocks
canonical publication when required snapshot metadata is absent, exposes a
public version healthcheck, and provides a guarded update-manifest fallback.

This plugin does not import the retired catalog, perform remote ingestion,
create engineering source-of-truth tables, delete data, or modify commerce.
