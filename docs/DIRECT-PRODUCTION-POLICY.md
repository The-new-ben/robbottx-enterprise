# Direct-production policy

## Owner override

No staging environment and no backup will be created. This overrides the
generic staging/backup instructions in the transferred build skill.

## Compensating controls

- Build and test versioned packages locally.
- Keep releases small and independently reversible by activation or package
  version.
- Make database upgrades additive before destructive cleanup.
- Do not delete inherited content, users, orders, settings, media, or plugins as
  part of initial foundation work.
- Capture the live state before every material release.
- Verify administrator access immediately before a production mutation.
- Run live smoke, accessibility, responsive, SEO, schema, link, and performance
  checks immediately after release.
- Stop a release when the exact target, expected behavior, or rollback action is
  unknown.
- Record every production mutation and its evidence in `docs/releases/`.

This policy reduces risk but does not pretend direct production is equivalent to
staging plus a tested restore point. That residual risk remains explicit.

