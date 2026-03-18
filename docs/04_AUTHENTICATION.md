# Authentication Guide

Understanding the built-in authentication system.

## How It Works

Your app includes a complete login system:

1. **Login route** (`/login`) - Validates credentials, creates session
2. **Dashboard route** (`/dashboard`) - Protected with `@require_auth`
3. **Logout route** (`/logout`) - Clears session
4. **Session management** - Flask sessions (server-side)
5. **Password hashing** - Werkzeug (scrypt algorithm)

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

**Don't need auth?** Follow these steps:

1. **Delete auth routes** in `app.stpl`:
   - `/login`
   - `/dashboard`
   - `/logout`

2. **Update `base.stpl` navbar** - replace session check with static links

3. **Delete files:**
   - `lib/auth_helpers.py`
   - `migrations/001_users.sql`

4. **Remove decorators:**
   - Delete `@require_auth` from any custom routes

See [Getting Started](01_GETTING_STARTED.md) for more examples.
