# Database Guide

Learn how to work with databases in ScribeEngine.

## Configuration

Edit `scribe.json`:

```json
{
  "databases": {
    "default": {
      "type": "sqlite",
      "database": "app.db"
    }
  }
}
```

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
      "database": "analytics"
    }
  }
}
```

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

Create `migrations/002_add_posts.sql`:

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

Run: `scribe db migrate`

Migrations run in numerical order (001_, 002_, etc.).

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
