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
│   └── auth_helpers.py   # Password hashing functions
├── migrations/           # Database schema changes
│   └── 001_users.sql     # Initial user table
├── static/               # CSS, JavaScript, images
│   ├── css/
│   │   └── style.css     # Your styles
│   └── js/
├── docs/                 # Documentation (you are here!)
└── app.db                # SQLite database (created automatically)
```

## Running Your App

```bash
cd myapp
scribe dev
```

Open http://localhost:5000 in your browser. You should see the welcome page!

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

Your app comes with a SQLite database. Let's query it:

```python
@route('/users')
{$
page_title = "Users"
# Query the database
users = db['default'].query("SELECT * FROM users")
$}

<div class="container">
    <h1>Users</h1>

    {% if users %}
        {% for user in users %}
        <div class="card">
            <h3>{{ user.username }}</h3>
            <p>Joined: {{ user.created_at }}</p>
        </div>
        {% endfor %}
    {% else %}
        <p>No users found.</p>
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
