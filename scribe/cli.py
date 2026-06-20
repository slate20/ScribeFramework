"""
Command-line interface for ScribeFramework.

Provides commands:
    scribe new <project>    - Create new project
    scribe dev              - Run development server
    scribe db migrate       - Run database migrations
"""

import click
import os
import shutil
from pathlib import Path


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
      "database": "app.db"
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

    users = db['default'].query(
        "SELECT * FROM users WHERE username = ?",
        (username,)
    )

    if users and verify_password(users[0]['password_hash'], password):
        session['user_id'] = users[0]['id']
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
session.pop('user_id', None)
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
@click.option('--path', default='.', help='Project directory')
def dev(host, port, debug, no_reload, path):
    """
    Run development server for your ScribeFramework application.

    Example:
        scribe dev                    # Run on localhost:5000
        scribe dev --port 3000        # Custom port
        scribe dev --no-reload        # Disable auto-reload
        scribe dev --host 0.0.0.0     # Allow external connections

    To use the IDE, run 'scribe ide' in a separate terminal.
    """
    from scribe.app import create_app
    from scribe.migrations import run_migrations
    import glob

    click.echo(f"Starting ScribeFramework development server...")
    click.echo(f"Project: {os.path.abspath(path)}")

    # Create app
    app = create_app(path)

    # Run migrations
    click.echo("\nApplying database migrations...")
    db = app.config['DB']
    run_migrations(db, path)

    # Configure auto-reload to watch project files
    extra_files = []
    use_reloader = not no_reload

    if use_reloader:
        # Watch .stpl template files
        extra_files.extend(glob.glob(os.path.join(path, '**/*.stpl'), recursive=True))
        # Watch lib/ Python files
        extra_files.extend(glob.glob(os.path.join(path, 'lib/**/*.py'), recursive=True))
        # Watch migrations
        extra_files.extend(glob.glob(os.path.join(path, 'migrations/**/*.sql'), recursive=True))
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
@click.option('--path', default='.', help='Project directory')
def ide(host, port, app_port, debug, no_reload, path):
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
    from scribe.migrations import run_migrations
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

    # Run migrations (so database browser works)
    click.echo("\nApplying database migrations...")
    db = gui_app.config['DB']
    run_migrations(db, path)

    # Configure auto-reload to watch project files
    extra_files = []
    use_reloader = not no_reload

    if use_reloader:
        # Watch .stpl template files
        extra_files.extend(glob.glob(os.path.join(path, '**/*.stpl'), recursive=True))
        # Watch lib/ Python files
        extra_files.extend(glob.glob(os.path.join(path, 'lib/**/*.py'), recursive=True))
        # Watch migrations
        extra_files.extend(glob.glob(os.path.join(path, 'migrations/**/*.sql'), recursive=True))
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
@click.option('--path', default='.', help='Project directory')
def serve(host, port, threads, path):
    """
    Run production server using Waitress.

    Uses the Waitress WSGI server - production-ready, multi-threaded,
    and fully self-contained. No external dependencies required.

    Example:
        scribe serve
        scribe serve --host 0.0.0.0 --port 8000
        scribe serve --threads 8
    """
    from scribe.app import create_app
    from scribe.migrations import run_migrations
    from waitress import serve as waitress_serve

    click.echo(f"Starting ScribeFramework production server...")
    click.echo(f"Project: {os.path.abspath(path)}")

    # Create Flask app (production mode)
    app = create_app(path)

    # Run migrations
    click.echo("\nApplying database migrations...")
    db = app.config['DB']
    run_migrations(db, path)

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
@click.option('--path', default='.', help='Project directory')
def migrate(path):
    """
    Run database migrations.

    Example:
        scribe db migrate
    """
    from scribe.app import load_config
    from scribe.database import create_adapter
    from scribe.migrations import run_migrations

    click.echo("Running database migrations...")

    # Load config
    config = load_config(path)

    # Create database adapter
    db = create_adapter(config.get('database', {'type': 'sqlite', 'database': 'app.db'}))

    # Run migrations
    run_migrations(db, path)

    db.close()


@db_commands.command()
@click.argument('name')
@click.option('--path', default='.', help='Project directory')
def new_migration(name, path):
    """
    Create a new migration file.

    Example:
        scribe db new-migration create_users
    """
    from scribe.migrations import create_migration

    filepath = create_migration(path, name)
    click.echo(f"\n✓ Created migration: {filepath}")
    click.echo(f"\nEdit the file to add your SQL statements, then run:")
    click.echo(f"  scribe db migrate")


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
