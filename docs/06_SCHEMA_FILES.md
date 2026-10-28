# Schema Files

Schema files are an optional, readable description of the tables a database connection has. They live in `schemas/`, one file per connection, and Scribe compares them with the live database.

Schema files never change the database themselves. `scribe schema generate` turns the differences into an ordinary `.sql` migration, which you review and apply with `scribe db migrate` (see [Database Guide](03_DATABASE.md#migrations)).

Projects without a `schemas/` directory are unaffected.

## Getting Started

### Existing database

```bash
scribe schema pull                   # write schemas/schema_<name>.py for every connection
```

Pull only reads the database. Every table it adds starts as `managed=False`, which means Scribe documents it but never reports changes for it. Set `managed=True` on the tables Scribe should own, then compare:

```bash
scribe schema diff
```

Running `pull` again later only adds tables the file doesn't mention yet. Tables you've already declared, edited, or marked `unmanaged()` are never rewritten.

### Starting empty

```bash
scribe schema init                   # one empty schema file per connection
```

## Writing a Schema File

`schemas/schema_default.py` describes the `default` connection; `schemas/schema_analytics.py` describes `analytics`, and so on.

```python
from scribe.schema import Table, Column, Index, ForeignKey, sql, raw_sql, unmanaged

Table("users",
    Column("id", "INTEGER", primary_key=True, autoincrement=True),
    Column("username", "TEXT", unique=True, nullable=False),
    Column("is_active", "BOOLEAN", default=True),
    Column("created_at", "TIMESTAMP", default=sql("CURRENT_TIMESTAMP")),
)

Table("orders",
    Column("id", "INTEGER", primary_key=True, autoincrement=True),
    Column("total", "NUMERIC(12,2)", nullable=False),
    Column("status", "TEXT", default="open"),
    Column("user_id", "INTEGER", ForeignKey("users.id")),
)

Index("idx_orders_status", "orders", ["status"])
```

### `Table(name, *columns, managed=True)`

- `managed=True` (the default for tables you write): `diff` compares the table with the database.
- `managed=False`: the table is documented but never compared. Columns are optional.
- On PostgreSQL, use `"schema.table"` for tables outside the current schema.

### `Column(name, type, *constraints, ...)`

| Argument | Meaning |
|---|---|
| `type` | The connection's own type name, e.g. `"INTEGER"` on SQLite or `"varchar(255)"` on PostgreSQL. Scribe doesn't translate types between databases. |
| `ForeignKey("table.column")` | Optional, passed positionally after the type |
| `primary_key=True` | Part of the primary key (set it on several columns for a composite key) |
| `autoincrement=True` | Database-assigned values (`AUTOINCREMENT`, `SERIAL`/identity, `IDENTITY`) |
| `nullable=False` | `NOT NULL` |
| `unique=True` | Single-column `UNIQUE` |
| `default=` | A literal (`"open"`, `0`, `True`) or a SQL expression wrapped in `sql("CURRENT_TIMESTAMP")` |

### `Index(name, table, columns, unique=False)`

Declares an index. Composite unique constraints are declared as unique indexes.

### `unmanaged(*names)`

Lists tables that exist but that Scribe should ignore entirely. `diff` and `status` won't report them as untracked.

### `raw_sql(name, sql)`

A named block of SQL for things the DSL can't describe, such as views and expression indexes. These blocks aren't compared with the database. Instead, `generate` includes a block in a migration when it's new or its text has changed. Write blocks so they're safe to run again (`IF NOT EXISTS`, `CREATE OR REPLACE`), and note that `IF NOT EXISTS` won't update an object that already exists.

## Reading the Diff

```text
default (sqlite) — schemas/schema_default.py
  tasks
    + priority: add column INTEGER
    ! title: type TEXT → VARCHAR(200)
  users
    ! pw_hash: add column TEXT (possible rename of password_hash → pw_hash)
    - password_hash: column exists in the database but not in the schema file (...)
  orders
    + create table (4 columns)
  3 additive, 3 need review (1 would drop data)
```

| Mark | Meaning |
|---|---|
| `+` | Additive: a new table, a nullable column or one with a default, a new index |
| `!` | Needs review: type, nullability, or default changes; anything that can't be done in place |
| `-` | Would drop data: a column, index, or constraint the database has but the schema file doesn't |

A column that disappears while a column of the same type appears is flagged as a possible rename, since running it as a drop plus an add would lose the data.

Spelling differences aren't reported. For example, PostgreSQL's `character varying(255)` matches `varchar(255)`, `'open'::text` matches `"open"`, and MSSQL's `((0))` matches `0`.

Not compared: tables marked `managed=False` or `unmanaged()`, `raw_sql()` blocks, expression indexes, and composite foreign keys.

## Status

```bash
scribe schema status
```

```text
default (sqlite) — schemas/schema_default.py
  managed:     3 table(s) — 2 in sync, 1 with changes (orders)
  unmanaged:   4 table(s)
  untracked:   1 table(s) in the database aren't in schemas/schema_default.py: audit
               'scribe schema pull --database default' adds them
  changes:     1 additive, 0 need review — 'scribe schema diff --database default' lists them
  migrations:  0 pending
```

## Generating Migrations

```bash
scribe schema generate              # write migrations/NNN_schema_<tables>.sql
scribe schema generate --dry-run    # print it instead
scribe db migrate                   # apply it (or let auto_migrate do it on startup)
```

The connection must have migrations enabled (see [Per-connection settings](03_DATABASE.md#per-connection-settings)). `generate` refuses to run while that connection has unapplied migrations, because the diff is computed against the live database and would repeat them.

What goes in the file:

| Change | In the migration |
|---|---|
| New table (created after any new tables it references), new nullable column or one with a constant default, new index, new UNIQUE, new `raw_sql()` block | SQL that runs |
| New foreign key on an existing column | Runs on PostgreSQL and MSSQL; review on SQLite |
| Type, nullability, default, or primary key changes; dropped columns, indexes, constraints | Commented out under `-- REVIEW` |
| Possible rename | Commented out: a `RENAME COLUMN` statement, plus the add/drop alternative |

Uncomment and adjust the REVIEW sections you want before running the file. Dropping a column, for example, deletes its data. Databases may also refuse a change for reasons Scribe can't see: PostgreSQL won't change the type of a column that a view uses until the view is dropped.

**SQLite** can't change a column's type, nullability, or default, or add constraints to an existing table, in place. For those, the migration contains a commented-out rebuild sequence (create a new table, copy the rows, drop the old one, rename) that copies every column the new definition keeps.

If every change needs review, `generate` writes nothing unless you pass `--force`.

`scribe dev` prints a one-line notice at startup when a schema file has changes that aren't in a migration yet.

## Commands

```bash
scribe schema init                         # empty schema file per connection
scribe schema pull     [--database name]   # add live tables to the schema file (read-only on the database)
scribe schema diff     [--database name]   # compare managed tables with the database (read-only)
scribe schema status   [--database name]   # summary (read-only)
scribe schema generate [--database name] [--name NAME] [--dry-run] [--force]
```

## Testing against PostgreSQL

`tests/test_schema_postgres.py` runs the full pull → generate → migrate cycle against a real PostgreSQL database. It is skipped unless `SCRIBE_TEST_POSTGRES` is set, and it **drops and recreates the `public` and `reporting` schemas** in the database you point it at. The database name must contain `test`:

```bash
SCRIBE_TEST_POSTGRES='{"host": "localhost", "port": 5432, "user": "scribe", "database": "scribe_test"}' pytest tests/test_schema_postgres.py
```
