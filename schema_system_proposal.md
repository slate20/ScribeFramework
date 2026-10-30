# Proposal: Hybrid Schema System for ScribeFramework

**Status:** Draft (rev 2) — Phases 0–4 implemented (Phase 4: IDE only; scaffolding not revisited)  
**Author:** Matt Venhaus  
**Date:** 2026-10-27

## Overview

Scribe currently manages database structure through plain `.sql` migration files. This works well for small projects but becomes harder to reason about as applications grow — especially when connecting to existing databases or working with multiple connections. Today, `run_migrations` only ever targets the `default` connection, so additional connections have no migration story at all.

This proposal introduces an optional **hybrid schema system** that gives developers a clear, declarative description of the tables a project cares about, while keeping versioned `.sql` migrations as the mechanism that actually changes the database.

The system is designed to be low-ceremony, opt-in, and practical for both green-field and brown-field projects.

> **Naming note:** "schema" collides with PostgreSQL schemas (`reporting.sales`). This document keeps the working name, but the final CLI group should consider `scribe tables` or `scribe model` instead of `scribe schema`.

## Goals

- Provide a single, readable description of the tables a project cares about
- Make it safe and easy to adopt existing databases
- Support multiple database connections cleanly, including migrations for every connection
- Keep the database's change history in reviewable, versioned `.sql` files
- Remain 100% backwards-compatible with current projects
- Keep the “I mostly just write SQL” feeling of Scribe

## Non-Goals

- Becoming a full ORM
- Forcing every project to use the schema system
- Replacing the ability to write raw SQL migrations when desired
- Cross-dialect portability of schema files (each file targets one connection and its dialect)
- Automatically performing destructive changes (drops, renames, type changes)

## Design Decisions

| Decision                        | Choice                                                                 |
|--------------------------------|------------------------------------------------------------------------|
| Multi-database layout           | `schemas/schema_{name}.py` per connection; each connection opts in to migrations with an explicit `migrations` path in `scribe.json` |
| When migrations run             | Via `scribe db migrate`, or on `dev`/`ide`/`serve` startup for connections with `auto_migrate: true`; the scaffolded SQLite `default` has it on |
| Column types                    | Native types of that connection's dialect, written as strings          |
| Default for pulled tables       | `managed=False`                                                        |
| Definition style                | Simple DSL for the common case + raw SQL strings as escape hatch      |
| Apply strategy                  | **Generate `.sql` migrations by default**; direct apply is a later, dev-only addition |
| Change policy                   | Additive changes are generated automatically; destructive changes require manual review |
| Startup behavior                | `dev` / `ide` / `serve` apply pending migrations for connections with `auto_migrate` on and report them for the rest; schema files are never applied on startup |
| Backwards compatibility         | Fully opt-in; existing projects continue working unchanged            |

## Prerequisites (Phase 0)

These fixes to the existing migration system are needed regardless of the schema system, and the schema system depends on them.

### 1. Dialect-safe `_migrations` table

`_create_migrations_table` in `scribe/migrations/runner.py` uses `INTEGER PRIMARY KEY AUTOINCREMENT`, which is SQLite-only. Neither the PostgreSQL nor the MSSQL adapter rewrites it, so `.sql` migrations currently fail on those connections. The DDL must be chosen per dialect:

| Dialect    | `id` column                         |
|------------|-------------------------------------|
| SQLite     | `INTEGER PRIMARY KEY AUTOINCREMENT` |
| PostgreSQL | `SERIAL PRIMARY KEY`                |
| MSSQL      | `INT IDENTITY(1,1) PRIMARY KEY`     |

`_get_applied_migrations` should also stop swallowing all exceptions with a bare `except`, so real connection or permission errors are reported.

### 2. Per-connection migrations (opt-in)

Each connection opts in to migrations by declaring a `migrations` path in `scribe.json`. Scribe never infers this from folder names, so existing subfolders inside `migrations/` are never picked up by accident.

All migration settings live **inside the connection block**, next to `type`. Anyone switching `default` to another database, or adding a second connection, is editing that block and sees the settings that control whether Scribe changes that database.

```json
{
  "databases": {
    "default": {
      "type": "postgresql",
      "host": "db.internal",
      "database": "app",
      "migrations": "migrations",
      "auto_migrate": false
    },
    "analytics": {
      "type": "postgresql",
      "host": "analytics.internal",
      "database": "warehouse",
      "migrations": "migrations/analytics"
    },
    "legacy": {
      "type": "mssql",
      "host": "erp.internal",
      "database": "erp",
      "migrations": false
    }
  }
}
```

Here `default` and `analytics` have migrations that run only through `scribe db migrate`, and `legacy` is never modified.

| `migrations` value on a connection | Meaning |
|---|---|
| A path, e.g. `"migrations/analytics"` | Migrations for this connection live in that folder (`*.sql`, non-recursive) |
| `true` | Shorthand for the conventional folder: `migrations` on `default`, `migrations/{name}` otherwise |
| `false` | Migrations are disabled; Scribe never creates `_migrations` or runs DDL on this connection |
| Absent on `default` | `"migrations"` — today's behavior, unchanged |
| Absent on any other connection | Disabled (same as `false`) |

- The documented convention for extra connections is `migrations/{name}`, and `scribe schema init` / `generate` suggest it, but any path works.
- `migrations: false` on `default` lets a brown-field project point Scribe at a database it must never modify.
- Each opted-in connection keeps its own `_migrations` table. Scribe never creates `_migrations` on a connection that hasn't opted in, or whose folder doesn't exist.
- Two connections may not share a migrations path; this is a config error at startup.

### 3. Per-connection auto-run (`auto_migrate`)

Today, `dev`, `ide`, and `serve` apply pending migrations every time they start. This proposal makes that a per-connection setting, so applying migrations on startup is a choice made in the same block that defines the database:

```bash
scribe db status   [--database name]   # list applied and pending migrations (read-only)
scribe db migrate  [--database name]   # apply pending migrations; all opted-in connections when omitted
```

- `"auto_migrate"` on a connection (only meaningful when `migrations` is enabled) controls startup behavior for that connection:
  - `true`: `dev`, `ide`, and `serve` apply its pending migrations on startup (today's behavior).
  - `false`: they only **report** pending migrations, e.g. `⚠ 2 pending migrations for 'analytics' — run 'scribe db migrate --database analytics'`, then start normally.

| `auto_migrate` on a connection | Meaning |
|---|---|
| `true` | Apply pending migrations on startup |
| `false` | Report pending migrations on startup; apply only via `scribe db migrate` |
| Absent on `default` | `true` — today's behavior, unchanged (see [Compatibility](#compatibility)) |
| Absent on any other connection | `false` — a newly added database is never changed on startup unless the block says so |

- `--migrate` / `--no-migrate` on `dev`, `ide`, and `serve` override the setting for every connection for a single run.
- `dev` and `ide` only watch a connection's migration folder for auto-reload when that connection auto-migrates, since a reload would not apply them otherwise.
- The pending check is read-only. If `_migrations` doesn't exist yet, every file counts as pending, and the table is not created.

#### Implicit-default warning

A common way to switch databases is to paste a PostgreSQL or MSSQL example over the scaffolded `default` block, which drops its explicit `migrations` / `auto_migrate` keys. The compatibility defaults then turn auto-run back on, and the scaffolded SQLite migrations would run against the new database at startup. To make that visible:

- When a **non-SQLite** connection is about to auto-migrate only because `auto_migrate` is absent (not because it is set to `true`), startup prints a warning naming the connection and the folder before running anything, and suggests setting `auto_migrate` explicitly.
- Every non-SQLite example in the docs and the README includes explicit `migrations` and `auto_migrate` keys, so copied blocks always carry a deliberate choice.

In practice the scaffolded SQL (`INTEGER PRIMARY KEY AUTOINCREMENT`) fails on PostgreSQL/MSSQL and is rolled back, so this case is noisy rather than destructive, but the warning makes the cause obvious.

### 4. MySQL adapter

`scribe/database/mysql.py` is empty, but `create_adapter` imports `MySQLAdapter` from it. Either implement the adapter or have `create_adapter` raise a clear "not supported yet" error. The schema system targets SQLite, PostgreSQL and MSSQL until MySQL exists.

### 5. Shared introspection

The IDE database browser (`scribe/gui/routes.py`) already contains per-dialect queries for listing tables and columns. Move these into adapter methods so the IDE and the schema system share one implementation:

```python
class DatabaseAdapter:
    def get_tables(self) -> list[str]: ...                  # includes "schema.table" on PostgreSQL
    def get_columns(self, table: str) -> list[ColumnInfo]: ...
    def get_indexes(self, table: str) -> list[IndexInfo]: ...          # Phase 1
    def get_foreign_keys(self, table: str) -> list[ForeignKeyInfo]: ... # Phase 1
```

## Schema File Structure

```text
myapp/
├── schemas/
│   ├── schema_default.py
│   ├── schema_analytics.py
│   └── schema_legacy.py
├── migrations/              # still the source of change history
│   ├── 001_initial.sql
│   └── analytics/
└── scribe.json
```

- One file per database connection
- File name must match the connection name in `scribe.json` (`schema_{name}.py`)
- If no `schemas/` directory exists, Scribe stays in classic `.sql` migration mode
- Schema files are loaded with `importlib`, the same way `lib/` modules are, so they work in the standalone binary

## Schema Definition Syntax

### Registration model

Every DSL call (`Table`, `Index`, `raw_sql`, `unmanaged`) registers itself in a module-level registry when called. Assigning a `Table` to a variable is optional and only useful for referencing it elsewhere. The registry is cleared before each schema file is loaded, so reloading (e.g. in `dev` or the IDE) never produces duplicates.

### Types

Column types are the **native types of the connection's dialect**, written exactly as that database would report or accept them. Scribe does not translate types between dialects. Because each schema file belongs to exactly one connection, this is unambiguous, and diffing compares normalized forms of those native types (e.g. PostgreSQL's `timestamp without time zone` matches `TIMESTAMP`).

### Defaults

Plain Python values are literals; SQL expressions must be wrapped in `sql(...)`:

```python
Column("status", "TEXT", default="open")                        # DEFAULT 'open'
Column("is_active", "BOOLEAN", default=True)                    # DEFAULT TRUE / 1 per dialect
Column("created_at", "TIMESTAMP", default=sql("CURRENT_TIMESTAMP"))  # DEFAULT CURRENT_TIMESTAMP
```

### Simple DSL (preferred for most tables)

```python
# schemas/schema_default.py  (SQLite connection)

from scribe.schema import Table, Column, Index, ForeignKey, sql

Table("users",
    Column("id", "INTEGER", primary_key=True, autoincrement=True),
    Column("username", "TEXT", unique=True, nullable=False),
    Column("email", "TEXT", unique=True),
    Column("password_hash", "TEXT", nullable=False),
    Column("is_active", "BOOLEAN", default=True),
    Column("created_at", "TIMESTAMP", default=sql("CURRENT_TIMESTAMP")),
    managed=True,
)

Table("orders",
    Column("id", "INTEGER", primary_key=True, autoincrement=True),
    Column("client", "TEXT", nullable=False),
    Column("total", "NUMERIC(12,2)", nullable=False),
    Column("status", "TEXT", default="open"),
    Column("user_id", "INTEGER", ForeignKey("users.id")),
    Column("created_at", "TIMESTAMP", default=sql("CURRENT_TIMESTAMP")),
    managed=True,
)

Index("idx_orders_status", "orders", ["status", "created_at"])
```

### PostgreSQL schema-qualified tables

```python
# schemas/schema_analytics.py  (PostgreSQL connection)

Table("reporting.sales",
    Column("id", "SERIAL", primary_key=True),
    Column("amount", "NUMERIC(12,2)", nullable=False),
    managed=True,
)
```

A name without a dot uses the connection's default search path (`public`).

### Raw SQL escape hatch

```python
# Useful for complex constraints, views, or database-specific features

from scribe.schema import raw_sql

raw_sql("idx_users_lower_email", """
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_lower_email
ON users (LOWER(email));
""")
```

- Each `raw_sql` block has a stable name and is tracked by a hash of its contents.
- `generate` emits a block into a migration when it is new or its hash has changed; unchanged blocks are skipped.
- Scribe cannot diff the effect of raw SQL against the live database, so a changed block is emitted as-is with a `-- REVIEW` marker. Authors are responsible for making the SQL safe to re-run (`IF NOT EXISTS`, `CREATE OR REPLACE`, etc.).

### Unmanaged tables

```python
from scribe.schema import unmanaged

# These tables exist but Scribe will never generate migrations for them
unmanaged("audit_log", "legacy_invoices", "temp_import")
```

Or per-table, optionally with columns kept for documentation and the IDE:

```python
Table("audit_log", managed=False)
```

### Scope

On a large existing database, `scope(include=[...], exclude=[...])` limits which tables a schema file covers. It takes case-insensitive glob patterns: `orders*` matches a table name in any schema, and `reporting.*` matches a whole PostgreSQL schema. `pull` only adds in-scope tables, and `status` only reports in-scope tables as untracked. Declared tables are always in scope. The scope lives in the schema file rather than `scribe.json`: it describes the project, not the environment, and `scribe.json` often differs per deployment or holds secrets. `pull --include/--exclude` writes it into a new file.

### Seed data

The DSL describes structure only. Seed and reference data stays in hand-written `.sql` migrations (as the new-project `tasks` rows do today).

## Commands

```bash
scribe schema pull     [--database name]  # Read live DB and generate/update schema file(s)
scribe schema diff     [--database name]  # Show differences between schema files and live DB (read-only)
scribe schema status   [--database name]  # Show managed tables, drift, and pending changes (read-only)
scribe schema generate [--database name]  # Write a numbered .sql migration from the diff
scribe schema init                        # Create an empty schemas/ directory with one file per connection
```

`scribe schema apply` is deferred to Phase 3 (see Rollout).

### Behavior

- **pull** creates or updates `schema_{name}.py`. Newly pulled tables default to `managed=False`. Existing entries the user has edited (e.g. `managed=True`) are preserved, and only new tables are added.
- **diff** and **status** never write to the database or to disk.
- **generate** writes the next numbered file into the connection's configured `migrations` path, e.g. `migrations/003_schema_add_orders_status.sql`. The file is then applied by `scribe db migrate` (or on startup if that connection has `auto_migrate` on) and recorded in `_migrations`.
- **generate** refuses to run for a connection that hasn't opted in to migrations, and prints the `scribe.json` snippet needed to enable it. Enabling migrations on a database is always an explicit config change.
- When the connection has `auto_migrate` on, the first `generate` for it warns that the next `dev`/`serve` start will run DDL against that database.
- All commands only consider `managed=True` tables when producing changes.
- All commands are no-ops (or fall back to classic mode) when no `schemas/` directory exists.

### Change policy

| Change                                   | `generate` output                                  |
|------------------------------------------|----------------------------------------------------|
| New table                                | `CREATE TABLE`                                     |
| New nullable column, or column with default | `ALTER TABLE ... ADD COLUMN`                    |
| New index / foreign key                  | `CREATE INDEX` / constraint DDL                    |
| New or changed `raw_sql` block           | Block contents (changed blocks marked `-- REVIEW`) |
| Dropped table or column                  | **Commented out**, marked `-- REVIEW: destructive` |
| Type, nullability, or default change     | **Commented out**, marked `-- REVIEW`              |
| Possible rename (drop + add of similar column) | **Commented out**, with a note suggesting a rename |

Destructive and ambiguous changes are never emitted as live SQL. A rename looks exactly like a drop plus an add in a declarative diff, and running that would destroy data. On SQLite, changing a column's type or constraints also requires rebuilding the table (create new table, copy, drop, rename); `generate` writes that sequence as commented-out SQL for the author to review rather than running it.

`generate` refuses to write a file if the only changes are commented-out ones, and prints the diff instead, unless `--force` is passed.

## Coexistence with hand-written migrations

Hand-written `.sql` files remain fully supported alongside schema files. Because `generate` always diffs against the **live database** (not against earlier generated files), a hand-written migration is simply part of the database's state:

- If a hand-written migration changes a `managed=True` table, `diff` and `status` report that table as **drifted** from its schema file.
- The fix is to update the schema file to match (or run `pull` for that table). `generate` never reverts drift on its own, because doing so would be a destructive change and falls under the change policy above.
- Changes to `managed=False` tables are never reported as drift.

## Startup behavior

`scribe dev`, `scribe ide`, and `scribe serve` check every opted-in connection for pending `.sql` migrations. They apply them for connections with `auto_migrate` on (or for all connections when `--migrate` is passed); for the rest they print a warning and start normally. They **never** read schema files or apply a schema diff. The database only changes through versioned migration files, so production deploys stay reviewable and repeatable.

`scribe dev` may also print a one-line notice when `diff` finds schema changes not yet generated (e.g. `2 schema changes pending for 'default' — run 'scribe schema generate'`).

## Workflows

### New project

`scribe new` still creates `.sql` migrations (including seed rows), and writes the migration settings explicitly into the scaffolded SQLite connection:

```json
{
  "databases": {
    "default": {
      "type": "sqlite",
      "database": "app.db",
      "migrations": "migrations",
      "auto_migrate": true
    }
  }
}
```

The first `scribe dev` creates and seeds `app.db` exactly as today, with no extra steps. Because the settings sit in the `default` block, a user who switches it to PostgreSQL or MSSQL, or copies it to add a second connection, edits them in the same place and can turn auto-run or migrations off.

A project opts in to schema files later with:

```bash
scribe schema init
scribe schema pull
# set managed=True on tables Scribe should own
```

### Existing database (brown-field)

```bash
# 1. Configure connection in scribe.json
# 2. Pull current structure
scribe schema pull

# 3. Edit schemas/schema_default.py
#    - Set managed=True only on tables you want Scribe to own
#    - Delete or ignore tables you don’t care about

# 4. Future changes
#    Edit the schema file → scribe schema generate → review → scribe db migrate
```

### Multi-database

```bash
# after adding "migrations": "migrations/analytics" to the analytics connection
scribe schema pull --database analytics
scribe schema generate --database analytics   # writes migrations/analytics/NNN_*.sql
scribe db migrate --database analytics
scribe schema diff --database legacy          # read-only; legacy never opted in to migrations
```

Each opted-in database has its own schema file, migration folder, and `_migrations` table.

## Compatibility

### How existing apps behave today

`run_migrations` creates `_migrations` with `INTEGER PRIMARY KEY AUTOINCREMENT` as soon as a `default` connection exists and a `migrations/` folder exists, even an empty one. That DDL is a syntax error on PostgreSQL and MSSQL and is not caught, so startup fails. Every working non-SQLite app is therefore in one of two situations:

- **A.** It has no `migrations/` folder (removed after `scribe new`), and its tables were created outside Scribe.
- **B.** Its connection isn't named `default`, so migrations are skipped with a warning.

Existing SQLite apps use the full migrate-on-startup behavior.

### Rules that keep existing apps working

1. **`auto_migrate` absent on `default` means `true`.** Existing `scribe.json` files have no `auto_migrate` key, so startup keeps applying `default`'s migrations exactly as today. On non-SQLite connections this implicit default triggers the [implicit-default warning](#implicit-default-warning) before anything runs. New projects from `scribe new` get explicit keys, so they never rely on this rule.
2. **`default` keeps `migrations/`.** Absent a `migrations` key, the `default` connection uses the top-level `migrations/` folder, as today. For a PostgreSQL or MSSQL `default` (an app connected to a database managed elsewhere, often in a hybrid setup next to a local SQLite connection), startup warns on every run until `migrations` is set explicitly, and `db new-migration`, `schema generate`, and `schema apply` refuse to create migration files for it. Those commands are how a `migrations/` folder usually appears, which is the moment such an app would start changing its production database.
3. **Other connections are disabled unless configured.** Subfolders inside `migrations/` are never treated as per-connection migrations by name. An app with, say, `migrations/analytics/` holding scripts meant to be run by hand will not have them executed after upgrading.
4. **No DDL on connections that haven't opted in.** Scribe never creates `_migrations` on a connection without an enabled `migrations` path and an existing folder. Read-only credentials and shared legacy databases are safe.
5. **Schema commands are opt-in and read-only until `generate`.** `pull`, `diff`, and `status` never write to the database. `generate` never enables migrations on a connection by itself.

### Effect of each change on existing apps

| Change | SQLite apps | PostgreSQL / MSSQL apps |
|---|---|---|
| Dialect-specific `_migrations` DDL | None | None for A/B; adding a `migrations/` folder now works instead of crashing |
| `_get_applied_migrations` stops swallowing errors | None in practice | None in practice (a failed read already aborted the transaction) |
| Per-connection `migrations` opt-in | None | None; existing subfolders are ignored |
| Per-connection `auto_migrate` (absent → `true` on `default`) | None; same startup behavior | None for A/B; implicit auto-run on a non-SQLite `default` warns first |
| `scribe db status`, `--migrate` / `--no-migrate` | Additive | Additive |
| MySQL adapter → clear error | N/A | N/A (`type: mysql` already fails with an ImportError) |
| Introspection moved into adapters | IDE only | IDE only; must keep `schema.table` names on PostgreSQL |
| Schema system | Opt-in | Opt-in |

### Other compatibility notes

- Existing migration history is never rewritten, and existing `_migrations` tables are reused as-is.
- A project can adopt the schema system at any time via `scribe schema pull`.
- Deleting the `schemas/` directory immediately returns the project to classic mode; all generated migrations remain as ordinary `.sql` files.
- Connections with `auto_migrate: false` need `scribe db migrate` in their deploy steps. `docs/05_DEPLOYMENT.md` needs a section on this, and the starter-page, README, and `docs/03_DATABASE.md` text about migrations "running automatically on start" should say this is per-connection.

## Managed vs Unmanaged

| Flag            | Meaning                                                  |
|-----------------|----------------------------------------------------------|
| `managed=True`  | Scribe diffs this table and generates migrations for it  |
| `managed=False` | Table is visible / documentable but never migrated, and never reported as drift |

Default on pull is `managed=False` so that connecting to a production database is safe by default. Tables written by hand default to `managed=True` (omitting the argument), since generated changes are additive-only and a hand-written table is usually one Scribe should create; `pull` always writes `managed=False` explicitly.

## Rollout

| Phase | Scope |
|-------|-------|
| **0** | Dialect-safe `_migrations` table; opt-in per-connection `migrations` paths and `--database` on `scribe db migrate`; per-connection `auto_migrate`, `scribe db status`, the startup pending-migrations and implicit-default warnings; `scribe new` writes explicit `migrations` / `auto_migrate: true` on the SQLite `default`; resolve the empty MySQL adapter (now a clear "not supported yet" error); move table/column introspection into adapter methods (`get_tables`, `get_columns`, `has_table`) |
| **1** | Index and foreign-key introspection (`get_indexes`, `get_foreign_keys`); DSL and registry; `schema init`, `pull`, `diff`, `status` (read-only) |
| **2** | `schema generate` with the change policy above; `raw_sql` hash tracking; `scribe dev` pending-changes notice. As built: `raw_sql` hashes are recorded as `-- raw_sql: name sha256:…` markers in the generated migrations (no extra table); `generate` refuses while the connection has unapplied migrations, since the diff is against the live database; SQLite review changes are grouped into one commented table-rebuild per table; adding UNIQUE columns or columns with non-constant defaults is review-only on SQLite but additive elsewhere |
| **3** | Optional `schema apply`: allowed in `dev` only, additive changes only, and records what it ran in `_migrations` so history stays complete. As built: Scribe has no dev/production setting, so "dev only" means connections with `auto_migrate: true` (explicit on non-SQLite connections). `apply` writes a normal migration file and runs it, rather than only recording a `_migrations` row, so every other database (teammates, CI, production, fresh `app.db`) gets the change too. Supporting change: each SQLite migration file now runs in one transaction, with `PRAGMA foreign_keys = OFF` honored before it and a `foreign_key_check` before commit, so a failed `apply` is rolled back and its file removed |
| **4** | IDE integration (below); revisit scaffolding new projects with schema files. As built: a Schema tab in `scribe ide` with the table browser, drift per table, managed toggle (an `ast`-located edit of the `managed=` keyword that keeps the rest of the file intact, rolled back if the file no longer loads), and Pull / Generate / Apply / Run pending migrations. Generate and Apply always preview the SQL first, and both are disabled while migrations are pending so the preview matches what runs. The steps the CLI and IDE share moved to `scribe/schema/actions.py`. Scaffolding `scribe new` projects with a schema file is not done yet |

Phases 0–1 are useful on their own: they fix multi-database migrations, make database changes deliberate, and give brown-field projects a readable map of their database with no risk of changing it.

### Alternative considered: SQLAlchemy + Alembic

SQLAlchemy reflection plus Alembic's `compare_metadata` already handle cross-dialect introspection and diffing. Using them internally would reduce the amount of dialect-specific code Scribe has to maintain, but adds a large dependency to the PyInstaller binary and pulls Scribe toward ORM-style tooling. The proposal assumes a hand-written implementation, which is feasible because v1 only targets three dialects and only generates additive changes. This should be revisited if dialect handling in `diff` grows unmanageable.

## IDE Integration (Light Touch)

The built-in Scribe IDE can later surface:

- A schema browser that reads the `schemas/*.py` files
- Visual diff against the live database, with drift highlighted
- One-click “Pull” and “Generate migration” actions
- Ability to toggle managed status from the UI

These are natural extensions and do not need to ship in the first version of the schema system. All four are implemented in the IDE's Schema tab (see docs/06_SCHEMA_FILES.md, "In the IDE").

## Summary

The hybrid schema system gives Scribe a clear, optional way to describe database structure without abandoning its SQL-first, low-ceremony philosophy. Schema files describe the tables a project cares about; versioned `.sql` migrations remain the only way the database changes. Starting by fixing the existing migration runner for every connection and dialect, making migrations and startup auto-run explicit per-connection settings, and limiting generated changes to additive ones, keeps the system safe for existing projects and production databases while leaving room for direct apply and IDE tooling later.
