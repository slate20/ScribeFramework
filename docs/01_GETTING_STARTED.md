# Getting Started with ScribeEngine

This guide will walk you through creating your first custom route and understanding how ScribeEngine works.

## Your Project Structure

After running `scribe new myapp`, you have:

```
myapp/
├── app.stpl              # Your routes (this is where you'll spend most time)
├── base.stpl             # HTML layout template
├── scribe.json           # Configuration (database, secret key)
├── lib/                  # Helper functions (auto-loaded)
├── schemas/
│   └── schema_default.py # The tables your app owns (see Schema Files guide)
├── migrations/           # .sql files that build the database, run on startup
├── static/               # CSS, JavaScript, images
│   ├── css/
│   │   └── style.css     # Your styles
│   └── js/
└── app.db                # SQLite database (created automatically)
```

There's no example content to delete: `app.stpl` has a single page and the database starts with no tables. To explore a working app first, run `scribe new myapp --demo`. It adds a tasks list, login and registration pages, `lib/basic_auth.py`, and migrations and schema declarations for the `tasks` and `users` tables.

## Running Your App

```bash
cd myapp
scribe dev
```

Open http://localhost:5000 in your browser. You should see your project's home page.

## Understanding Routes

Routes are defined in `app.stpl` using the `@route()` decorator:

```python
@route('/hello')
{$
message = "Hello, World!"
$}

<h1>{{ message }}</h1>
```

**What's happening:**
1. `@route('/hello')` - Defines URL path
2. `{$ ... $}` - Python code block (executed server-side)
3. `message = "Hello, World!"` - Creates a variable
4. `{{ message }}` - Jinja2 template variable (renders in HTML)

## Your First Custom Route

Let's add a simple blog post route. Open `app.stpl` and add at the end:

```python
@route('/blog')
{$
page_title = "Blog"
posts = [
    {"title": "First Post", "date": "2025-01-01"},
    {"title": "Second Post", "date": "2025-01-15"},
]
$}

<div class="container">
    <h1>Blog Posts</h1>

    {% for post in posts %}
    <div class="card">
        <h2>{{ post.title }}</h2>
        <p class="text-muted">Posted on {{ post.date }}</p>
    </div>
    {% endfor %}
</div>
```

**Save the file** and the server will automatically reload. Visit http://localhost:5000/blog

## Working with Route Parameters

You can capture parts of the URL:

```python
@route('/blog/<int:post_id>')
{$
page_title = f"Post #{post_id}"
# post_id is automatically available as an integer
posts = {
    1: {"title": "First Post", "content": "Hello world!"},
    2: {"title": "Second Post", "content": "Another post"},
}
post = posts.get(post_id, None)

if not post:
    return abort(404)
$}

<div class="container">
    <div class="card">
        <h1>{{ post.title }}</h1>
        <p>{{ post.content }}</p>
    </div>
</div>
```

**Parameter types:**
- `<int:id>` - Integer
- `<string:name>` - String (default)
- `<path:filepath>` - Path (with slashes)

## Using the Database

Your app comes with a SQLite database (`app.db`) that starts with no tables. Describe one in `schemas/schema_default.py`:

```python
Table("posts",
    Column("id", "INTEGER", primary_key=True, autoincrement=True),
    Column("title", "TEXT", nullable=False),
    Column("created_at", "TIMESTAMP", default=sql("CURRENT_TIMESTAMP")),
)
```

Then create it:

```bash
scribe schema apply     # writes migrations/001_schema_posts.sql and runs it
```

(See the [Schema Files guide](06_SCHEMA_FILES.md) for more.) Now query it from a route:

```python
@route('/posts')
{$
page_title = "Posts"
# Query the database
posts = db['default'].query("SELECT * FROM posts ORDER BY created_at DESC")
$}

<div class="container">
    <h1>Posts</h1>

    {% if posts %}
        {% for post in posts %}
        <div class="card">
            <h3>{{ post.title }}</h3>
            <p>Posted: {{ post.created_at }}</p>
        </div>
        {% endfor %}
    {% else %}
        <p>No posts yet.</p>
    {% endif %}
</div>
```

**Important:** Always use parameterized queries to prevent SQL injection:

```python
# ✅ GOOD (parameterized)
users = db['default'].query(
    "SELECT * FROM users WHERE username = ?",
    (username,)
)

# ❌ BAD (vulnerable to SQL injection)
users = db['default'].query(
    f"SELECT * FROM users WHERE username = {username}"
)
```

## Forms and POST Requests

Handle form submissions:

```python
@route('/contact', methods=['GET', 'POST'])
{$
page_title = "Contact"
success = False

if request.method == 'POST':
    name = request.form.get('name')
    email = request.form.get('email')
    message = request.form.get('message')

    # Process the form (e.g., save to database)
    # ... your logic here ...

    success = True
$}

<div class="container-narrow">
    <div class="card">
        <h1>Contact Us</h1>

        {% if success %}
        <div class="alert alert-success">Message sent!</div>
        {% endif %}

        <form method="POST">
            {{ csrf() }}  <!-- CSRF protection -->

            <div class="form-group">
                <label>Name</label>
                <input type="text" name="name" required>
            </div>

            <div class="form-group">
                <label>Email</label>
                <input type="email" name="email" required>
            </div>

            <div class="form-group">
                <label>Message</label>
                <textarea name="message" rows="5" required></textarea>
            </div>

            <button type="submit" class="btn btn-primary">Send</button>
        </form>
    </div>
</div>
```

**Key points:**
- `methods=['GET', 'POST']` - Accept both methods
- `{{ csrf() }}` - Required for security (prevents CSRF attacks)
- `request.method` - Check which HTTP method was used
- `request.form.get('name')` - Access form data

## What's Next?

- **Customize the theme:** Edit `static/css/style.css` (change CSS variables)
- **Learn template syntax:** Read [Template Syntax](02_TEMPLATE_SYNTAX.md)
- **Work with databases:** Read [Database](03_DATABASE.md)
- **Understand authentication:** Read [Authentication](04_AUTHENTICATION.md)

Happy coding! 🚀
