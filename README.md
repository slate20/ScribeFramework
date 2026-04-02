# ScribeFramework

### **Write Python where you need it.**

Scribe is a low-ceremony web framework designed for developers who need to ship functional, data-driven tools without the overhead of traditional MVC patterns. By using `.stpl` files, Scribe co-locates routing, business logic, and HTML into a single, cohesive unit.

No separate controller files, no rigid API layers—just Python and HTML working together.

---

## The `.stpl` Approach

Scribe eliminates the friction of jumping between files. Logic lives exactly where it’s rendered. Because Scribe automatically parses the `lib/` directory, any functions you write there are immediately available in your templates without manual imports.

```html
@route('/reports/margin')
@require_auth
{$
# Straight Python logic with built-in DB helpers.
# Functions in lib/ are auto-loaded and ready to use.
data = db.table('sales').where(status='pending').all()
risk_score = calculate_risk_profile(data) 
$}

<h1>Operational Risk Report</h1>
<p>Current Score: {{ risk_score }}</p>

<ul>
    {% for item in data %}
        <li>{{ item.name }}: {{ item.margin }}%</li>
    {% endfor %}
</ul>
```

---

## Why Scribe?

* **Zero-Ceremony Organization:** Scribe recursively finds and parses `.stpl` files wherever you put them. The framework adapts to your mental model, whether you prefer a flat structure or a nested one.
* **Auto-Injected Logic:** Any `.py` file in your `lib/` directory is automatically parsed, making its functions immediately accessible in your templates.
* **Your Workflow, Your Choice:** Scribe is entirely editor-agnostic. Use the optional, browser-based integrated IDE (`scribe ide`) featuring a Monaco-powered editor and database browser, or stick to your preferred local setup (like Neovim or VS Code) and control everything via the CLI.
* **Modern Interactivity:** Built-in support for **HTMX 2.x** (via `@no_layout` for fragments) and **SSE** (via the `@sse` decorator and `frame()` helper) lets you build reactive, real-time UIs in pure Python.
* **Database First:** SQLite is configured by default, but Scribe supports PostgreSQL, MySQL, and other major backends via SQLAlchemy. Migrations are managed by simply dropping `.sql` files into a `migrations/` folder.
* **Escape Hatches:** Because Scribe is built on Flask, you have full access to the underlying Flask API whenever you need to break out of the standard Scribe workflow.

---

## Installation & Quick Start

Scribe is distributed as a standalone binary for Linux environments.

1.  **Download and Install:**
    Extract the release tarball and run the installation script:
    ```bash
    tar -xvf scribe-linux.tar.gz
    sudo ./install.sh
    ```
2.  **Create a Project:**
    ```bash
    scribe new my-app
    cd my-app
    ```
3.  **Launch in Development:**
    ```bash
    scribe dev
    ```
    Your app is live at `http://localhost:5000` with hot-reloading enabled.

---

## Use Cases

Scribe is flexible enough to handle everything from one-off scripts to complex operational engines:

* **IT & SysAdmin Automation:** Build "single pane of glass" workspaces for server health, log aggregation, or remote script execution.
* **Operational Control Centers:** Use Server-Sent Events (SSE) to create live-updating monitors for facilities, sales floors, or IoT feeds.
* **Dynamic Inventory & Logistics:** Create tools that calculate real-time stock impacts or manufacturing timelines using complex Python libraries.
* **Interactive Data Science:** Move beyond static notebooks. Build internal tools that let stakeholders run simulations or view complex data models.

---

## Deployment

Scribe is built for a **"Copy and Run"** deployment model. You aren't tied to a specific cloud provider or complex orchestration. To run in production, Scribe uses the **Waitress** server to provide a stable, production-grade WSGI environment out of the box.

```bash
scribe serve --port 8000
```

Whether you are deploying via `scp` to a VPS, running it as a `systemd` service, or wrapping it in a lightweight container, the process remains identical.

---

## Security by Default

Scribe doesn't sacrifice safety for speed. Every project comes with:
* **Automatic CSRF Protection:** Enabled for standard forms and HTMX requests out of the box.
* **SQL Injection Prevention:** All database helpers use parameterized queries.
* **Secure Sessions:** Built-in session management and password hashing helpers.
* **XSS Defense:** All template output is auto-escaped by default, keeping your application secure from the jump.

---

**Scribe is currently in Alpha (v2.1.0).**
