# Migration roadmap

**Updated: 2026-10-12.** Released baseline: **0.2.1**, structure contract **1.0**.
The changelog's Unreleased section describes changes after that baseline.

| Milestone | Current status | Evidence / remaining work |
| --- | --- | --- |
| M0 — parity audit | Completed; historical record | `02_legacy_parity_audit.md` |
| M1 — legacy test port | Implemented | `tests/test_migration_pg.py`, `tests/test_migration_modes_pg.py`, `docs/legacy_test_alignment.md`; five dormant feature tests remain skipped |
| M2 — JSON contract | Implemented | Version 1.0 JSON Schema, semantic validator, JSON/XML producers, producer guide |
| M2.5 — extended entities | Wave 0 implemented on supporting dialects; waves 1–3 proposed | CHECK/comments exist; views, routines, table triggers, custom types and standalone sequences are not implemented |
| M3 — multiple databases | Four adapters implemented with differing capabilities | PostgreSQL, SQLite, MySQL, SQL Server; see public capability matrix, not the original planned sequence |
| M4 — consumers | Asqueel and DB Manager integrated; legacy Genropy rollout not asserted | Native plan/apply contracts and separate server package; consumer suites must remain green |
| Hardening | In progress | Reviewed plans, source snapshots and atomic target DDL exist; unsupported transformations remain explicit |

Current priorities are SQLite adoption/constraints, structured omissions, blocking
typing and reproducible packaging (see Unreleased changes and issues #2, #4, #5,
#15, #20–#25). SERIAL4 declaration/upgrade and PostgreSQL initial `public` schema
handling remain open. MySQL and SQL Server are supported by CI; additional
feature work on those dialects is deferred.

## Reading order

- [Current charter](01_charter_and_milestones.md)
- [Capability matrix](../docs/capabilities.md)
- [Known limits](../docs/known_limits.md)
- [Development and release checks](../docs/maintenance.md)
- [Changelog](../CHANGELOG.md)

## Historical designs

These documents retain original assumptions and chronology; they are not the
current support contract. Implementation status above and the public matrix take
precedence over future-tense passages in these records.

| Document | Status |
| --- | --- |
| [Parity audit](02_legacy_parity_audit.md) | Historical audit and subsequent findings |
| [Test porting plan](03_test_porting_plan.md) | Historical plan; current coverage is in `docs/legacy_test_alignment.md` |
| [JSON contract notes](04_json_contract_notes.md) | Historical design and completion record; current contract is packaged schema 1.0 |
| [Extended entities](05_extended_entities.md) | Proposal for waves 1–3; wave 0 delivered |
