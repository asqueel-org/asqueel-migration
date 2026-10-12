Asqueel Migration
=================

.. image:: ../assets/branding/asqueel-migration-primary.svg
   :alt: Asqueel Migration
   :width: 300px

An autonomous Python library for SQL schema migrations: compare a
normalized JSON description of a database (the contract) against a live
database and generate or apply the realignment SQL. ORM-agnostic by
design — any producer that emits the JSON contract can drive it.

Supported dialects: PostgreSQL, SQLite, MySQL, MSSQL.

The producer guide covers normalized input, reviewed ``plan_migration`` /
``apply_migration`` execution, connection ownership and the PostgreSQL CLI.
HTTP, OpenAPI, MCP and backup/restore belong to the separate
`Asqueel DB Manager <https://github.com/asqueel-org/asqueel-dbmanager>`_ application.

.. toctree::
   :maxdepth: 2
   :caption: Contents

   producer_guide
