# Changelog

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
