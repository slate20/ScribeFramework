# Deployment Guide

Deploy your ScribeEngine app to production.

## Production Checklist

Before deploying:

- [ ] Change `secret_key` in `scribe.json` to a random value
- [ ] Decide how migrations are applied (see [Migrations in Production](#migrations-in-production))
- [ ] Use environment variables for secrets
- [ ] Set up monitoring/logging
- [ ] Configure backups

## Using Production Server

ScribeEngine includes Waitress (production WSGI server):

```bash
scribe serve --host 0.0.0.0 --port 8000 --threads 8
```

**Options:**
- `--host`: IP address (0.0.0.0 = all interfaces)
- `--port`: Port number
- `--threads`: Worker threads
- `--migrate` / `--no-migrate`: Override each connection's `auto_migrate` for this run

## Migrations in Production

By default, `scribe serve` applies pending migrations at startup for connections with `"auto_migrate": true` (including `default` when the key is missing). For production, it is usually better to apply them as an explicit deploy step:

1. Set `"auto_migrate": false` on the connection in `scribe.json`.
2. In your deploy script, run migrations before restarting the server:

```bash
scribe db status    # optional: review what will run
scribe db migrate
sudo systemctl restart myapp
```

With `auto_migrate` off, `scribe serve` still starts normally and prints a warning if migrations are pending.

## PostgreSQL Configuration

Edit `scribe.json`:

```json
{
  "databases": {
    "default": {
      "type": "postgresql",
      "host": "localhost",
      "port": 5432,
      "user": "myapp_user",
      "password": "USE_ENV_VARIABLE",
      "database": "myapp_db",
      "migrations": "migrations",
      "auto_migrate": false
    }
  },
  "secret_key": "USE_ENV_VARIABLE"
}
```

**Don't commit secrets!** Use environment variables.

## Nginx Reverse Proxy

```nginx
server {
    listen 80;
    server_name myapp.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## Systemd Service

Create `/etc/systemd/system/myapp.service`:

```ini
[Unit]
Description=MyApp ScribeEngine
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/var/www/myapp
ExecStart=/usr/local/bin/scribe serve --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable:
```bash
sudo systemctl enable myapp
sudo systemctl start myapp
```

See other guides for development workflows.
