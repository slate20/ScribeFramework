"""
Authentication helper functions and decorators for ScribeEngine.

Provides:
- @require_auth decorator (configurable via scribe.json or per-route arguments)
- Login/logout helpers
- Password hashing utilities
"""

from functools import wraps
from flask import session, redirect, request
from werkzeug.security import generate_password_hash, check_password_hash


def require_auth(f=None, login_url=None, session_key=None):
    """
    Decorator to require authentication for a route.

    Resolution order for login_url and session_key:
        1. Explicit keyword argument on the decorator
        2. scribe.json  ->  auth.login_url / auth.session_key
        3. Built-in defaults  ('/login' and 'user_id')

    Args:
        f: The view function (set automatically when used as @require_auth
           with no parentheses).
        login_url: URL to redirect unauthenticated users to.
        session_key: Session key that must be present for a user to be
                     considered authenticated.

    Usage in templates:

        # Most common — zero config, uses defaults or scribe.json values:
        @route('/dashboard')
        @require_auth
        {$ ... $}

        # Override per-route:
        @route('/admin')
        @require_auth(session_key='admin_id', login_url='/admin/login')
        {$ ... $}

    scribe.json example:
        {
          "auth": {
            "session_key": "uid",
            "login_url": "/sign-in"
          }
        }
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            from flask import current_app

            # Resolve configuration, preferring explicit args over app config
            # over hard-coded defaults.
            auth_cfg = current_app.config.get('AUTH', {})

            resolved_key = (
                session_key
                or auth_cfg.get('session_key', 'user_id')
            )
            resolved_url = (
                login_url
                or auth_cfg.get('login_url', '/login')
            )

            if resolved_key not in session:
                # Remember where the user was trying to go so we can redirect
                # back after a successful login.
                session['next_url'] = request.url
                return redirect(resolved_url)

            return func(*args, **kwargs)
        return wrapper

    # Support both @require_auth (no parentheses) and
    # @require_auth(...) (with arguments).
    if f is not None:
        # Called as @require_auth with no parentheses — f is the view function.
        return decorator(f)

    # Called as @require_auth(...) — return the decorator for the next call.
    return decorator


# ---------------------------------------------------------------------------
# App factory helper — call this inside create_app() after loading config
# ---------------------------------------------------------------------------

def configure_auth(app, config: dict):
    """
    Store auth configuration on the Flask app so require_auth can read it.

    Call this from create_app() after loading scribe.json:

        configure_auth(app, app_config.get('auth', {}))

    Args:
        app: Flask application instance
        config: The 'auth' sub-dict from scribe.json (may be empty)
    """
    app.config['AUTH'] = {
        'session_key': config.get('session_key', 'user_id'),
        'login_url':   config.get('login_url',   '/login'),
    }


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """
    Hash a password using Werkzeug's secure hashing (scrypt).

    Args:
        password: Plain text password

    Returns:
        Hashed password string

    Example in template:
        {$
        password = request.form.get('password')
        hashed = hash_password(password)
        db['default'].insert('users', username=username, password=hashed)
        $}
    """
    return generate_password_hash(password, method='scrypt')


def verify_password(password_hash: str, password: str) -> bool:
    """
    Verify a password against its hash.

    Args:
        password_hash: Hashed password from database
        password: Plain text password to check

    Returns:
        True if password matches

    Example in template:
        {$
        user = db['default'].query(
            "SELECT * FROM users WHERE username = ?", (username,)
        )
        if user and verify_password(user[0]['password_hash'], password):
            session['user_id'] = user[0]['id']
            return redirect('/dashboard')
        $}
    """
    return check_password_hash(password_hash, password)


def login_user(user_id: int, remember: bool = False):
    """
    Log in a user by storing their ID in the session.

    Args:
        user_id: User ID to store in session
        remember: If True, make session permanent (30 days)
    """
    session['user_id'] = user_id

    if remember:
        session.permanent = True


def logout_user():
    """
    Log out the current user by clearing the session.

    Example in template:
        @route('/logout')
        {$
        logout_user()
        flash('You have been logged out', 'info')
        return redirect('/')
        $}
    """
    session.clear()


def get_current_user_id():
    """
    Get the current user's ID from the session.

    Returns:
        User ID or None if not logged in
    """
    return session.get('user_id')


def is_authenticated() -> bool:
    """
    Check if a user is currently authenticated.

    Returns:
        True if user is logged in
    """
    return 'user_id' in session


# ---------------------------------------------------------------------------
# AuthHelper class
# ---------------------------------------------------------------------------

class AuthHelper:
    """
    Authentication helper class that can be injected into templates.

    Example usage in template:
        {$
        if auth.login(username, password):
            return redirect('/dashboard')
        else:
            error = "Invalid credentials"
        $}
    """

    def __init__(self, db, session):
        self.db = db
        self.session = session

    def login(self, username: str, password: str, username_field: str = 'username') -> bool:
        """
        Attempt to log in with username and password.

        Args:
            username: Username or email
            password: Plain text password
            username_field: Field name to search by (default: 'username')

        Returns:
            True if login successful
        """
        users = self.db.where('users', **{username_field: username})

        if not users:
            return False

        user = users[0]

        if verify_password(user['password_hash'], password):
            login_user(user['id'])
            return True

        return False

    def logout(self):
        """Log out the current user."""
        logout_user()

    def user_id(self):
        """Get current user ID or None."""
        return get_current_user_id()

    def is_authenticated(self) -> bool:
        """Check if user is logged in."""
        return is_authenticated()

    def get_user(self):
        """
        Get the current user object from database.

        Returns:
            User Row object or None
        """
        user_id = get_current_user_id()
        if user_id:
            return self.db.find('users', user_id)
        return None
