# Proprietary design boundary

## Decision

This GitHub repository is public. It contains public website code, generic data
contracts, validators, synthetic fixtures, vendor-backed research records, and
deliberately approved public snapshots.

Original RobbottX engineering records belong in a separate private engineering
repository or access-controlled PLM and object store.

## Private-only material

- unpublished mission profiles and requirements;
- original CAD, URDF, SDFormat, OpenUSD, collision models, mass properties, and
  native 3D sources;
- engineering BOMs, exact costs, supplier negotiations, alternates, and sourcing
  risk;
- calculations, simulations, unprocessed measurements, failures, calibration, and production
  evidence;
- safety hazards, residual risk, threat models, vulnerabilities, privacy design,
  AI evaluation data, and incident records;
- manufacturing processes, tolerances, fixtures, work instructions, quality
  controls, and nonconformance;
- patent, design, trade-secret, ownership, freedom-to-operate, and pre-disclosure
  material.

Deleting a file later does not remove it from public Git history.

## Allowed public material

- generic versioned schemas and validators;
- synthetic examples that cannot be mistaken for a real product;
- third-party facts whose provenance, scope, rights, and public use are approved;
- an explicit public snapshot containing only approved fields and claims;
- rights-cleared GLB derivatives and static fallbacks whose exact path, byte
  size, SHA-256, public revision, rights state, and disclosure approval are
  recorded in `PUBLIC-ASSET-DISCLOSURE.json`. Every GLB approval names one exact
  static fallback in `paired_asset_path`; the fallback approval names that GLB
  back, and both approvals use the same public revision;
- public WordPress, search, feed, graph, and commerce projections built from that
  snapshot.

## Export flow

```text
private reviewed source
  -> explicit disclosure authorization
  -> field whitelist and redaction
  -> claim, rights, safety, legal, and commercial review
  -> deterministic public snapshot and hash
  -> whole-repository and archive scan
  -> hash-bound scan receipt
  -> deployment of the same verified artifact bytes
  -> independent public release verification
```

There is no automatic whole-record export. An approved public field does not
approve adjacent private fields. Public corrections begin in the private source,
then regenerate the approved snapshot.

The public repository inventory includes both the current Git index and the
tracked and non-ignored working tree. When their bytes differ, both views receive
the same complete format, archive, JSON, 3D, and disclosure-approval checks.
Local dependencies, generated previews, caches, and the ignored `work/`
directory are outside the Git publication set. The gate rejects unknown file
types, oversized uninspected content, unsafe or nested archives, native
engineering formats, private identifiers in paths or content, and unapproved 3D
derivatives. JSON is parsed with duplicate keys and non-finite numbers rejected;
control manifests and snapshots have bounded reads; GLB JSON and BIN chunks are
scanned; and ZIP stored/deflated member ranges must be consumed exactly. The gate
also emits the aggregate repository digest, exact release ZIP hashes, public
snapshot hash, asset-approval manifest hash, Git commit, and dirty state.

This scanner is defense in depth. It does not decide that arbitrary engineering
content is safe. Public structured data must also pass the versioned publication
schema and field whitelist. Code review is the approval boundary for changes to
the asset disclosure manifest and publication contracts.

## Release rejection

Reject a release when a public surface, distribution archive, or generated asset
contains:

- private classification or object-storage paths;
- private reference-system IDs;
- hazard, verification-plan, engineering-BOM, threat, raw-test, or supplier-cost
  records;
- native CAD, robotics simulation, database, model-weight, or raw telemetry files;
- a target, calculation, simulation, prototype result, certification, price,
  stock, or delivery state presented beyond its approved evidence.
