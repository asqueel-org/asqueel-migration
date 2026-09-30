# Changelog

## 0.1.2 (unreleased)

- Rename the distribution, Python package and CLI to Asqueel Migration.
- Retain all fixes from 0.1.1; prepare GitHub Trusted Publishing for the new name.

## 0.1.1 — 2026-09-29

- Preserve added and changed columns before primary-key rebuilds, retaining
  dialect-specific SQL assembly (#10, #12; legacy genropy/genropy#1194).
- Normalize legacy varchar min:max sizes in JSON and XML producers so
  repeated schema comparisons converge after migration (#11, #13).
- Align regression coverage with legacy develop, including varchar widening
  on primary-key columns, and document intentional test exclusions.

## 0.1.0 — 2026-09-29

First public Alpha release.

- Compare normalized database schemas and generate additive migrations for
  PostgreSQL, SQLite, MySQL and SQL Server, with JSON and XML producers.
- Apply DDL atomically where supported; MySQL reports best-effort execution.
- Preserve authored index names and PostgreSQL descending column order.
  Quote and escape index identifiers and handle schema-aware index rebuilds
  and dialect-specific renames (issues #8 and #9).
- Offer an optional localhost-only HTTP/MCP editor built on Kajenn 0.1.
  Applying migrations remains REST-only.

The API is still evolving. Renames are not inferred and database-only objects
are retained by default. See the producer guide for dialect limitations.
