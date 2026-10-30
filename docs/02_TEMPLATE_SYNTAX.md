# Template Syntax Reference

Complete guide to ScribeEngine `.stpl` file syntax.

## Route Declaration

### Basic Routes

```python
@route('/')              # GET request (default)
@route('/about')         # Static path
@route('/api/data')      # Nested path
```

### HTTP Methods

```python
@route('/login', methods=['GET', 'POST'])
@route('/api/users', methods=['GET', 'POST', 'PUT', 'DELETE'])
```

### Route Parameters

```python
@route('/posts/<int:post_id>')                # Integer
@route('/users/<username>')                   # String (default)
@route('/files/<path:filepath>')              # Path (includes slashes)
@route('/product/<uuid:product_id>')          # UUID
```

## Python Blocks

Execute Python code with `{$ ... $}`:

```python
{$
# Variables
title = "Hello"
items = [1, 2, 3]

# Loops
for item in items:
    process(item)

# Conditionals
if user_id:
    user = db['default'].find('users', user_id)

# Functions
def format_date(date):
    return date.strftime('%Y-%m-%d')
$}
```

### Available Objects

- `request` - Flask request object (form data, headers, method)
- `session` - Flask session (dict-like)
- `db` - Database connections
- `flash()` - Flash messages
- `redirect()` - Redirect to URL
- `abort()` - Return HTTP error
- `jsonify()` - Return JSON response

## Jinja2 Templates

### Variables

```html
<h1>{{ page_title }}</h1>
<p>{{ user.name }}</p>
<p>{{ items[0] }}</p>
```

### Filters

```html
{{ name | upper }}                    # UPPERCASE
{{ long_text | truncate(100) }}       # Limit length
{{ date | default('No date') }}       # Default value
```

### Conditionals

```html
{% if user %}
    <p>Welcome, {{ user.name }}!</p>
{% else %}
    <p>Please log in.</p>
{% endif %}
```

### Loops

```html
{% for post in posts %}
    <h2>{{ post.title }}</h2>
{% endfor %}

{% for key, value in dict.items() %}
    <p>{{ key }}: {{ value }}</p>
{% endfor %}
```

## Decorators

### @require_auth

Require login:

```python
@route('/dashboard')
@require_auth
{$ ... $}
```

Redirects to `/login` if not authenticated.

### @no_layout

Disable the automatic `base.stpl` wrapper. Useful for HTMX fragments or AJAX responses.

```python
@route('/api/fragment')
@no_layout
{$ ... $}
<div>I am a bare HTML snippet</div>
```

### @sse

Enable Server-Sent Events (SSE). This decorator:
1. Sets the response mimetype to `text/event-stream`.
2. Automatically applies `@no_layout`.
3. Supports `yield` for streaming updates.

```python
@route('/counter')
@sse
{$
import time
for i in range(5):
    count = i
    yield frame() # Renders the template below
    time.sleep(1)
$}
<div class="update">Current count: {{ count }}</div>
```

### @csrf_exempt

Exempt this route from Flask-WTF's CSRF protection, which is otherwise applied to every
`POST`/`PUT`/`PATCH`/`DELETE` route and requires a token bound to the browser session
cookie. Use this on API endpoints meant to be called with a bearer token or from another
service, since those clients never carry that cookie and would otherwise always get a 400.

```python
@route('/api/webhook', methods=['POST'])
@csrf_exempt
{$ ... $}
```

Do **not** add this to routes rendered by, or submitted from, an HTML form in your app —
those still need CSRF protection. Prefer scoping it to a dedicated API path (e.g. under
`/api/`) rather than reusing a route that's also form-facing.

## Built-in Helpers

### frame(template=None, event=None, **kwargs)

Used within `@sse` routes to render fragments for the stream.

- **template**: Optional override for the template to render. Defaults to the route's own template.
- **event**: Optional SSE event name (e.g., `event: update`).
- **kwargs**: Extra variables to pass to the template.

```python
yield frame(event='notification', msg='New Alert!')
```

## Return Statements

### Redirect

```python
{$
if not user:
    return redirect('/login')
$}
```

### JSON Response

```python
{$
data = {"status": "success", "count": 42}
return jsonify(data)
$}
```

### Abort (HTTP Error)

```python
{$
if not authorized:
    return abort(403)  # Forbidden
$}
```

## Layout Inheritance

Use `base.stpl` automatically:

```python
@route('/page')
{$
page_title = "My Page"  # Sets <title>
$}

<!-- Content automatically wrapped in base.stpl -->
<h1>Hello!</h1>
```

See [Getting Started](01_GETTING_STARTED.md) for examples.
