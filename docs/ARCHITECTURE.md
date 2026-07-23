# Architecture baseline

## System layers

1. **Canonical transactional store**
   - entities, names, revisions, assertions, evidence, BOMs, rules, offers,
     serialized units, and change history;
   - authoritative writes and immutable identifiers.
2. **Knowledge-graph projection**
   - typed, versioned relationships for membership, where-used, alternatives,
     compatibility evidence, software dependencies, and assemblies.
3. **Compatibility service**
   - dimension-specific inputs, rule-set versions, conditions, evidence,
     explanations, unresolved unknowns, and engineering-review states.
4. **Search and discovery projections**
   - lexical, multilingual, faceted, graph, vector, feed, and sitemap indexes.
5. **3D and simulation projections**
   - licensed source geometry; GLB for the web; STEP/CAD, URDF/Xacro, SDFormat,
     and OpenUSD for their appropriate engineering workflows.
6. **WordPress projection**
   - public editorial/SEO pages, accounts, commerce, curated taxonomies,
     publication gates, structured data, and API connections.
7. **Lifecycle and enterprise integrations**
   - supplier feeds, RFQ/procurement, manufacturing, ownership, fleets,
     maintenance, incidents, PLM/ERP, private catalogs, and data APIs.

## Human hierarchy

`materials -> parts -> components -> modules -> versioned BOMs/configurations ->
robots/cells/robotized appliances -> factories/fleets/habitats/colonies`

The hierarchy controls navigation and SEO. It does not erase many-to-many
engineering relationships.

## Compatibility dimensions

- mechanical and geometry;
- electrical and power;
- connector and pinout;
- protocol and communications;
- firmware, software, operating system, and licensing;
- performance and timing;
- thermal and environmental;
- safety, regulatory, and certification context;
- supply-chain, lifecycle, and regional availability;
- mission and planetary environment.

Result states are: confirmed, conditional, adapter required,
version-constrained, incompatible, unverified, conflicting evidence,
engineering review required, or not applicable.
