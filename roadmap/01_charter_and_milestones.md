# Current charter and milestones

**Updated: 2026-10-12.** Baseline: library 0.2.1, structure contract 1.0.

## Scope and architecture

The library compares a producer-supplied normalized schema with the live database
and generates migrations. Producers own application model extraction; the engine
owns validation, introspection, diff, SQL generation and execution. It does not
read ORM trees itself. JSON and XML producers share the normalized contract.

`SqlMigrator` retains the legacy Python surface. `plan_migration` and
`apply_migration` add reviewed plan identifiers, unsupported-operation rejection
and convergence reporting. Inputs are copied and preparation is repeatable.
Callers own database connections. The CLI remains a minimal PostgreSQL automation
interface without the reviewed-plan protocol.

HTTP, OpenAPI and MCP are in the separate Asqueel DB Manager package. Consumers
include Asqueel's native migration API and DB Manager; changes must preserve
those contracts. The previous proposed Genropy rollout is not evidence of an
actual migration of every legacy consumer.

## Delivery

The [roadmap index](00_INDEX.md) records current milestone status. M0–M2 are
implemented, and the four M3 adapters exist. Extended-entity wave 0 (CHECK and
comments) exists on supporting dialects. Waves 1–3 remain proposals, with no
promised release date or structure-version bump.

Post-0.2.1 work addresses SQLite `main`, legacy TIMESTAMP adoption, new-table
FK/UNIQUE support, structured omissions, typing and package integrity. Features
marked Unreleased must not be assumed available from PyPI 0.2.1.

## Remaining boundaries

- Preserve the additive contract: database-only objects remain, except the
  explicitly enabled DROP COLUMN operation. Renames are not inferred.
- Target DDL is atomic on PostgreSQL, SQLite and SQL Server; MySQL is best-effort.
  Database creation is separate and plan identifiers do not prevent concurrent
  external DDL.
- Existing SQLite constraint transformations need table rebuilding, which is not
  implemented. Cross-file FKs and requested deferral are unsupported.
- SERIAL4 autogeneration and safe SERIAL4-to-SERIAL8 upgrades require an explicit
  contract decision. PostgreSQL initial `public` creation remains a known limit.
- Keep MySQL/SQL Server integration coverage; defer additional dialect work.
- Introduce stronger type annotations/protocols gradually, without weakening the
  blocking checks or changing the public JSON contract unintentionally.

Detailed support, tests and release gates are in the public documentation rather
than inferred from the historical design files.
