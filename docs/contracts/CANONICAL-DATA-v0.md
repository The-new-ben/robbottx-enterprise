# Canonical data contract v0

## Identity

Canonical IDs are opaque, language-neutral UUIDv7 values with typed prefixes:

- `RBTX:E:` entity
- `RBTX:R:` entity revision
- `RBTX:EV:` evidence
- `RBTX:A:` assertion
- `RBTX:ED:` graph edge
- `RBTX:C:` configuration revision
- `RBTX:B:` BOM version
- `RBTX:BR:` compatibility rule
- `RBTX:CA:` compatibility assessment
- `RBTX:OF:` offer
- `RBTX:AS:` 3D asset
- `RBTX:S:` publication snapshot

Names, model codes, slugs, taxonomies, WordPress IDs, and seller SKUs never
become canonical identifiers.

## Records

- `Entity` establishes durable identity and type.
- `EntityRevision` separates physical or software revisions from editorial
  corrections.
- `Label` preserves official native, international, translated,
  transliterated, alias, and deprecated forms with BCP-47 language tags.
- `Evidence` records publisher, source type, URL, date, exact locator,
  response checksum, language, jurisdiction, and rights state.
- `Assertion` preserves raw and normalized values, units, conditions, evidence,
  claim class, confidence, reviewer state, and validity.
- `Edge` expresses typed, versioned, evidence-backed relationships.
- `ConfigurationRevision` freezes purpose, environment, BOM, software, rules,
  and checksum.
- `BOMVersion` and `BOMItem` preserve hierarchy, role, quantity, alternates,
  mounting/interface references, and provenance.
- `CompatibilityRuleVersion` is executable, reviewable, versioned, and tested.
- `CompatibilityAssessment` binds exact revisions to per-dimension results and
  never promotes unknown to pass.
- `OfferSnapshot` separates seller/region/time commercial state from product
  identity.
- `Asset3D` binds rights, source, checksum, exact revision, units, axes, scale,
  LOD, validation, and accessible fallback.

## Evidence classes

1. `manufacturer_primary`
2. `standard_or_regulator`
3. `authorized_distributor`
4. `independent_test`
5. `calculation_or_simulation`
6. `community_lead`

Community evidence can start research but cannot independently publish a
technical, compatibility, safety, certification, price, or stock claim.
Conflicts coexist and remain visible; values are not silently averaged.

## Compatibility dimensions and states

Dimensions:

- mechanical/geometry
- electrical/power
- connector/pinout
- protocol/communications
- firmware/software/licensing
- performance/timing
- thermal/environmental
- safety/regulatory
- lifecycle/supply/region
- mission/planetary environment

States:

- `confirmed`
- `conditional`
- `adapter_required`
- `version_constrained`
- `incompatible`
- `unverified`
- `conflicting_evidence`
- `engineering_review_required`
- `not_applicable`

An overall result cannot be `confirmed` while a required dimension is unknown,
conflicting, version-constrained without a frozen version, or awaiting
engineering review.

## System boundary

```text
primary evidence
  -> reviewed canonical write path
  -> PostgreSQL target + checksum-addressed object storage
  -> immutable publication snapshot / versioned read API
  -> WordPress, search, graph, feed, AI, analytics, and 3D projections
```

The repository fixture is the executable v0 contract while production hosting
is unresolved. It is not the long-term storage decision.
