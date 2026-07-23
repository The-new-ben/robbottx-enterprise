# RobbottX public language

## Public audience

RobbottX addresses:

1. Robotics engineers and system integrators comparing exact systems,
   interfaces, versions, conditions, and source documents.
2. Technical buyers and procurement teams checking part identity, lifecycle,
   regional availability, price, lead time, warranty, and commercial risk.
3. Customers selecting a standard or custom robotic system for a defined task.
4. Manufacturers and distributors maintaining accurate product, document, and
   offer records.
5. Operators, service teams, and safety teams checking operating limits,
   maintenance, replacement, compliance, and application conditions.
6. Researchers, educators, and developers who need technical depth and
   reproducible sources.

Search engines and authorized machine clients receive semantic HTML,
structured data, feeds, and APIs. Public machine responses use catalog
language and stable technical identifiers. Internal workflow state stays
behind authentication.

## Public copy does not address

- Codex, agents, release engineers, or project managers.
- Internal milestones, prompts, publication gates, snapshots, projections, or
  candidate states.
- Buyers seeking compatibility, certification, stock, price, or safety claims
  that the available evidence does not support.
- Present-day customers for future planetary offerings without a qualified
  product and evidence record.

## Established-platform voice

RobbottX public pages describe systems, components, specifications,
compatibility, documents, lifecycle, availability, and customer actions. They
do not describe RobbottX as an experiment, roadmap, launch, or unfinished
project.

Attach uncertainty to the affected record:

- Documentation reviewed
- Conditions apply
- Version specific
- Not confirmed
- Source conflict
- Requires validation
- Verify with manufacturer
- Availability not confirmed

Do not advertise counts of internal blockers. Show the applicable condition in
the specification, compatibility area, or supplier record where it changes a
decision.

## Information layers

1. Public decision layer: identity, use, key specifications, compatibility
   state, important condition, and next action.
2. Engineering layer: exact revisions, interfaces, software, operating limits,
   safety, and supply conditions.
3. Provenance layer: source document, document location, review date, record
   ID, checksum, and change history.
4. Machine layer: stable IDs, schemas, graph relationships, and provenance
   appropriate to the caller's authorization.

Public language includes rendered pages, SEO and structured data, public REST
responses, health endpoints, search and error states, WordPress site settings,
readmes, manifests, stylesheet headers, block metadata, downloadable records,
and every other directly requestable file.

## Release rules

Reject customer-facing copy when it:

- contains an em dash;
- contains internal project, agent, publication, or data-pipeline vocabulary;
- sounds like a beta, launch log, roadmap, or research exercise;
- uses inflated or formulaic phrasing;
- merges compatibility, lifecycle, evidence, availability, and order readiness
  into one status;
- promises more than the exact source, model, revision, region, date, or test
  scope supports;
- calls a field searchable when the live search index does not contain and
  return that field;
- uses unscoped absolutes such as every, all, complete, or full;
- exposes internal workflow language through a public API, health response, or
  static file;
- claims that every specification is publicly traceable when the interface does
  not expose that relationship;
- breaks at a narrow viewport or under long translated text.

The automated check is `npm run validate:language`.
