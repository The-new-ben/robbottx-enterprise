# RobbottX agent instructions

## Mission

Treat every task as part of the RobbottX 360-degree enterprise:
evidence-backed entities, engineering graph, compatibility, configuration,
3D/simulation, procurement, lifecycle, SEO, commerce, ethics/safety, and
planetary extension.

## Required reasoning

For every substantive change, separate:

- explicit requirements;
- implied dependencies;
- proposed additions;
- unknowns;
- contradictions;
- risks;
- acceptance evidence.

Zoom out across the enterprise before zooming into the smallest complete
vertical slice.

## Hard constraints

- Do not import or use the retired catalog CSVs or placeholder catalog images.
- Do not copy the inherited site design or treat inherited content as canonical.
- Do not create a staging environment or backup.
- Do not store credentials, tokens, cookies, customer data, production exports,
  or secrets in this repository.
- Do not publish unsupported engineering, compatibility, certification, stock,
  price, safety, or space-qualification claims.
- Do not turn WordPress posts and taxonomies into the canonical engineering
  database.
- Do not create mass indexable pages before identity, evidence, canonical,
  quality, sitemap, and faceted-navigation gates exist.

## Architecture

- Immutable, language-neutral entity IDs.
- Separate family, model, revision, variant, configuration, physical unit,
  supplier SKU, and seller offer.
- Assertion-level provenance and confidence.
- Versioned typed graph edges, BOMs, rules, and compatibility results.
- Rebuildable WordPress, search, graph, vector, feed, and 3D projections.
- English public launch first; source ingestion supports `en`, `zh-Hans`,
  `zh-Hant`, `ja`, `ko`, and `de` from the beginning.

## Definition of done

A material milestone needs observable implementation, current research,
functional verification, engineering/data checks, SEO/structured-data checks,
desktop/mobile screenshots, accessibility/performance evidence, and documented
limitations. Unknown compatibility is never a pass.

## WordPress deployment law

For any WordPress install, update, deployment, or hotfix, use the globally
installed `wordpress-agent-deploy` skill. Build a deterministic versioned
plugin ZIP, publish it to the verified GitHub raw URL, deploy through a
temporary administrator-gated Code Snippets REST route using
`Plugin_Upgrader`, independently verify the public healthcheck and rendered
body, delete the route, and prove it returns 404. Never leave privileged
one-shot code at snippet top level or persist a deploy route.
