# Public language benchmark

Reviewed 2026-07-23. This receipt records language patterns, not current stock
or pricing.

## Established patterns

### RBTX

Official component pages use `Part No.`, `Variants`, `Usual delivery time`,
`Downloads`, `Build A Complete System`, and regional availability notices.
RobbottX adopts the direct catalog nouns, but does not adopt broad
`compatibility guaranteed` language.

- https://rbtx.com/en-US/components/cobots/fairino-fr5-6dof-922mm-5kg/fr5-ip54-standard
- https://rbtx.com/en-US/components/humanoid/unitree-g1-humanoid-robot-version-edu-01/g1-edu-u8

### DigiKey and Mouser

Distributor pages separate lifecycle, product attributes, source documents,
availability, stock, lead time, and suggested replacements. Mouser also uses
`Verify Status with Factory` when lifecycle information is unclear.

- https://www.mouser.com/en/apihome/
- https://www.mouser.com/en/ProductDetail/TE-Connectivity-DEUTSCH/D38999-26FC98PA-LC

### MISUMI

Configuration language follows a clear order: select specifications and
dimensions, generate the part number, download CAD where available, then add to
the component list or cart.

- https://us.misumi-ec.com/guide/category/ecatalog/use_cad.html
- https://my.misumi-ec.com/guide/category/ecatalog/detail.html

### Rockwell Automation

Rockwell separates compatibility comparison, available versions, lifecycle
status, dependencies, issues, release notes, firmware, software, and
replacement research.

- https://www.rockwellautomation.com/en-us/support/product/product-compatibility-migration.html
- https://compatibility.rockwellautomation.com/Pages/home.aspx

### Universal Robots

UR technical pages use direct specification tables. Its real compatibility
program tests mechanical, electrical, software, and documentation scope before
granting an approved product status. RobbottX does not use `plug-and-play`,
`full compatibility`, or `certified` without equivalent evidence.

- https://www.universal-robots.com/manuals/EN/HTML/SW5_19/Content/prod-usr-man/complianceUR10e/H_g5_sections/appendix_g5/tech_spec_sheet.htm
- https://www.universal-robots.com/partner/partner-program/

### NVIDIA Robotics

NVIDIA uses stable platform sections such as Overview, Use Cases, Technology,
Ecosystem, Resources, and Next Steps. RobbottX adopts clear category labels,
but does not adopt full-stack superlatives or broad production-readiness
claims.

- https://www.nvidia.com/en-us/industries/robotics/

## RobbottX adoption

- Product facts use Specifications and Technical data.
- Compatibility is stated per system layer and version.
- Evidence appears as Technical documents and sources.
- Supplier information is separate from technical identity.
- Missing information uses Not confirmed, Not provided by manufacturer, or
  Availability not confirmed.
- Public pages sound like maintained reference records, not internal project
  status reports.
- Search copy names only fields present in the live index and covered by query
  tests. Until then, the interface says `Search RobbottX`.
- Public-surface review includes health JSON, readmes, manifests, stylesheet
  headers, block metadata, and downloadable records, not only rendered body copy.
- Unscoped absolutes such as `every layer`, `complete catalog`, and `all
  components` are rejected unless the measured scope is stated.
