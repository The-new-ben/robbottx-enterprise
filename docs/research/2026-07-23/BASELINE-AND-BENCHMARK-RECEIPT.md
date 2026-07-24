# Baseline and visual benchmark receipt

Date: 2026-07-23  
Scope: authenticated read-only production inventory and first-fold visual
benchmarking. No live data, settings, content, themes, plugins, users, orders,
payments, or files were changed.

## Production identity

- Canonical public origin: `https://robbottx.com/`
- WordPress environment: production, single site, HTTPS
- WordPress: 7.0.2
- PHP: 8.4.18, FPM
- Web server: nginx 1.31.2
- Database engine: MariaDB 10.6.25
- Site language: `en_US`
- Search-engine discouragement: disabled
- Pretty permalink structure: not configured
- WordPress users: 1

Sensitive database identifiers, credentials, paths unrelated to package
deployment, and account information are intentionally not recorded here.

## Live theme and plugin baseline

Active theme:

- Robotics Gadgets Review 1.0 (`robotic-gadgets-theme`)
- Declared author: OpenAI Assistant
- Declared author URL: placeholder `example.com`
- Classic theme features; no block-theme foundation

Plugin state:

- 16 active plugins
- 2 inactive plugins
- 17 updates surfaced in WordPress
- Auto-updates disabled
- One active global code snippet

Material active-plugin categories:

- WooCommerce and two payment integrations
- Rank Math SEO
- ACF and Custom Post Type UI
- Classic Editor and Advanced Editor Tools
- Search & Filter
- Site Reviews
- WP All Import and two CSV import tools
- WP File Manager
- Legacy Robot CSV Importer and Robots Catalog Shortcode

Operational observations:

- WooCommerce reports the store as coming soon.
- Opcode cache reports full, with no free interned-string memory.
- The current stack has overlapping import, custom-type, review, search, and
  catalog mechanisms. None is accepted as the canonical RobbottX architecture.
- Plugin updates will not be applied as an incidental first step because direct
  production plus no backup creates an uncontrolled compatibility risk.

## Public-page findings

The current homepage fails as a viable enterprise baseline:

- Generic site identity: “New WordPress Site.”
- Intended hero HTML is printed visibly as raw text.
- English and Hebrew are mixed without a coherent locale or direction contract.
- Default “Hello world!” content remains public.
- Navigation is effectively absent.
- Category, review, community, and commerce sections are placeholders.
- Several sections use near-white text on a near-white background.
- Large empty areas create no information hierarchy.
- Placeholder links use `#`.
- The mobile first fold is dominated by raw markup and broken line wrapping.
- The public experience is visibly affected by inherited theme and content
  defects; the new design must not be a restyle of this structure.

The screenshots were captured while authenticated, so the WordPress toolbar is
visible. It is an evidence artifact, not part of the desired public design.

## Screenshots

Live baseline:

- `screenshots/live-home-desktop-1440x1000.jpg`
- `screenshots/live-home-mobile-390x844.jpg`

Current benchmark families:

- Premium product:
  `screenshots/benchmark-premium-apple-macbook-pro-1440x1000.jpg`
- Robotics ecosystem:
  `screenshots/benchmark-ecosystem-nvidia-robotics-1440x1000.jpg`
- Engineering commerce:
  `screenshots/benchmark-commerce-digikey-products-1440x1000.jpg`
- Closest direct marketplace:
  `screenshots/benchmark-direct-rbtx-1440x1000.jpg`

Capture limitations:

- The mobile full-page capture exceeded the browser capture deadline, so the
  exact 390×844 viewport is preserved instead.
- Apple displayed a regional-choice banner in the captured viewport.
- A Tesla Optimus URL returned an official 404 and was rejected as a useful
  benchmark.

## Benchmark observations

### Apple MacBook Pro

- Restrained global navigation.
- Product-family focus and cinematic hero treatment.
- Progressive disclosure instead of showing every specification at once.
- Strong use of negative space and controlled typography.

Use the hierarchy and pacing principle, not Apple’s trade dress, typography,
black product framing, or interaction copies.

### NVIDIA Robotics

- Clear ecosystem and industry context.
- Robot-led imagery paired with a concise mission statement.
- Strong separation among technology stack, applications, partners, and
  resources.

RobbottX needs equal ecosystem clarity while remaining vendor-neutral and adding
evidence, configuration, procurement, and lifecycle actions.

### DigiKey

- Search is the primary global action.
- Dense taxonomy remains scannable.
- Part-number discovery and category counts establish immediate inventory
  credibility.

RobbottX must support similar discovery depth while adding where-used,
compatibility, robot/configuration context, evidence, and simulation meaning.

### RBTX

- Immediate robotics identity.
- Strong global search and demonstration CTA.
- Bold application-oriented hero language.
- Commerce and expert help appear early.

RobbottX must exceed the opaque “compatible” promise with dimension-specific
results, evidence, conditions, exact revisions, and visible unknowns.

## Resulting design decisions

- Build an original identity rather than blend the four references.
- Lead with a meaningful robot/system configuration, not a generic catalog
  slogan.
- Keep the top navigation simple: Discover, Build, Verify, Source, Learn.
- Make universal search and configuration entry points visible immediately.
- Reveal the pyramid progressively: system → modules → parts → evidence.
- Pair cinematic system imagery with engineering facts and concrete next
  actions.
- Use an original mineral/industrial palette rather than Apple monochrome,
  NVIDIA green, DigiKey red, or RBTX purple/orange.
- Let dense tables, evidence, offers, and BOMs appear in task-specific panels
  below a clean overview.
- Preserve crawlable text, links, specifications, and static visual fallbacks
  when 3D or motion is unavailable.

## Immediate architecture consequences

1. Configure canonical descriptive permalinks before any new public entity URLs
   become authoritative.
2. Release a new block theme and core projection plugin as separate versioned
   packages.
3. Keep the first production release additive and reversible by activation;
   do not delete the inherited theme, plugins, content, users, or commerce data.
4. Do not activate new engineering entity pages until the first canonical
   publication snapshot passes evidence and indexability gates.
5. Treat the current 17 updates and full opcode cache as a separate operations
   workstream, not as an excuse to mix unrelated risk into the first release.
