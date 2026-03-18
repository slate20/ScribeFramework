# ScribeEngine Documentation

Welcome to your eval documentation! These guides will help you get the most out of ScribeEngine.

## 📚 Guides

1. **[Getting Started](01_GETTING_STARTED.md)** - Create your first routes and understand the basics
2. **[Template Syntax](02_TEMPLATE_SYNTAX.md)** - Complete reference for .stpl files
3. **[Database](03_DATABASE.md)** - Working with databases, queries, and migrations
4. **[Authentication](04_AUTHENTICATION.md)** - Understanding and customizing the auth system
5. **[Deployment](05_DEPLOYMENT.md)** - Deploying your app to production

## 🚀 Recommended Reading Order

**New to ScribeEngine?**
1. Start with Getting Started
2. Read Template Syntax
3. Explore Database guide
4. Dive into Authentication (if using auth)

**Ready for production?**
- Jump to Deployment guide

## 🔗 More Resources

- **Full Documentation:** See the `new-architecture/` directory for complete technical specs
- **Examples:** Check out the `/login`, `/dashboard` routes in your `app.stpl`
- **Community:** [GitHub Issues](https://github.com/yourusername/scribe-engine/issues)

## 💡 Quick Reference

**Define a route:**
```python
@route('/hello')
{$
message = "Hello!"
$}
<h1>{{ message }}</h1>
```

**Query database:**
```python
{$
users = db['default'].query("SELECT * FROM users")
$}
```

**Protect a route:**
```python
@route('/admin')
@require_auth
{$
... $}
```

Happy coding! 🎉
