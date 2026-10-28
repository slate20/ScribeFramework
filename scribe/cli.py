"""
Command-line interface for ScribeFramework.

Provides commands:
    scribe new <project>    - Create new project
    scribe dev              - Run development server
    scribe db migrate       - Run database migrations
    scribe db status        - Show applied and pending migrations
    scribe schema ...       - Describe tables in schemas/ and compare with the database
"""

import click
import os
import re
import shutil
import sys
from pathlib import Path


def _implicit_migrations_warning(target, path, pending=None, will_run=False):
    """
    Startup warning for a non-SQLite connection that doesn't say whether Scribe may change it.

    Args:
        pending: Pending migration filenames, or None if they couldn't be read
        will_run: Whether they're about to be applied
    """
    folder = os.path.relpath(target.path, path)
    lines = [f"⚠ '{target.name}' ({target.dialect}) doesn't set \"migrations\" in scribe.json, "
             f"so Scribe treats {folder}/ as its migrations folder."]
    if not os.path.isdir(target.path):
        lines.append("  That folder doesn't exist, so nothing runs today, but migrations added there would.")
    elif pending and will_run:
        lines.append(f"  Its {len(pending)} pending migration(s) there will run now.")
    elif pending:
        lines.append(f"  It has {len(pending)} pending migration(s) there.")
    lines += [
        "  If this database's schema is managed outside this app, add \"migrations\": false to its block.",
        f"  If Scribe should manage it, add \"migrations\": \"{folder}\" and \"auto_migrate\" (true or false).",
    ]
    return '\n'.join(lines)


def _implicit_migrations_refusal(target):
    """Why a command won't create migration files for a connection, or None if it may."""
    if not target.needs_explicit_migrations:
        return None
    # Only 'default' has migrations on without the key, and then the folder is always migrations/
    return (f"'{target.name}' ({target.dialect}) doesn't set \"migrations\" in scribe.json, so Scribe won't "
            f"create migrations for it. If Scribe should manage its schema, add \"migrations\": \"migrations\" "
            f"to its block (or \"migrations\": false if the schema is managed elsewhere).")


def _run_startup_migrations(db, path, migrate):
    """
    Apply or report pending migrations for each connection on dev/ide/serve startup.

    Args:
        db: The app's DatabaseManager
        path: Project directory
        migrate: --migrate/--no-migrate override; None uses each connection's auto_migrate

    Returns:
        Migration folders of the connections that auto-migrated, for the reloader to watch
    """
    from scribe.migrations import (
        get_migration_targets, get_pending_migrations, run_migrations, MigrationConfigError
    )

    try:
        targets = get_migration_targets({name: adapter.config for name, adapter in db.items()}, path)
    except MigrationConfigError as e:
        raise click.ClickException(str(e))

    watched = []
    for target in targets:
        adapter = db[target.name]
        folder = os.path.relpath(target.path, path)
        auto_migrate = target.auto_migrate if migrate is None else migrate

        # Repeats on every start until scribe.json says whether Scribe may change this database
        if target.needs_explicit_migrations:
            try:
                pending = get_pending_migrations(adapter, target.path)
            except Exception:
                adapter.rollback()
                pending = None
            click.echo('\n' + _implicit_migrations_warning(target, path, pending, will_run=auto_migrate))
            if not auto_migrate or not pending:
                continue

        elif not auto_migrate:
            try:
                pending = get_pending_migrations(adapter, target.path)
            except Exception as e:
                adapter.rollback()
                click.echo(f"\n⚠ Could not check migrations for '{target.name}': {e}")
                continue
            if pending:
                click.echo(
                    f"\n⚠ {len(pending)} pending migration(s) for '{target.name}' "
                    f"— run 'scribe db migrate --database {target.name}'"
                )
            continue

        # A non-SQLite connection auto-migrating only because the key is missing usually
        # means a SQLite block was replaced without revisiting its migration settings.
        elif migrate is None and target.auto_migrate_implicit and target.dialect != 'sqlite':
            pending = get_pending_migrations(adapter, target.path)
            if pending:
                click.echo(
                    f"\n⚠ '{target.name}' ({target.dialect}) has no 'auto_migrate' setting, so its "
                    f"{len(pending)} pending migration(s) in {folder}/ will run now.\n"
                    f"  Set \"auto_migrate\" (and \"migrations\") explicitly in its scribe.json block "
                    f"to control this."
                )

        click.echo(f"\nApplying database migrations for '{target.name}' ({folder}/)...")
        run_migrations(adapter, path, target.path)
        watched.append(target.path)

    return watched


def _report_schema_changes(db, path):
    """
    On dev startup, note connections whose schema file has changes not yet in a migration.

    Only connections with migrations enabled are checked, since only they can generate one.
    Problems are reported as a warning; they never stop the server from starting.
    """
    from scribe.migrations import get_migration_targets
    from scribe.schema.loader import schemas_dir, schema_file_path

    if not os.path.isdir(schemas_dir(path)):
        return

    try:
        targets = get_migration_targets({name: adapter.config for name, adapter in db.items()}, path)
    except Exception:
        return  # _run_startup_migrations already reported the config error

    for target in targets:
        file = schema_file_path(path, target.name)
        if not os.path.exists(file) or target.needs_explicit_migrations:
            continue
        adapter = db[target.name]
        try:
            from scribe.schema.diff import diff_schema
            from scribe.schema.generate import raw_sql_changes
            from scribe.schema.introspect import read_live_schema
            from scribe.schema.loader import load_schema

            definition = load_schema(file)
            live = read_live_schema(adapter, definition.declares)
            changes = diff_schema(definition, live, target.dialect).changes
            count = len(changes) + len(raw_sql_changes(definition, target.path))
        except Exception as e:
            adapter.rollback()
            click.echo(f"\n⚠ Could not compare {os.path.relpath(file, path)} with '{target.name}': {e}")
            continue
        if count:
            action = ("'scribe schema apply' applies the additive ones" if _apply_refusal(target, target.name) is None
                      else "'scribe schema generate' writes one")
            click.echo(
                f"\n⚠ {count} schema change(s) for '{target.name}' aren't in a migration yet "
                f"— 'scribe schema diff --database {target.name}' lists them, {action}"
            )


def _load_databases(path):
    """Load scribe.json and get its named connection blocks."""
    from scribe.app import load_config
    from scribe.migrations import get_databases_config

    return get_databases_config(load_config(path))


def _require_connection(databases, name):
    """Fail with the list of available connections if `name` isn't configured."""
    if name not in databases:
        available = ', '.join(f"'{n}'" for n in databases)
        raise click.ClickException(
            f"Database connection '{name}' not found in scribe.json. Available: {available}"
        )


def _connect(name, block):
    """Open a connection for a CLI command, turning connection failures into a one-line error."""
    from scribe.database import create_adapter

    try:
        return create_adapter(block)
    except Exception as e:
        detail = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
        raise click.ClickException(
            f"Could not connect to '{name}' ({block.get('type', 'sqlite')}): {detail}"
        )


def _resolve_migration_targets(path, database=None):
    """
    Load scribe.json and get the connections that `scribe db` commands should act on.

    Returns:
        (databases config, targets) — targets is narrowed to `database` when given
    """
    from scribe.migrations import get_migration_targets, MigrationConfigError

    databases = _load_databases(path)
    try:
        targets = get_migration_targets(databases, path)
    except MigrationConfigError as e:
        raise click.ClickException(str(e))

    if database is None:
        return databases, targets

    _require_connection(databases, database)
    targets = [target for target in targets if target.name == database]
    if not targets:
        folder = 'migrations' if database == 'default' else f'migrations/{database}'
        raise click.ClickException(
            f"Migrations are not enabled for '{database}'. To enable them, add\n"
            f"  \"migrations\": \"{folder}\"\n"
            f"to its block in scribe.json."
        )
    return databases, targets


@click.group()
@click.version_option(version="2.0.0-alpha")
def cli():
    """ScribeFramework - Write Python directly in templates"""
    pass


@cli.command()
@click.argument('project_name')
@click.option('--path', default='.', help='Parent directory for new project')
def new(project_name, path):
    """
    Create a new ScribeFramework project.

    Example:
        scribe new myapp
        scribe new myblog --path ~/projects
    """
    # Create project directory
    project_path = os.path.join(path, project_name)

    if os.path.exists(project_path):
        click.echo(f"Error: Directory '{project_path}' already exists")
        return

    click.echo(f"Creating new ScribeFramework project: {project_name}")

    # Create directory structure
    os.makedirs(project_path)
    os.makedirs(os.path.join(project_path, 'migrations'))
    os.makedirs(os.path.join(project_path, 'lib'))
    os.makedirs(os.path.join(project_path, 'static'))
    os.makedirs(os.path.join(project_path, 'static', 'css'))
    os.makedirs(os.path.join(project_path, 'static', 'js'))

    # Create scribe.json
    scribe_json = '''{
  "databases": {
    "default": {
      "type": "sqlite",
      "database": "app.db",
      "migrations": "migrations",
      "auto_migrate": true
    }
  },
  "SECRET_KEY": "CHANGE_THIS_TO_A_RANDOM_SECRET_KEY_IN_PRODUCTION"
}
'''
    with open(os.path.join(project_path, 'scribe.json'), 'w') as f:
        f.write(scribe_json)

    # Create base.stpl layout template
    base_stpl = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ page_title | default(\'{{project_name}}\') }} — Scribe</title>
    <meta name="description" content="{{ page_description | default(\'Built with ScribeFramework\') }}">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="/static/css/style.css">

    <!-- HTMX Core -->
    <script src="https://cdn.jsdelivr.net/npm/htmx.org@2.0.8/dist/htmx.min.js"></script>
    <!-- HTMX SSE Extension -->
    <script src="https://unpkg.com/htmx-ext-sse@2.2.4/sse.js"></script>

    {% block extra_head %}{% endblock %}
</head>
<body hx-headers='{"X-CSRFToken": "{{ csrf_token() }}"}'>
    <header class="navbar">
        <div class="container">
            <div class="navbar-content">
                <div class="navbar-brand">
                    <a href="/">{{project_name}}</a>
                </div>
                <nav class="navbar-links">
                    <a href="/">Home</a>
                    <a href="https://scribeframework.slatecapit.com/docs" target="_blank">Docs</a>
                    {% if session.get('user_id') %}
                        <a href="/logout">Logout</a>
                    {% else %}
                        <a href="/login">Login</a>
                    {% endif %}
                </nav>
            </div>
        </div>
    </header>

    <main class="main-content">
        <!-- Flash messages / Toasts -->
        <div id="toast-container" class="toast-container">
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="toast-message">
                            <span>{{ message }}</span>
                            <button type="button" class="close-toast" onclick="this.parentElement.remove();">&times;</button>
                        </div>
                    {% endfor %}
                {% endif %}
            {% endwith %}
        </div>

        <div class="container">
            {% block content %}
                <!-- Route content goes here -->
            {% endblock %}
        </div>
    </main>

    <footer class="footer">
        <div class="container">
            <p>&copy; 2026 {{project_name}}. Powered by ScribeFramework.</p>
        </div>
    </footer>

    <script>
        document.addEventListener(\'DOMContentLoaded\', function() {
            // Toast auto-dismiss
            const toasts = document.querySelectorAll(\'.toast-message\');
            toasts.forEach(toast => {
                setTimeout(() => {
                    toast.style.opacity = \'0\';
                    toast.style.transition = \'opacity 0.3s ease\';
                    setTimeout(() => toast.remove(), 300);
                }, 4000);
            });
        });
    </script>

    {% block extra_scripts %}{% endblock %}
</body>
</html>
'''.replace('{{project_name}}', project_name)
    with open(os.path.join(project_path, 'base.stpl'), 'w') as f:
        f.write(base_stpl)

    # Create example app.stpl
    app_stpl = r'''@route('/')
{$
page_title = "Control Center"
db_status = "Connected"
db_error = None
tasks = []

try:
    # Query tasks to verify database connection
    tasks = db['default'].query("SELECT * FROM tasks ORDER BY id DESC")
except Exception as e:
    db_status = "Error"
    db_error = str(e)
$}

<div class="panel">
    <div class="panel-header">
        <span class="status-indicator {{ 'status-ok' if db_status == 'Connected' else 'status-err' }}"></span>
        System status: Database {{ db_status }}
    </div>
    <div class="panel-body">
        <h1>Welcome to ScribeFramework</h1>
        <p class="lead">Write Python where you need it. This starter page is rendering directly from <code>app.stpl</code> and is connected to <code>app.db</code> via automatic migrations.</p>
    </div>
</div>

<div class="grid-split">
    <!-- Tasks/Database Panel -->
    <div class="panel">
        <div class="panel-header">> Database Query Example</div>
        <div class="panel-body">
            <p class="text-muted">A live list fetched from SQLite database via <code>db['default']</code>:</p>
            
            {% if db_error %}
                <div class="alert alert-error">
                    <strong>Database Error:</strong> {{ db_error }}
                </div>
            {% endif %}

            {% if tasks %}
                <ul class="task-list">
                    {% for task in tasks %}
                        <li>
                            <span class="bullet">✓</span>
                            <span class="task-title">{{ task.title }}</span>
                        </li>
                    {% endfor %}
                </ul>
            {% else %}
                <p class="text-muted italic">No tasks found in the database. Run migrations to initialize.</p>
            {% endif %}

            <div class="form-container">
                <form method="POST" action="/task/add">
                    {{ csrf() }}
                    <div class="input-group">
                        <input type="text" name="title" placeholder="Enter new task..." required autocomplete="off">
                        <button type="submit" class="btn btn-primary">Insert</button>
                    </div>
                </form>
            </div>
        </div>
    </div>

    <!-- Quick Start Panel -->
    <div class="panel">
        <div class="panel-header">> Project Blueprint</div>
        <div class="panel-body">
            <p>Your project is structured around simplicity and speed:</p>
            <ul class="blueprint-list">
                <li><strong><code>app.stpl</code></strong> — The primary router and template layout file. Write your <code>@route()</code> decorators and server-side Python logic here.</li>
                <li><strong><code>base.stpl</code></strong> — The base HTML shell that automatically wraps all routes.</li>
                <li><strong><code>scribe.json</code></strong> — Application config, database connections, and environment variables.</li>
                <li><strong><code>migrations/</code></strong> — Schema updates. Place <code>.sql</code> migrations here; they run automatically on start.</li>
                <li><strong><code>static/css/style.css</code></strong> — Branding and visual design tokens.</li>
            </ul>
            <div class="actions">
                <a href="https://scribeframework.slatecapit.com/docs" target="_blank" class="btn btn-secondary">Read the Docs</a>
                <a href="https://github.com/slate20/ScribeFramework" target="_blank" class="btn btn-secondary">GitHub</a>
            </div>
        </div>
    </div>
</div>

<div class="panel">
    <div class="panel-header">
        {% if session.get('user_id') %}
            <span class="status-indicator status-ok"></span> Authentication — Logged In
        {% else %}
            <span class="status-indicator status-err"></span> Authentication — Not Logged In
        {% endif %}
    </div>
    <div class="panel-body">
        <p>
            {% if session.get('user_id') %}
                You are currently logged in. <a href="/logout">Logout</a>
            {% else %}
                <a href="/register">Create an account</a> or <a href="/login">log in</a> to try the built-in auth system.
            {% endif %}
        </p>
        <p class="text-muted">To protect any route, add <code>@require_auth</code> directly below its <code>@route()</code> decorator:</p>
        <pre><code>&#64;route('/dashboard')
&#64;require_auth
&#123;$
# Only authenticated users reach here
user = db['default'].find('users', session['user_id'])
$&#125;</code></pre>
        <p class="text-muted">Auth helpers (<code>verify_password</code>, <code>hash_password</code>) are available in all routes via <code>lib/basic_auth.py</code>.</p>
    </div>
</div>

@route('/task/add', methods=['POST'])
{$
title = request.form.get('title', '').strip()
if title:
    db['default'].insert('tasks', title=title)
    flash('Successfully added task to database', 'success')
return redirect('/')
$}

@route('/login', methods=['GET', 'POST'])
{$
page_title = "Login"
error = None

if 'user_id' in session:
    return redirect('/')

if request.method == 'POST':
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')

    rows = db['default'].query(
        "SELECT * FROM users WHERE username = ?",
        (username,)
    )

    user = rows[0] if rows else None

    if user and verify_password(user['password_hash'], password):
        session['user_id'] = user['id']
        flash('Welcome back!', 'success')
        return redirect('/')
    else:
        error = "Invalid username or password"
$}

<div class="auth-container">
    <div class="panel auth-panel">
        <div class="panel-header">> Login</div>
        <div class="panel-body">
            {% if error %}
                <div class="alert alert-error">{{ error }}</div>
            {% endif %}
            <form method="POST" action="/login">
                {{ csrf() }}
                <div class="form-group">
                    <label for="username">Username</label>
                    <input type="text" id="username" name="username"
                           value="{{ request.form.get('username', '') }}"
                           placeholder="Username" required autofocus autocomplete="username">
                </div>
                <div class="form-group">
                    <label for="password">Password</label>
                    <input type="password" id="password" name="password"
                           placeholder="Password" required autocomplete="current-password">
                </div>
                <button type="submit" class="btn btn-primary btn-block">Login</button>
            </form>
            <p class="auth-switch">Don't have an account? <a href="/register">Register</a></p>
        </div>
    </div>
</div>

@route('/register', methods=['GET', 'POST'])
{$
page_title = "Register"
error = None

if 'user_id' in session:
    return redirect('/')

if request.method == 'POST':
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')

    if len(username) < 3:
        error = "Username must be at least 3 characters"
    elif len(password) < 8:
        error = "Password must be at least 8 characters"
    else:
        existing = db['default'].query(
            "SELECT id FROM users WHERE username = ?",
            (username,)
        )
        if existing:
            error = "Username already taken"
        else:
            user_id = db['default'].insert('users',
                username=username,
                password_hash=hash_password(password)
            )
            session['user_id'] = user_id
            flash('Account created! Welcome.', 'success')
            return redirect('/')
$}

<div class="auth-container">
    <div class="panel auth-panel">
        <div class="panel-header">> Register</div>
        <div class="panel-body">
            {% if error %}
                <div class="alert alert-error">{{ error }}</div>
            {% endif %}
            <form method="POST" action="/register">
                {{ csrf() }}
                <div class="form-group">
                    <label for="username">Username</label>
                    <input type="text" id="username" name="username"
                           value="{{ request.form.get('username', '') }}"
                           placeholder="Username" required autofocus autocomplete="username">
                </div>
                <div class="form-group">
                    <label for="password">Password</label>
                    <input type="password" id="password" name="password"
                           placeholder="Password (min 8 characters)" required autocomplete="new-password">
                </div>
                <button type="submit" class="btn btn-primary btn-block">Create Account</button>
            </form>
            <p class="auth-switch">Already have an account? <a href="/login">Login</a></p>
        </div>
    </div>
</div>

@route('/logout')
{$
session.clear()
flash('You have been logged out', 'info')
return redirect('/login')
$}

'''
    with open(os.path.join(project_path, 'app.stpl'), 'w') as f:
        f.write(app_stpl)

    # Create CSS
    css = r'''/* ================================================================
   SCRIBEFRAMEWORK — STARTER THEME: Utilitarian Brutalism
   No gradients. No rounded corners. No ceremony.
   ================================================================ */

:root {
    /* ── Brand Colors ───────────────────────────────────────────
       Your app's core visual identity. Changing these values
       is all it takes to retheme the majority of the UI.        */
    --color-primary:   #E5C07B;   /* main accent — links, focus, code  */
    --color-secondary: #98C379;   /* secondary — CTA buttons, brand    */
    --bg-base:         #0D0D0D;   /* page background                   */
    --bg-surface:      #181818;   /* card / panel background           */
    --bg-overlay:      rgba(0, 0, 0, 0.4); /* header tint, overlays   */
    --text-primary:    #ABB2BF;   /* body copy                         */
    --text-muted:      #5C6370;   /* placeholders, helper text         */
    --text-heading:    #FFFFFF;   /* h1 / h3 / h4 color                */
    --color-border:    #3E4451;   /* borders and dividers              */

    /* ── Semantic Colors ────────────────────────────────────────
       UI state colors. Independent of branding — swap freely.   */
    --color-success: #98C379;
    --color-warning: #D19A66;
    --color-danger:  #E06C75;
    --color-info:    #61AFEF;

    /* ── Borders ────────────────────────────────────────────── */
    --border-width: 1px;

    /* ── Radius ─────────────────────────────────────────────── */
    --radius: 0px;          /* set to e.g. 4px for a softer UI   */

    /* ── Shadows ────────────────────────────────────────────── */
    --shadow: 0 4px 10px rgba(0, 0, 0, 0.5);

    /* ── Typography ─────────────────────────────────────────── */
    --font-sans:   'Inter', system-ui, -apple-system, sans-serif;
    --font-mono:   'JetBrains Mono', 'Fira Code', monospace;
    --line-height: 1.6;

    /* ── Spacing ────────────────────────────────────────────── */
    --spacing-xs:  0.25rem;
    --spacing-sm:  0.5rem;
    --spacing-md:  1rem;
    --spacing-lg:  1.5rem;
    --spacing-xl:  2rem;
    --spacing-2xl: 3rem;

    /* ── Layout ─────────────────────────────────────────────── */
    --container-max-width: 1000px;

    /* ── Motion ─────────────────────────────────────────────── */
    --transition-speed: 0.1s;
}

/* ================================================================
   BASE STYLES
   ================================================================ */
* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

html {
    font-size: 16px;
    height: 100%;
}

body {
    font-family: var(--font-sans);
    color: var(--text-primary);
    background-color: var(--bg-base);
    line-height: var(--line-height);
    min-height: 100%;
    display: flex;
    flex-direction: column;
}

.main-content {
    flex: 1;
    padding: var(--spacing-xl) 0;
}

h1, h2, h3, h4 {
    font-family: var(--font-mono);
    font-weight: 700;
    color: var(--text-heading);
    margin-top: 0;
    margin-bottom: var(--spacing-md);
    letter-spacing: -0.5px;
}

h1 { font-size: 1.75rem; }
h2 { font-size: 1.35rem; color: var(--color-primary); }
h3 { font-size: 1.1rem; }

p {
    margin-bottom: var(--spacing-md);
}

p:last-child {
    margin-bottom: 0;
}

a {
    color: var(--color-primary);
    text-decoration: none;
    transition: color var(--transition-speed);
}

a:hover {
    color: var(--text-heading);
    text-decoration: underline;
    text-underline-offset: 3px;
}

.text-muted { color: var(--text-muted); }
.text-center { text-align: center; }
.italic { font-style: italic; }

/* ================================================================
   CONTAINER & LAYOUT
   ================================================================ */
.container {
    max-width: var(--container-max-width);
    margin: 0 auto;
    padding: 0 var(--spacing-xl);
}

.navbar {
    background: var(--bg-base);
    border-bottom: var(--border-width) solid var(--color-border);
    padding: var(--spacing-md) 0;
}

.navbar-content {
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.navbar-brand a {
    font-family: var(--font-mono);
    font-size: 1rem;
    font-weight: 700;
    color: var(--color-secondary);
}

.navbar-brand a::before {
    content: "> ";
    color: var(--color-primary);
}

.navbar-links {
    display: flex;
    gap: var(--spacing-md);
}

.navbar-links a {
    font-family: var(--font-mono);
    font-size: 0.85rem;
    color: var(--text-muted);
}

.navbar-links a:hover {
    color: var(--color-primary);
    text-decoration: none;
}

/* ================================================================
   PANELS & GRIDS (Utilitarian Brutalism)
   ================================================================ */
.panel {
    background: var(--bg-surface);
    border: var(--border-width) solid var(--color-border);
    border-radius: var(--radius);
    margin-bottom: var(--spacing-xl);
}

.panel-header {
    background: var(--bg-overlay);
    border-bottom: var(--border-width) solid var(--color-border);
    padding: var(--spacing-sm) var(--spacing-md);
    font-family: var(--font-mono);
    font-size: 0.8rem;
    color: var(--text-muted);
    display: flex;
    align-items: center;
    gap: var(--spacing-sm);
}

.panel-body {
    padding: var(--spacing-xl);
}

.grid-split {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--spacing-xl);
}

@media (max-width: 768px) {
    .grid-split {
        grid-template-columns: 1fr;
    }
}

.lead {
    font-size: 1.1rem;
    color: var(--text-primary);
    max-width: 720px;
}

/* Status Indicator */
.status-indicator {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
}

.status-ok { background-color: var(--color-success); }
.status-err { background-color: var(--color-danger); }

/* ================================================================
   LISTS & CONTROLS
   ================================================================ */
.task-list {
    list-style: none;
    margin-bottom: var(--spacing-lg);
}

.task-list li {
    display: flex;
    align-items: flex-start;
    gap: var(--spacing-sm);
    padding: var(--spacing-sm) 0;
    border-bottom: 1px solid rgba(62, 68, 81, 0.3);
}

.task-list li:last-child {
    border-bottom: none;
}

.bullet {
    font-family: var(--font-mono);
    color: var(--color-secondary);
    font-weight: 700;
}

.blueprint-list {
    list-style: none;
    margin-bottom: var(--spacing-lg);
}

.blueprint-list li {
    position: relative;
    padding-left: var(--spacing-md);
    margin-bottom: var(--spacing-md);
}

.blueprint-list li::before {
    content: "■";
    position: absolute;
    left: 0;
    top: 2px;
    color: var(--color-border);
    font-size: 0.7rem;
}

/* ================================================================
   FORMS & INPUTS
   ================================================================ */
.form-container {
    margin-top: var(--spacing-lg);
    border-top: var(--border-width) dashed var(--color-border);
    padding-top: var(--spacing-lg);
}

.input-group {
    display: flex;
    gap: var(--spacing-sm);
}

input[type="text"] {
    flex: 1;
    background: var(--bg-base);
    border: var(--border-width) solid var(--color-border);
    border-radius: var(--radius);
    color: var(--text-primary);
    padding: var(--spacing-sm) var(--spacing-md);
    font-family: var(--font-sans);
    font-size: 0.95rem;
    outline: none;
}

input[type="text"]:focus {
    border-color: var(--color-primary);
}

/* ================================================================
   BUTTONS
   ================================================================ */
.btn {
    display: inline-block;
    padding: var(--spacing-sm) var(--spacing-lg);
    border: var(--border-width) solid;
    border-radius: var(--radius);
    font-family: var(--font-mono);
    font-size: 0.8rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    cursor: pointer;
    background: transparent;
    transition: background-color var(--transition-speed), color var(--transition-speed);
}

.btn-primary {
    color: var(--color-secondary);
    border-color: var(--color-secondary);
}

.btn-primary:hover {
    background: var(--color-secondary);
    color: var(--bg-base);
}

.btn-secondary {
    color: var(--text-muted);
    border-color: var(--color-border);
}

.btn-secondary:hover {
    background: var(--color-border);
    color: var(--text-primary);
    text-decoration: none;
}

.actions {
    display: flex;
    gap: var(--spacing-md);
    margin-top: var(--spacing-lg);
}

/* ================================================================
   ALERTS & TOASTS
   ================================================================ */
.alert {
    padding: var(--spacing-md);
    border-left: 3px solid;
    border-radius: var(--radius);
    font-size: 0.9rem;
    margin-bottom: var(--spacing-md);
}

.alert-success {
    background: rgba(152, 195, 121, 0.1);
    color: var(--color-success);
    border-color: var(--color-success);
}

.alert-warning {
    background: rgba(209, 154, 102, 0.1);
    color: var(--color-warning);
    border-color: var(--color-warning);
}

.alert-error {
    background: rgba(224, 108, 117, 0.1);
    color: var(--color-danger);
    border-color: var(--color-danger);
}

.alert-info {
    background: rgba(97, 175, 239, 0.1);
    color: var(--color-info);
    border-color: var(--color-info);
}

/* Toast Messages */
.toast-container {
    position: fixed;
    bottom: 20px;
    right: 20px;
    z-index: 1000;
    display: flex;
    flex-direction: column;
    gap: var(--spacing-sm);
}

.toast-message {
    background: var(--bg-surface);
    border: var(--border-width) solid var(--color-border);
    border-left: 3px solid var(--color-success);
    border-radius: var(--radius);
    padding: var(--spacing-sm) var(--spacing-md);
    font-family: var(--font-mono);
    font-size: 0.8rem;
    color: var(--text-primary);
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: var(--spacing-lg);
    box-shadow: var(--shadow);
    animation: slide-in 0.2s ease-out;
}

.close-toast {
    background: none;
    border: none;
    color: var(--text-muted);
    cursor: pointer;
    font-weight: 700;
}

.close-toast:hover {
    color: var(--text-heading);
}

@keyframes slide-in {
    from { transform: translateY(20px); opacity: 0; }
    to { transform: translateY(0); opacity: 1; }
}

/* ================================================================
   CODE & DOCUMENTATION
   ================================================================ */
code {
    font-family: var(--font-mono);
    font-size: 0.85em;
    color: var(--color-primary);
    background: rgba(255, 255, 255, 0.05);
    padding: 0.1em 0.3em;
    border: 1px solid rgba(255, 255, 255, 0.1);
}

pre {
    background: rgba(0, 0, 0, 0.5);
    border: var(--border-width) solid var(--color-border);
    border-radius: var(--radius);
    padding: var(--spacing-md);
    overflow-x: auto;
    margin: var(--spacing-md) 0;
}

pre code {
    background: none;
    border: none;
    padding: 0;
    color: var(--text-primary);
}

.doc-content h1, .doc-content h2, .doc-content h3 {
    margin-top: var(--spacing-xl);
}

.doc-content h1:first-child {
    margin-top: 0;
}

.doc-content p, .doc-content ul, .doc-content ol {
    margin-bottom: var(--spacing-md);
}

.doc-content ul, .doc-content ol {
    padding-left: var(--spacing-xl);
}

.doc-content li {
    margin-bottom: var(--spacing-xs);
}

/* ================================================================
   FOOTER
   ================================================================ */
.footer {
    border-top: var(--border-width) solid var(--color-border);
    padding: var(--spacing-xl) 0;
    margin-top: var(--spacing-2xl);
}

.footer p {
    font-family: var(--font-mono);
    font-size: 0.75rem;
    color: var(--text-muted);
}

/* ================================================================
   AUTH FORMS
   ================================================================ */
.auth-container {
    display: flex;
    justify-content: center;
    padding: var(--spacing-xl) 0;
}

.auth-panel {
    width: 100%;
    max-width: 420px;
}

.form-group {
    margin-bottom: var(--spacing-md);
}

.form-group label {
    display: block;
    font-family: var(--font-mono);
    font-size: 0.8rem;
    color: var(--text-muted);
    margin-bottom: var(--spacing-xs);
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

.form-group input[type="text"],
.form-group input[type="password"] {
    width: 100%;
    background: var(--bg-base);
    border: var(--border-width) solid var(--color-border);
    border-radius: var(--radius);
    color: var(--text-primary);
    padding: var(--spacing-sm) var(--spacing-md);
    font-family: var(--font-sans);
    font-size: 0.95rem;
    outline: none;
}

.form-group input[type="text"]:focus,
.form-group input[type="password"]:focus {
    border-color: var(--color-primary);
}

.btn-block {
    width: 100%;
    text-align: center;
    margin-top: var(--spacing-md);
    padding: var(--spacing-md);
}

.auth-switch {
    margin-top: var(--spacing-md);
    text-align: center;
    font-size: 0.85rem;
    color: var(--text-muted);
}
'''
    with open(os.path.join(project_path, 'static', 'css', 'style.css'), 'w') as f:
        f.write(css)

    # Create initial migration SQL
    initial_sql = r'''-- Initial migration: Create tasks table
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    completed BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert starting tasks to verify database read
INSERT INTO tasks (title) VALUES
    ('Run "scribe dev" to start local development server'),
    ('Open "app.stpl" to explore routes and templates'),
    ('Add your own database tables in "migrations/"');
'''
    with open(os.path.join(project_path, 'migrations', '001_initial.sql'), 'w') as f:
        f.write(initial_sql)

    # Create users migration
    users_sql = '''CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
'''
    with open(os.path.join(project_path, 'migrations', '002_users.sql'), 'w') as f:
        f.write(users_sql)

    # Create lib/basic_auth.py
    basic_auth_py = '''"""Authentication helpers - auto-loaded into all templates"""
from werkzeug.security import check_password_hash, generate_password_hash


def verify_password(password_hash, password):
    if password is None or password_hash is None:
        return False
    return check_password_hash(password_hash, password)


def hash_password(password):
    return generate_password_hash(password)
'''
    with open(os.path.join(project_path, 'lib', 'basic_auth.py'), 'w') as f:
        f.write(basic_auth_py)

    # Create README
    readme = f'''# {project_name}

A ScribeFramework web application.

## Quick Start

1. Start the development server with auto-reload enabled:
   ```bash
   scribe dev
   ```

2. Open [http://localhost:5000](http://localhost:5000) in your browser.

## Project Structure

* **`app.stpl`** — Your main application code. Route definitions and Jinja2 templates live here.
* **`base.stpl`** — Base HTML template layout.
* **`scribe.json`** — Configuration (database connections, secret keys).
* **`migrations/`** — Schema migration scripts. Executed automatically on startup.
* **`static/`** — Static assets, including custom CSS.
'''
    with open(os.path.join(project_path, 'README.md'), 'w') as f:
        f.write(readme)

    # Create .gitignore
    gitignore = '''# Database
*.db
*.sqlite
*.sqlite3

# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
venv/
env/
ENV/

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# ScribeFramework
scribe.json  # May contain secrets
'''
    with open(os.path.join(project_path, '.gitignore'), 'w') as f:
        f.write(gitignore)

    click.echo(f"\n✓ Created project: {project_name}")
    click.echo(f"\nNext steps:")
    click.echo(f"  cd {project_name}")
    click.echo(f"  scribe dev")
    click.echo(f"\nThen:")
    click.echo(f"  1. Open http://localhost:5000")
    click.echo(f"  2. Edit app.stpl to add your own routes")
    click.echo(f"  3. Visit https://scribeframework.com/docs for guides")


@cli.command()
@click.option('--host', default='127.0.0.1', help='Host to bind to')
@click.option('--port', default=5000, type=int, help='Port to bind to')
@click.option('--debug/--no-debug', default=True, help='Enable debug mode')
@click.option('--no-reload', is_flag=True, help='Disable auto-reload on file changes')
@click.option('--migrate/--no-migrate', default=None,
              help="Apply pending migrations on startup (overrides each connection's auto_migrate)")
@click.option('--path', default='.', help='Project directory')
def dev(host, port, debug, no_reload, migrate, path):
    """
    Run development server for your ScribeFramework application.

    Example:
        scribe dev                    # Run on localhost:5000
        scribe dev --port 3000        # Custom port
        scribe dev --no-reload        # Disable auto-reload
        scribe dev --host 0.0.0.0     # Allow external connections
        scribe dev --no-migrate       # Skip applying migrations this run

    To use the IDE, run 'scribe ide' in a separate terminal.
    """
    from scribe.app import create_app
    import glob

    click.echo(f"Starting ScribeFramework development server...")
    click.echo(f"Project: {os.path.abspath(path)}")

    # Create app
    app = create_app(path)

    # Apply (or report) pending migrations, then note schema changes not in a migration yet
    migration_folders = _run_startup_migrations(app.config['DB'], path, migrate)
    _report_schema_changes(app.config['DB'], path)

    # Configure auto-reload to watch project files
    extra_files = []
    use_reloader = not no_reload

    if use_reloader:
        # Watch .stpl template files
        extra_files.extend(glob.glob(os.path.join(path, '**/*.stpl'), recursive=True))
        # Watch lib/ Python files
        extra_files.extend(glob.glob(os.path.join(path, 'lib/**/*.py'), recursive=True))
        # Watch migrations of connections that apply them on startup
        for folder in migration_folders:
            extra_files.extend(glob.glob(os.path.join(folder, '*.sql')))
        # Watch schema files, so the schema-change notice stays current
        extra_files.extend(glob.glob(os.path.join(path, 'schemas', '*.py')))
        # Watch config
        config_file = os.path.join(path, 'scribe.json')
        if os.path.exists(config_file):
            extra_files.append(config_file)

        click.echo(f"  Auto-reload: ENABLED - watching {len(extra_files)} project files")
    else:
        click.echo(f"  Auto-reload: DISABLED")

    # Run server
    click.echo(f"\n✓ Development server running at http://{host}:{port}")
    click.echo(f"  Press CTRL+C to quit")
    click.echo(f"\n💡 Tip: Run 'scribe ide' in another terminal to open the IDE\n")

    app.run(
        host=host,
        port=port,
        debug=debug,
        use_reloader=use_reloader,
        extra_files=extra_files if use_reloader else None
    )


@cli.command()
@click.option('--host', default='127.0.0.1', help='Host to bind to')
@click.option('--port', default=5001, type=int, help='Port to bind to')
@click.option('--app-port', default=5000, type=int, help='Port where app server is running (for preview)')
@click.option('--debug/--no-debug', default=True, help='Enable debug mode')
@click.option('--no-reload', is_flag=True, help='Disable auto-reload on file changes')
@click.option('--migrate/--no-migrate', default=None,
              help="Apply pending migrations on startup (overrides each connection's auto_migrate)")
@click.option('--path', default='.', help='Project directory')
def ide(host, port, app_port, debug, no_reload, migrate, path):
    """
    Run the ScribeFramework IDE (web-based code editor).

    The IDE provides:
    - Code editor with .stpl syntax highlighting
    - Live preview of your app
    - Database browser
    - File management
    - Route explorer

    Example:
        scribe ide                        # Run IDE on localhost:5001
        scribe ide --port 3001            # Custom IDE port
        scribe ide --app-port 8000        # Preview app on port 8000
        scribe ide --host 0.0.0.0         # Allow remote access (use with caution)

    Note: Run 'scribe dev' in a separate terminal to start your app server.
    """
    from scribe.app import create_standalone_gui_app
    import glob

    # Security warning if not localhost
    if host != '127.0.0.1' and host != 'localhost':
        click.echo("\n⚠️  WARNING: IDE will be accessible from other machines!")
        click.echo("   Only use --host 0.0.0.0 on trusted networks.")
        click.echo("   Consider adding authentication for remote access.\n")

    click.echo(f"Starting ScribeFramework IDE...")
    click.echo(f"Project: {os.path.abspath(path)}")

    # Create GUI app
    gui_app = create_standalone_gui_app(path)

    # Configure app server port for preview
    gui_app.config['APP_SERVER_PORT'] = app_port

    # Apply (or report) pending migrations, so the database browser is current
    migration_folders = _run_startup_migrations(gui_app.config['DB'], path, migrate)

    # Configure auto-reload to watch project files
    extra_files = []
    use_reloader = not no_reload

    if use_reloader:
        # Watch .stpl template files
        extra_files.extend(glob.glob(os.path.join(path, '**/*.stpl'), recursive=True))
        # Watch lib/ Python files
        extra_files.extend(glob.glob(os.path.join(path, 'lib/**/*.py'), recursive=True))
        # Watch migrations of connections that apply them on startup
        for folder in migration_folders:
            extra_files.extend(glob.glob(os.path.join(folder, '*.sql')))
        # Watch config
        config_file = os.path.join(path, 'scribe.json')
        if os.path.exists(config_file):
            extra_files.append(config_file)

        click.echo(f"  Auto-reload: ENABLED - watching {len(extra_files)} project files")
    else:
        click.echo(f"  Auto-reload: DISABLED")

    # Run IDE server
    click.echo(f"\n✓ IDE running at http://{host}:{port}")
    click.echo(f"  Preview target: http://localhost:{app_port}")
    click.echo(f"  Press CTRL+C to quit")
    click.echo(f"\n💡 Tip: Make sure 'scribe dev' is running on port {app_port}\n")

    gui_app.run(
        host=host,
        port=port,
        debug=debug,
        use_reloader=use_reloader,
        extra_files=extra_files if use_reloader else None
    )


@cli.command()
@click.option('--host', default='0.0.0.0', help='Host to bind to')
@click.option('--port', default=8000, type=int, help='Port to bind to')
@click.option('--threads', default=4, type=int, help='Number of threads')
@click.option('--migrate/--no-migrate', default=None,
              help="Apply pending migrations on startup (overrides each connection's auto_migrate)")
@click.option('--path', default='.', help='Project directory')
def serve(host, port, threads, migrate, path):
    """
    Run production server using Waitress.

    Uses the Waitress WSGI server - production-ready, multi-threaded,
    and fully self-contained. No external dependencies required.

    Example:
        scribe serve
        scribe serve --host 0.0.0.0 --port 8000
        scribe serve --threads 8
        scribe serve --no-migrate     # Run 'scribe db migrate' as a separate deploy step
    """
    from scribe.app import create_app
    from waitress import serve as waitress_serve

    click.echo(f"Starting ScribeFramework production server...")
    click.echo(f"Project: {os.path.abspath(path)}")

    # Create Flask app (production mode)
    app = create_app(path)

    # Apply (or report) pending migrations
    _run_startup_migrations(app.config['DB'], path, migrate)

    # Start server
    click.echo(f"\n✓ Production server running at http://{host}:{port}")
    click.echo(f"  Server: Waitress (production WSGI)")
    click.echo(f"  Threads: {threads}")
    click.echo(f"  Press CTRL+C to quit\n")

    # Run with Waitress - production-ready WSGI server
    waitress_serve(app, host=host, port=port, threads=threads)


@cli.group(name='db')
def db_commands():
    """Database management commands"""
    pass


@db_commands.command()
@click.option('--database', default=None,
              help='Connection name (default: every connection with migrations enabled)')
@click.option('--path', default='.', help='Project directory')
def migrate(database, path):
    """
    Run database migrations.

    Example:
        scribe db migrate                       # All connections with migrations enabled
        scribe db migrate --database analytics  # One connection
    """
    from scribe.migrations import run_migrations

    databases, targets = _resolve_migration_targets(path, database)
    if not targets:
        click.echo("No database connections have migrations enabled.")
        return

    for target in targets:
        click.echo(f"Running migrations for '{target.name}' ({os.path.relpath(target.path, path)}/)...")
        db = _connect(target.name, databases[target.name])
        try:
            run_migrations(db, path, target.path)
        except Exception:
            # run_migrations already reported which file failed
            sys.exit(1)
        finally:
            db.close()
        click.echo()


@db_commands.command()
@click.option('--database', default=None,
              help='Connection name (default: every connection in scribe.json)')
@click.option('--path', default='.', help='Project directory')
def status(database, path):
    """
    Show applied and pending migrations for each connection (read-only).

    Example:
        scribe db status
        scribe db status --database analytics
    """
    from scribe.migrations import get_applied_migrations, get_pending_migrations

    databases, targets = _resolve_migration_targets(path)
    if database is not None:
        _require_connection(databases, database)
    targets_by_name = {target.name: target for target in targets}
    names = [database] if database else list(databases)

    for name in names:
        target = targets_by_name.get(name)
        if target is None:
            click.echo(f"{name}: migrations disabled\n")
            continue

        auto = 'on' if target.auto_migrate else 'off'
        if target.auto_migrate_implicit:
            auto += ' (default)'
        click.echo(f"{name}: {os.path.relpath(target.path, path)}/  auto_migrate: {auto}")
        if target.needs_explicit_migrations:
            click.echo(f"  ⚠ \"migrations\" isn't set for this {target.dialect} connection; add \"migrations\": false "
                       f"if its schema is managed elsewhere")

        if not os.path.isdir(target.path):
            click.echo("  (folder does not exist)\n")
            continue

        db = _connect(name, databases[name])
        try:
            applied = get_applied_migrations(db)
            pending = get_pending_migrations(db, target.path)
        except Exception as e:
            click.echo(f"  ✗ Could not read migration state: {e}\n")
            continue
        finally:
            db.close()

        for filename in applied:
            click.echo(f"  ✓ {filename}")
        for filename in pending:
            click.echo(f"  • {filename}  (pending)")
        if not applied and not pending:
            click.echo("  (no migration files)")
        click.echo()


@db_commands.command()
@click.argument('name')
@click.option('--database', default=None, help="Connection to create it for (default: 'default')")
@click.option('--path', default='.', help='Project directory')
def new_migration(name, database, path):
    """
    Create a new migration file.

    Example:
        scribe db new-migration create_users
        scribe db new-migration add_page_views --database analytics
    """
    from scribe.migrations import create_migration

    _, targets = _resolve_migration_targets(path, database or 'default')
    target = targets[0]
    refusal = _implicit_migrations_refusal(target)
    if refusal:
        raise click.ClickException(refusal)

    filepath = create_migration(path, name, target.path)
    click.echo(f"\n✓ Created migration: {filepath}")
    click.echo(f"\nEdit the file to add your SQL statements, then run:")
    if target.name == 'default':
        click.echo(f"  scribe db migrate")
    else:
        click.echo(f"  scribe db migrate --database {target.name}")


@cli.group(name='schema')
def schema_commands():
    """Schema files: describe tables in schemas/ and compare them with the database"""
    pass


def _schema_connections(path, database):
    """Connection blocks the schema commands act on: one with --database, otherwise all."""
    databases = _load_databases(path)
    if database is None:
        return databases
    _require_connection(databases, database)
    return {database: databases[database]}


def _read_live_schema(name, block, table_filter=None):
    """
    Connect to a database and read its tables, with CLI-friendly errors.

    Returns:
        (live tables accepted by table_filter, total number of tables in the database)
    """
    from scribe.schema.introspect import read_live_schema_counted

    db = _connect(name, block)
    try:
        return read_live_schema_counted(db, table_filter)
    except NotImplementedError as e:
        raise click.ClickException(f"'{name}': {e}")
    finally:
        db.close()


def _load_schema_file(file):
    from scribe.schema import SchemaError
    from scribe.schema.loader import load_schema

    try:
        return load_schema(file)
    except SchemaError as e:
        raise click.ClickException(str(e))


def _no_schemas_dir(path):
    from scribe.schema.loader import schemas_dir

    if os.path.isdir(schemas_dir(path)):
        return False
    click.echo("No schemas/ directory, so this project uses .sql migrations only.")
    click.echo("Run 'scribe schema pull' to describe an existing database, or 'scribe schema init' to start empty.")
    return True


@schema_commands.command()
@click.option('--path', default='.', help='Project directory')
def init(path):
    """
    Create schemas/ with an empty schema file for each connection.

    Existing schema files are left untouched.

    Example:
        scribe schema init
    """
    from scribe.schema.loader import schema_file_path
    from scribe.schema.writer import write_init_file

    for name, block in _load_databases(path).items():
        file = schema_file_path(path, name)
        rel = os.path.relpath(file, path)
        if write_init_file(file, name, block.get('type', 'sqlite').lower()):
            click.echo(f"✓ Created {rel}")
        else:
            click.echo(f"  {rel} already exists")

    click.echo("\nNext: 'scribe schema pull' adds the tables already in each database.")


@schema_commands.command()
@click.option('--database', default=None, help='Connection name (default: every connection)')
@click.option('--include', multiple=True,
              help='Table pattern to pull, e.g. "orders", "hr_*", "reporting.*" (repeatable; new schema files only)')
@click.option('--exclude', multiple=True, help='Table pattern to leave out (repeatable; new schema files only)')
@click.option('--path', default='.', help='Project directory')
def pull(database, include, exclude, path):
    """
    Add tables from the live database to schemas/schema_{name}.py.

    Read-only on the database. New tables are written with managed=False;
    tables the file already declares are never changed. Only tables in the
    file's scope() are pulled. When creating a new schema file, --include
    and --exclude set that scope and are written into the file.

    Example:
        scribe schema pull
        scribe schema pull --database erp --include "orders" --include "reporting.*"
    """
    from scribe.schema import SchemaError
    from scribe.schema.dsl import Scope
    from scribe.schema.loader import schema_file_path
    from scribe.schema.writer import pull_into_file

    for name, block in _schema_connections(path, database).items():
        dialect = block.get('type', 'sqlite').lower()
        file = schema_file_path(path, name)
        rel = os.path.relpath(file, path)

        new_scope = None
        if os.path.exists(file):
            if include or exclude:
                raise click.ClickException(
                    f"{rel} already exists, so --include/--exclude can't change what it covers. "
                    f"Edit (or add) the scope(include=[...], exclude=[...]) call in {rel} instead."
                )
            table_filter = _load_schema_file(file).in_scope
        elif include or exclude:
            try:
                new_scope = Scope(list(include) or None, list(exclude) or None)
            except SchemaError as e:
                raise click.ClickException(str(e))
            table_filter = new_scope.matches
        else:
            table_filter = None

        live, total = _read_live_schema(name, block, table_filter)
        try:
            added, skipped = pull_into_file(file, name, dialect, list(live.values()), new_scope)
        except SchemaError as e:
            raise click.ClickException(f"{e}\n{rel} was left unchanged.")

        in_scope = f" ({len(live)} of {total} tables in scope)" if len(live) < total else ""
        if added:
            click.echo(f"✓ {name}: added {len(added)} table(s) to {rel} as managed=False{in_scope}")
            for table in added:
                click.echo(f"    {table}")
        else:
            click.echo(f"  {name}: no new tables ({len(skipped)} already in {rel}){in_scope}")
        if new_scope is not None:
            click.echo(f"  Wrote {new_scope!r} to {rel}; edit it there to change what later pulls add.")

    click.echo("\nSet managed=True on the tables Scribe should own, then run 'scribe schema diff'.")


_CHANGE_SYMBOLS = {'additive': '+', 'review': '!', 'destructive': '-'}


def _change_symbol(change):
    if change.additive:
        return _CHANGE_SYMBOLS['additive']
    return _CHANGE_SYMBOLS['destructive'] if change.destructive else _CHANGE_SYMBOLS['review']


class _SchemaCheck:
    """A connection's schema file compared with its database, for the schema commands."""

    def __init__(self, name, block, file, definition=None, live=None, diff=None, target=None, raw=(),
                 total_tables=0):
        self.name = name
        self.block = block
        self.dialect = block.get('type', 'sqlite').lower()
        self.file = file
        self.definition = definition    # None when the connection has no schema file
        self.live = live
        self.diff = diff
        self.target = target            # MigrationTarget, or None when migrations are disabled
        self.raw = list(raw)            # raw_sql blocks not yet in a generated migration
        self.total_tables = total_tables  # tables in the database, in scope or not

    @property
    def change_count(self):
        return len(self.diff.changes) + len(self.raw) if self.diff else 0


def _check_schemas(path, database, untracked=False):
    """
    Load and diff each connection's schema file.

    Args:
        untracked: Also read in-scope tables the file doesn't declare, so the diff
                   can list them as untracked (for status). Otherwise only declared
                   tables are read, which is all diff/generate/apply compare.

    Yields:
        _SchemaCheck per connection (with definition=None when it has no schema file)
    """
    from scribe.migrations import get_migration_targets, MigrationConfigError
    from scribe.schema.diff import diff_schema
    from scribe.schema.generate import raw_sql_changes
    from scribe.schema.loader import schema_file_path

    try:
        targets = {t.name: t for t in get_migration_targets(_load_databases(path), path)}
    except MigrationConfigError as e:
        raise click.ClickException(str(e))

    for name, block in _schema_connections(path, database).items():
        file = schema_file_path(path, name)
        target = targets.get(name)
        if not os.path.exists(file):
            if database is not None:
                raise click.ClickException(
                    f"No schema file for '{name}'. Run 'scribe schema pull --database {name}' to create one."
                )
            yield _SchemaCheck(name, block, file, target=target)
            continue

        definition = _load_schema_file(file)
        live, total = _read_live_schema(name, block, definition.in_scope if untracked else definition.declares)
        dialect = block.get('type', 'sqlite').lower()
        # raw_sql blocks are tracked through generated migrations, so only connections with migrations have them
        raw = raw_sql_changes(definition, target.path) if target else []
        yield _SchemaCheck(name, block, file, definition, live, diff_schema(definition, live, dialect), target, raw,
                           total_tables=total)


@schema_commands.command()
@click.option('--database', default=None, help='Connection name (default: every connection with a schema file)')
@click.option('--path', default='.', help='Project directory')
def diff(database, path):
    """
    Show differences between managed tables and the live database (read-only).

    + additive change   ! needs review   - would drop data

    Example:
        scribe schema diff
        scribe schema diff --database analytics
    """
    if _no_schemas_dir(path):
        return

    for check in _check_schemas(path, database):
        if check.definition is None:
            continue
        result = check.diff
        click.echo(f"{check.name} ({check.dialect}) — {os.path.relpath(check.file, path)}")

        if not check.change_count:
            click.echo(f"  ✓ No differences in {len(result.in_sync)} managed table(s)\n")
            continue

        for table in result.changed_tables():
            click.echo(f"  {table}")
            for change in result.changes:
                if change.table != table:
                    continue
                target = f"{change.column}: " if change.column else ""
                click.echo(f"    {_change_symbol(change)} {target}{change.description}")

        if check.raw:
            click.echo("  raw_sql")
            for raw in check.raw:
                symbol = '+' if raw.status == 'new' else '!'
                click.echo(f"    {symbol} {raw.name}: {raw.status} since the last generated migration")

        review = result.needs_review + [r for r in check.raw if r.status != 'new']
        destructive = [c for c in result.needs_review if c.destructive]
        additive = len(result.additive) + len([r for r in check.raw if r.status == 'new'])
        summary = f"  {additive} additive, {len(review)} need review"
        if destructive:
            summary += f" ({len(destructive)} would drop data)"
        click.echo(summary + "\n")


@schema_commands.command(name='status')
@click.option('--database', default=None, help='Connection name (default: every connection)')
@click.option('--path', default='.', help='Project directory')
def schema_status(database, path):
    """
    Summarize managed tables, drift, and pending migrations (read-only).

    Example:
        scribe schema status
    """
    from scribe.migrations import get_pending_migrations

    if _no_schemas_dir(path):
        return

    for check in _check_schemas(path, database, untracked=True):
        name = check.name
        rel = os.path.relpath(check.file, path)
        if check.definition is None:
            click.echo(f"{name} ({check.dialect}): no schema file — "
                       f"'scribe schema pull --database {name}' creates one\n")
            continue

        result = check.diff
        click.echo(f"{name} ({check.dialect}) — {rel}")
        changed = result.changed_tables()
        managed = len(result.in_sync) + len(changed)
        line = f"  managed:     {managed} table(s)"
        if managed:
            line += f" — {len(result.in_sync)} in sync"
            if changed:
                line += f", {len(changed)} with changes ({', '.join(changed)})"
        click.echo(line)
        click.echo(f"  unmanaged:   {len(result.unmanaged)} table(s)")
        if check.definition.scope is not None:
            click.echo(f"  scope:       {len(check.live)} of {check.total_tables} database table(s) "
                       f"— {check.definition.scope!r}")

        if result.untracked:
            click.echo(f"  untracked:   {len(result.untracked)} table(s) in the database aren't in {rel}: "
                       f"{', '.join(result.untracked)}")
            click.echo(f"               'scribe schema pull --database {name}' adds them")

        if result.changes:
            click.echo(f"  changes:     {len(result.additive)} additive, {len(result.needs_review)} need review "
                       f"— 'scribe schema diff --database {name}' lists them")

        blocks = len(check.definition.raw_sql)
        if blocks or check.raw:
            line = f"  raw_sql:     {blocks} block(s)"
            if check.target is None:
                line += " (not tracked: migrations are disabled)"
            elif check.raw:
                line += f", {len(check.raw)} not in a migration yet"
            click.echo(line)

        if check.target is None:
            click.echo("  migrations:  disabled")
        else:
            db = _connect(check.name, check.block)
            try:
                pending = get_pending_migrations(db, check.target.path)
            finally:
                db.close()
            click.echo(f"  migrations:  {len(pending)} pending" + (" — 'scribe db migrate'" if pending else ""))
        click.echo()


def _migration_slug(name, tables):
    """File name part for a generated migration: --name, or derived from the tables it touches."""
    if name:
        slug = name
    elif tables:
        slug = 'schema_' + '_'.join(t.rpartition('.')[2] for t in tables[:3])
        if len(tables) > 3:
            slug += '_etc'
    else:
        slug = 'schema_raw_sql'
    return re.sub(r'[^A-Za-z0-9_]+', '_', slug).strip('_').lower() or 'schema'


@schema_commands.command()
@click.option('--database', default=None,
              help='Connection name (default: every connection with a schema file and migrations enabled)')
@click.option('--name', 'migration_name', default=None, help='Migration file name (default: from the tables changed)')
@click.option('--dry-run', is_flag=True, help='Print the migration instead of writing it')
@click.option('--force', is_flag=True, help='Write the file even if every change is commented out for review')
@click.option('--path', default='.', help='Project directory')
def generate(database, migration_name, dry_run, force, path):
    """
    Write a .sql migration from the differences between schema files and the database.

    Additive changes are written as SQL that runs. Changes that could lose
    data or can't be made in place are written commented-out under
    "-- REVIEW" for you to check. Apply the file with 'scribe db migrate'.

    Example:
        scribe schema generate
        scribe schema generate --database analytics --name add_page_views
        scribe schema generate --dry-run
    """
    from scribe.migrations import get_pending_migrations, next_migration_filename
    from scribe.schema.generate import generate_migration

    if _no_schemas_dir(path):
        return

    for check in _check_schemas(path, database):
        name = check.name
        if check.definition is None:
            continue
        if check.target is None or check.target.needs_explicit_migrations:
            folder = 'migrations' if name == 'default' else f'migrations/{name}'
            message = (_implicit_migrations_refusal(check.target) if check.target else
                       f"Migrations are not enabled for '{name}', so there's nowhere to write the migration. "
                       f"To enable them, add\n  \"migrations\": \"{folder}\"\nto its block in scribe.json.")
            if database is not None:
                raise click.ClickException(message)
            click.echo(f"{name}: skipped. {message}\n")
            continue

        if not check.change_count:
            click.echo(f"{name}: nothing to generate — the database matches {os.path.relpath(check.file, path)}")
            continue

        # The diff is against the live database, so unapplied migrations would be generated again
        db = _connect(check.name, check.block)
        try:
            pending = get_pending_migrations(db, check.target.path)
        finally:
            db.close()
        if pending:
            raise click.ClickException(
                f"'{name}' has {len(pending)} pending migration(s) ({', '.join(pending)}). "
                f"Run 'scribe db migrate --database {name}' first so the diff includes them."
            )

        migration = generate_migration(
            check.definition, check.diff, check.live, check.dialect, name,
            os.path.relpath(check.file, path), check.raw,
        )

        if dry_run:
            click.echo(migration.sql)
            continue

        if migration.live == 0 and not force:
            click.echo(
                f"{name}: all {migration.review} change(s) need review, so the migration would run nothing.\n"
                f"  Run 'scribe schema diff --database {name}' to see them, '--dry-run' to see the SQL, "
                f"or '--force' to write the commented-out file anyway.\n"
            )
            continue

        os.makedirs(check.target.path, exist_ok=True)
        filename = next_migration_filename(check.target.path, _migration_slug(migration_name, migration.tables))
        file = os.path.join(check.target.path, filename)
        with open(file, 'w', encoding='utf-8') as f:
            f.write(migration.sql)

        rel = os.path.relpath(file, path)
        click.echo(f"✓ {name}: wrote {rel}")
        click.echo(f"  {migration.live} statement(s) will run, {migration.review} commented out for review")
        if check.target.auto_migrate:
            click.echo(f"  auto_migrate is on: it will run on the next 'scribe dev', 'scribe ide', or "
                       f"'scribe serve' start. Review it before then, or run 'scribe db migrate'.")
        else:
            click.echo(f"  Review it, then run 'scribe db migrate"
                       f"{'' if name == 'default' else ' --database ' + name}'.")
        click.echo()


def _apply_refusal(target, name):
    """Why `scribe schema apply` won't run on a connection, or None if it may."""
    if target is None:
        folder = 'migrations' if name == 'default' else f'migrations/{name}'
        return (f"Migrations are not enabled for '{name}'. To enable them, add\n"
                f"  \"migrations\": \"{folder}\"\nto its block in scribe.json.")
    if target.needs_explicit_migrations:
        return _implicit_migrations_refusal(target)
    if not target.auto_migrate:
        return (f"'{name}' has auto_migrate off, so its migrations are applied deliberately. "
                f"Use 'scribe schema generate', review the file, then 'scribe db migrate'.")
    if target.auto_migrate_implicit and target.dialect != 'sqlite':
        return (f"'{name}' ({target.dialect}) has no explicit \"auto_migrate\" setting. "
                f"Set \"auto_migrate\": true in its scribe.json block to allow 'scribe schema apply' on it.")
    return None


@schema_commands.command()
@click.option('--database', default=None,
              help='Connection name (default: every eligible connection with a schema file)')
@click.option('--name', 'migration_name', default=None, help='Migration file name (default: from the tables changed)')
@click.option('--dry-run', is_flag=True, help='Print the migration instead of writing and running it')
@click.option('--path', default='.', help='Project directory')
def apply(database, migration_name, dry_run, path):
    """
    Generate a migration with only the additive changes, and run it now.

    For local development on connections with "auto_migrate": true. The
    migration file is written like any other, so commit it with your schema
    change and other databases get it through 'scribe db migrate'. Changes
    that need review are left out; 'scribe schema generate' handles those.

    Example:
        scribe schema apply
        scribe schema apply --database default --name add_due_date
    """
    from scribe.migrations import (
        get_migration_targets, get_pending_migrations, next_migration_filename, run_migrations,
        MigrationConfigError,
    )
    from scribe.schema.diff import SchemaDiff
    from scribe.schema.generate import generate_migration
    from scribe.schema.loader import schema_file_path

    if _no_schemas_dir(path):
        return

    try:
        targets = {t.name: t for t in get_migration_targets(_load_databases(path), path)}
    except MigrationConfigError as e:
        raise click.ClickException(str(e))

    for name, block in _schema_connections(path, database).items():
        if not os.path.exists(schema_file_path(path, name)):
            if database is not None:
                raise click.ClickException(
                    f"No schema file for '{name}'. Run 'scribe schema pull --database {name}' to create one."
                )
            continue
        target = targets.get(name)
        refusal = _apply_refusal(target, name)
        if refusal:
            if database is not None:
                raise click.ClickException(refusal)
            click.echo(f"{name}: skipped. {refusal}\n")
            continue

        # This connection would run pending migrations on its next start anyway; do it now
        # so the diff reflects them.
        db = _connect(name, block)
        try:
            pending = get_pending_migrations(db, target.path)
            if pending and not dry_run:
                click.echo(f"{name}: running {len(pending)} pending migration(s) first")
                try:
                    run_migrations(db, path, target.path)
                except Exception:
                    raise click.ClickException(f"A pending migration for '{name}' failed; fix it and try again.")
        finally:
            db.close()
        if pending and dry_run:
            raise click.ClickException(
                f"'{name}' has {len(pending)} pending migration(s); without --dry-run they'd run first. "
                f"Run 'scribe db migrate --database {name}' to apply them, then try again."
            )

        check = next(_check_schemas(path, name))
        additive = SchemaDiff(changes=[c for c in check.diff.changes if c.additive])
        raw = [r for r in check.raw if r.status == 'new']
        left_out = len(check.diff.changes) - len(additive.changes) + len(check.raw) - len(raw)

        if not additive.changes and not raw:
            message = f"{name}: nothing to apply"
            if left_out:
                message += (f" — {left_out} change(s) need review; "
                            f"'scribe schema generate' writes them commented out")
            click.echo(message)
            continue

        migration = generate_migration(
            check.definition, additive, check.live, check.dialect, name,
            os.path.relpath(check.file, path), raw,
        )
        if dry_run:
            click.echo(migration.sql)
            continue

        os.makedirs(target.path, exist_ok=True)
        filename = next_migration_filename(target.path, _migration_slug(migration_name, migration.tables))
        file = os.path.join(target.path, filename)
        rel = os.path.relpath(file, path)
        with open(file, 'w', encoding='utf-8') as f:
            f.write(migration.sql)
        click.echo(f"✓ {name}: wrote {rel} ({migration.live} statement(s))")

        db = _connect(name, block)
        try:
            run_migrations(db, path, target.path)
        except Exception:
            # Nothing was applied (the migration ran in one transaction), so don't leave the file pending
            os.remove(file)
            raise click.ClickException(f"Applying {rel} failed and was rolled back; the file was removed.")
        finally:
            db.close()

        click.echo(f"  Commit {rel} along with your schema change so other databases get it.")
        if left_out:
            click.echo(f"  {left_out} change(s) need review and were left out — "
                       f"'scribe schema diff --database {name}' lists them")
        click.echo()


@cli.command()
@click.option('--yes', '-y', is_flag=True, help='Skip confirmation prompt')
def uninstall(yes):
    """
    Uninstall ScribeFramework from your system.

    This removes the scribe executable from your PATH.

    Example:
        scribe uninstall
        scribe uninstall -y
    """
    import shutil

    # Find where this executable is located
    executable_path = shutil.which('scribe')

    if not executable_path:
        click.echo("ScribeFramework is not installed (scribe command not found in PATH)")
        return

    click.echo(f"ScribeFramework is installed at: {executable_path}")

    if not yes:
        if not click.confirm("\nAre you sure you want to uninstall ScribeFramework?"):
            click.echo("Uninstall cancelled")
            return

    try:
        # Remove the executable
        os.remove(executable_path)
        click.echo(f"\n✓ Successfully uninstalled ScribeFramework")
        click.echo(f"  Removed: {executable_path}")
        click.echo("\nThank you for using ScribeFramework!")

    except PermissionError:
        click.echo(f"\n✗ Permission denied. The executable is in a system directory.")
        click.echo(f"  Try running with sudo:")
        click.echo(f"  sudo scribe uninstall")

    except Exception as e:
        click.echo(f"\n✗ Error during uninstall: {e}")
        click.echo(f"  You may need to manually remove: {executable_path}")


if __name__ == '__main__':
    # Required for multiprocessing on Windows and for proper process spawning
    import multiprocessing
    multiprocessing.freeze_support()
    cli()
