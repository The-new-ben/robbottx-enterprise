# Security

Do not report credentials, cookies, tokens, personal data, production paths, or
customer information in a public issue.

The repository must contain no secrets. Production evidence is redacted before
it is stored. Engineering facts are untrusted input until they pass schema,
evidence, authorization, and publication gates.

The first release performs no remote ingestion, file upload, payment mutation,
or destructive data migration. Future public submission and ingestion surfaces
require a threat model, capability checks, rate limits, validation, audit logs,
and incident handling before activation.
