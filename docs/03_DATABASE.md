# Database Guide

Learn how to work with databases in ScribeEngine.

## Configuration

Edit `scribe.json`:

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

`migrations` and `auto_migrate` control whether Scribe changes this database. See [Migrations](#migrations).

### Multiple Databases

```json
{
  "databases": {
    "default": {
      "type": "sqlite",
      "database": "app.db"
    },
    "analytics": {
      "type": "postgresql",
      "host": "localhost",
      "port": 5432,
      "user": "dbuser",
      "password": "secret",
      "database": "analytics",
      "migrations": false
    }
  }
}
```

Supported types: `sqlite`, `postgresql`, `mssql`.

Access: `db['default']`, `db['analytics']`

## Query Methods

### Raw SQL

```python
{$
users = db['default'].query("SELECT * FROM users")
user = db['default'].query(
    "SELECT * FROM users WHERE id = ?",
    (user_id,)
)
$}
```

### Find by ID

```python
{$
user = db['default'].find('users', 123)
# Returns: {'id': 123, 'username': 'alice', ...}
$}
```

### Insert

```python
{$
user_id = db['default'].insert('users',
    username='alice',
    email='alice@example.com',
    password_hash=hash_password('secret')
)
$}
```

### Update

```python
{$
db['default'].update('users',
    {'email': 'newemail@example.com'},
    id=user_id
)
$}
```

### Delete

```python
{$
db['default'].delete('users', id=user_id)
$}
```

## Migrations

Migrations are `.sql` files, applied in filename order (`001_`, `002_`, ...). Each applied file is recorded in a `_migrations` table in that database, so it only ever runs once.

Create one with `scribe db new-migration add_posts`, which writes `migrations/003_add_posts.sql` (numbered after the existing files):

```sql
CREATE TABLE posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT,
    user_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
```

Apply it:

```bash
scribe db status    # show applied and pending migrations (read-only)
scribe db migrate   # apply pending migrations
```

### Per-connection settings

Each connection block in `scribe.json` decides whether Scribe may change that database:

| Key | Values | Default |
|---|---|---|
| `migrations` | Folder path, `true` (uses `migrations/` for `default`, `migrations/<name>` otherwise), or `false` | `"migrations"` for `default`; disabled for other connections |
| `auto_migrate` | `true`: apply pending migrations when `scribe dev`, `scribe ide`, or `scribe serve` starts. `false`: only report them | `true` for `default`; `false` for other connections |

New projects from `scribe new` set both explicitly on the SQLite `default` connection, so the starter tables are created on the first `scribe dev`.

**Switching `default` to PostgreSQL or MSSQL?** Revisit these keys in the same block. The starter migrations use SQLite syntax, and with `auto_migrate` on they will run against the new database at startup. Set `"migrations": false` if Scribe should never change it, or `"auto_migrate": false` to apply migrations yourself with `scribe db migrate`. If `auto_migrate` is missing on a non-SQLite connection, startup prints a warning before running anything.

### Migrations for other connections

Other connections opt in by naming a folder:

```json
"analytics": {
  "type": "postgresql",
  "database": "analytics",
  "migrations": "migrations/analytics",
  "auto_migrate": false
}
```

```bash
scribe db new-migration add_page_views --database analytics
scribe db migrate --database analytics
scribe db migrate                        # every connection with migrations enabled
```

Folders are never matched to connections by name, so a `migrations/analytics/` folder does nothing until `analytics` points to it. Two connections cannot share a folder.

### Startup flags

`scribe dev`, `scribe ide`, and `scribe serve` accept `--migrate` / `--no-migrate` to override `auto_migrate` for every connection for one run.

## Best Practices

### Always Use Parameterized Queries

```python
# ✅ SAFE
users = db['default'].query(
    "SELECT * FROM users WHERE username = ?",
    (username,)
)

# ❌ DANGEROUS (SQL injection vulnerability)
users = db['default'].query(
    f"SELECT * FROM users WHERE username = {username}"
)
```

### Check for Empty Results

```python
{$
users = db['default'].query("SELECT * FROM users WHERE id = ?", (user_id,))

if users:
    user = users[0]
else:
    return abort(404)
$}
```

See [Template Syntax](02_TEMPLATE_SYNTAX.md) for more examples.
