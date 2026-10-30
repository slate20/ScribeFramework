"""
Files `scribe new` writes.

A new project is minimal by default: configuration, a layout, one page, and
empty migrations/ and schemas/ ready for the app's own tables. With --demo it
also gets the starter app (a tasks table, login and registration, and a page
explaining how the pieces fit together).
"""

import datetime
import os
from typing import Dict

DIRECTORIES = ('migrations', 'schemas', 'lib', 'static/css', 'static/js')


def project_files(project_name: str, demo: bool = False) -> Dict[str, str]:
    """Relative path -> content for every file in a new project."""
    base = (BASE_STPL
            .replace('{{nav_links}}', DEMO_NAV_LINKS if demo else MINIMAL_NAV_LINKS)
            .replace('{{year}}', str(datetime.date.today().year))
            .replace('{{project_name}}', project_name))
    files = {
        'scribe.json': SCRIBE_JSON,
        '.gitignore': GITIGNORE,
        'base.stpl': base,
        'README.md': README.format(
            project_name=project_name,
            structure=DEMO_README_STRUCTURE if demo else MINIMAL_README_STRUCTURE,
        ),
    }
    if demo:
        files.update({
            'app.stpl': DEMO_APP_STPL,
            'static/css/style.css': THEME_CSS,
            'migrations/001_initial.sql': DEMO_INITIAL_SQL,
            'migrations/002_users.sql': DEMO_USERS_SQL,
            'schemas/schema_default.py': SCHEMA_HEADER + '\n\n' + DEMO_SCHEMA_TABLES,
            'lib/basic_auth.py': DEMO_BASIC_AUTH_PY,
        })
    else:
        files.update({
            'app.stpl': MINIMAL_APP_STPL.replace('{{project_name}}', project_name),
            'static/css/style.css': MINIMAL_CSS,
            'schemas/schema_default.py': SCHEMA_HEADER + MINIMAL_SCHEMA_EXAMPLE,
        })
    return files


def create_project(project_path: str, project_name: str, demo: bool = False):
    """Write a new project into project_path, which must not exist yet."""
    os.makedirs(project_path)
    for directory in DIRECTORIES:
        os.makedirs(os.path.join(project_path, *directory.split('/')), exist_ok=True)
    for relative, content in project_files(project_name, demo).items():
        with open(os.path.join(project_path, *relative.split('/')), 'w', encoding='utf-8') as f:
            f.write(content)


# === Shared ===

SCRIBE_JSON = r'''{
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

GITIGNORE = r'''# Database
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

# {{nav_links}}, {{year}}, and {{project_name}} are filled in by project_files()
BASE_STPL = r'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ page_title | default('{{project_name}}') }} — Scribe</title>
    <meta name="description" content="{{ page_description | default('Built with ScribeFramework') }}">
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
{{nav_links}}                </nav>
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
            <p>&copy; {{year}} {{project_name}}</p>
        </div>
    </footer>

    <script>
        document.addEventListener('DOMContentLoaded', function() {
            // Toast auto-dismiss
            const toasts = document.querySelectorAll('.toast-message');
            toasts.forEach(toast => {
                setTimeout(() => {
                    toast.style.opacity = '0';
                    toast.style.transition = 'opacity 0.3s ease';
                    setTimeout(() => toast.remove(), 300);
                }, 4000);
            });
        });
    </script>

    {% block extra_scripts %}{% endblock %}
</body>
</html>
'''

MINIMAL_NAV_LINKS = r'''                    <a href="/">Home</a>
'''

DEMO_NAV_LINKS = r'''                    <a href="/">Home</a>
                    <a href="https://scribeframework.slatecapit.com/docs" target="_blank">Docs</a>
                    {% if session.get('user_id') %}
                        <a href="/logout">Logout</a>
                    {% else %}
                        <a href="/login">Login</a>
                    {% endif %}
'''

README = r'''# {project_name}

A ScribeFramework web application.

## Quick Start

1. Start the development server with auto-reload enabled:
   ```bash
   scribe dev
   ```

2. Open [http://localhost:5000](http://localhost:5000) in your browser.

## Project Structure

{structure}'''

MINIMAL_README_STRUCTURE = r'''* **`app.stpl`** — Your routes. Route definitions and Jinja2 templates live here.
* **`base.stpl`** — Base HTML layout that wraps every page.
* **`scribe.json`** — Configuration (database connections, secret keys).
* **`schemas/schema_default.py`** — The database tables the app owns. Edit it, then run `scribe schema apply` (or `scribe schema generate` to review the SQL first).
* **`migrations/`** — Numbered `.sql` files that build the database, applied automatically on startup. `scribe schema` writes new ones; commit them with your schema change.
* **`lib/`** — Python helpers, available in every route.
* **`static/`** — Static assets, including `css/style.css`.
'''

DEMO_README_STRUCTURE = r'''* **`app.stpl`** — Your main application code. Route definitions and Jinja2 templates live here.
* **`base.stpl`** — Base HTML template layout.
* **`scribe.json`** — Configuration (database connections, secret keys).
* **`schemas/schema_default.py`** — The database tables the app owns. Edit it, then run `scribe schema apply` (or `scribe schema generate` to review the SQL first).
* **`migrations/`** — Numbered `.sql` files that build the database, applied automatically on startup. `scribe schema` writes new ones; commit them with your schema change.
* **`static/`** — Static assets, including custom CSS.
'''

SCHEMA_HEADER = r'''"""
Schema for the 'default' database connection (sqlite).

The tables this app owns. To change the database, edit this file, then run:

    scribe schema diff        # see what would change
    scribe schema apply       # write a migration with the additive changes and run it
    scribe schema generate    # or write one to review first (needed for drops and type changes)

Both write a numbered .sql file to migrations/. Commit it along with this file:
other databases (a teammate's, production, a fresh app.db) are built from migrations.
The Schema tab in `scribe ide` shows the same comparison.

Column types are SQLite's own types.
"""

from scribe.schema import Table, Column, Index, ForeignKey, sql, raw_sql, unmanaged, scope
'''

THEME_CSS = r'''/* ================================================================
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


# === Minimal project ===

MINIMAL_APP_STPL = r'''@route('/')
{$
page_title = "Home"
$}

<h1>{{project_name}}</h1>
<p class="text-muted">Edit <code>app.stpl</code> to build this page.</p>
'''

MINIMAL_SCHEMA_EXAMPLE = r'''
# Describe your tables here, for example:
#
# Table("posts",
#     Column("id", "INTEGER", primary_key=True, autoincrement=True),
#     Column("title", "TEXT", nullable=False),
#     Column("created_at", "TIMESTAMP", default=sql("CURRENT_TIMESTAMP")),
# )
#
# then run `scribe schema apply` to create them.
'''

# The theme without the demo's panel, list, and auth form styles
MINIMAL_CSS = r'''/* ================================================================
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
'''


# === Demo project (--demo) ===

DEMO_APP_STPL = r'''@route('/')
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
        <p class="lead">Write Python where you need it. This starter page is rendering directly from <code>app.stpl</code> and is connected to <code>app.db</code>, whose tables are described in <code>schemas/schema_default.py</code>.</p>
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
                <li><strong><code>schemas/schema_default.py</code></strong> — The tables your app owns. Edit it, then run <code>scribe schema apply</code> to update the database.</li>
                <li><strong><code>migrations/</code></strong> — Numbered <code>.sql</code> files that build the database. <code>scribe schema</code> writes new ones for you; they run automatically on start.</li>
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

DEMO_INITIAL_SQL = r'''-- Initial migration: Create tasks table
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
    ('Add a table in "schemas/schema_default.py", then run "scribe schema apply"');
'''

DEMO_USERS_SQL = r'''CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
'''

DEMO_SCHEMA_TABLES = r'''Table("tasks",
    Column("id", "INTEGER", primary_key=True, autoincrement=True),
    Column("title", "TEXT", nullable=False),
    Column("completed", "BOOLEAN", default=0),
    Column("created_at", "TIMESTAMP", default=sql("CURRENT_TIMESTAMP")),
)


Table("users",
    Column("id", "INTEGER", primary_key=True, autoincrement=True),
    Column("username", "TEXT", nullable=False, unique=True),
    Column("password_hash", "TEXT", nullable=False),
    Column("created_at", "TIMESTAMP", default=sql("CURRENT_TIMESTAMP")),
)
'''

DEMO_BASIC_AUTH_PY = r'''"""Authentication helpers - auto-loaded into all templates"""
from werkzeug.security import check_password_hash, generate_password_hash


def verify_password(password_hash, password):
    if password is None or password_hash is None:
        return False
    return check_password_hash(password_hash, password)


def hash_password(password):
    return generate_password_hash(password)
'''
