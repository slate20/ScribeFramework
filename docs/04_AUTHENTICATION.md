# Authentication Guide

Understanding the built-in authentication system.

## How It Works

Projects created with `scribe new myapp --demo` include a complete login system you can copy from (a plain `scribe new` project has none, so add only what you need):

1. **Login route** (`/login`) - Validates credentials, creates session
2. **Register route** (`/register`) - Creates a user with a hashed password
3. **Logout route** (`/logout`) - Clears session
4. **Session management** - Flask sessions (server-side)
5. **Password hashing** - Werkzeug (scrypt algorithm), via `lib/basic_auth.py`

`@require_auth` protects any route (see below).

## The Login Flow

### 1. User submits login form

```python
@route('/login', methods=['GET', 'POST'])
{$
if request.method == 'POST':
    username = request.form.get('username')
    password = request.form.get('password')

    # Look up user
    users = db['default'].query(
        "SELECT * FROM users WHERE username = ?",
        (username,)
    )

    if users and verify_password(users[0]['password_hash'], password):
        session['user_id'] = users[0]['id']  # Create session
        return redirect('/dashboard')
$}
```

### 2. Session is stored

ScribeEngine uses Flask sessions (signed cookies by default).

### 3. Protected routes check session

```python
@route('/dashboard')
@require_auth
{$
# @require_auth checks if 'user_id' in session
# Redirects to /login if not authenticated
user = db['default'].find('users', session['user_id'])
$}
```

## Password Hashing

**NEVER store plain text passwords!**

### Hash a password

```python
from lib.auth_helpers import hash_password

hashed = hash_password('user_password')
# Store `hashed` in database
```

### Verify a password

```python
from lib.auth_helpers import verify_password

if verify_password(stored_hash, user_input):
    # Password correct
```

## Adding User Registration

```python
@route('/register', methods=['GET', 'POST'])
{$
page_title = "Register"
error = None

if request.method == 'POST':
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')

    # Validation
    if len(username) < 3:
        error = "Username must be at least 3 characters"
    elif len(password) < 8:
        error = "Password must be at least 8 characters"
    else:
        # Check if username exists
        existing = db['default'].query(
            "SELECT id FROM users WHERE username = ?",
            (username,)
        )

        if existing:
            error = "Username already taken"
        else:
            # Create user
            user_id = db['default'].insert('users',
                username=username,
                password_hash=hash_password(password)
            )
            session['user_id'] = user_id
            return redirect('/dashboard')
$}

<form method="POST">
    {{ csrf() }}
    <!-- form fields -->
</form>
```

## Removing Authentication

A plain `scribe new` project has no authentication to remove. In a `--demo` project:

1. **Delete auth routes** in `app.stpl`:
   - `/login`
   - `/register`
   - `/logout`

2. **Update `base.stpl` navbar** - replace the session check with static links

3. **Delete `lib/basic_auth.py`**

4. **Drop the `users` table** - remove its `Table("users", ...)` from `schemas/schema_default.py`, then run `scribe db new-migration drop_users` and put `DROP TABLE users;` in the new file (keep `migrations/002_users.sql`: migrations that already ran stay in history). Schema files never generate table drops.

5. **Remove decorators:**
   - Delete `@require_auth` from any custom routes

See [Getting Started](01_GETTING_STARTED.md) for more examples.
