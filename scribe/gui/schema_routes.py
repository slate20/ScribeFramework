"""
GUI IDE Routes - Schema panel

Read schemas/schema_{name}.py files, compare them with the live database,
and run the same steps as `scribe schema pull/generate/apply`.

scribe.json is re-read on every request, so edits to it apply without
restarting the IDE. Each request opens its own database connection.

Note: Routes are registered programmatically in scribe/gui/__init__.py.
"""

import os

from flask import jsonify, request

from scribe.gui.routes import get_project_root


class _RequestError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _relative(message):
    """Show project files as schemas/... rather than absolute paths."""
    return str(message).replace(str(get_project_root()) + os.sep, '')


def _json_errors(view):
    """Turn _RequestError (and unexpected errors) into {'error': ...} responses."""
    from functools import wraps
    from scribe.schema import SchemaError

    @wraps(view)
    def wrapper(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except _RequestError as e:
            return jsonify({'error': _relative(e)}), e.status
        except SchemaError as e:
            return jsonify({'error': _relative(e)}), 400
        except Exception as e:
            return jsonify({'error': _relative(f"{type(e).__name__}: {e}")}), 500
    return wrapper


def _connect(name, block):
    from scribe.database import create_adapter

    try:
        return create_adapter(block)
    except Exception as e:
        detail = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
        raise _RequestError(f"Could not connect to '{name}' ({block.get('type', 'sqlite')}): {detail}", 502)


def _project():
    """(project path, connection blocks, migration targets by name)"""
    from scribe.app import load_config
    from scribe.migrations import get_databases_config, get_migration_targets, MigrationConfigError

    path = str(get_project_root())
    databases = get_databases_config(load_config(path))
    try:
        targets = {t.name: t for t in get_migration_targets(databases, path)}
    except MigrationConfigError as e:
        raise _RequestError(str(e))
    return path, databases, targets


def _connection(connection_name):
    """(project path, block, target, schema file path) for one connection."""
    from scribe.schema.loader import schema_file_path

    path, databases, targets = _project()
    if connection_name not in databases:
        raise _RequestError(f"Connection '{connection_name}' not found in scribe.json", 404)
    return path, databases[connection_name], targets.get(connection_name), schema_file_path(path, connection_name)


def _rel(path, file):
    return os.path.relpath(file, path).replace(os.sep, '/')


def _connection_summary(path, name, block, target, file):
    from scribe.schema.actions import apply_refusal, generate_refusal

    return {
        'name': name,
        'dialect': block.get('type', 'sqlite').lower(),
        'file': _rel(path, file),
        'exists': os.path.exists(file),
        'migrations': _rel(path, target.path) if target else None,
        'auto_migrate': bool(target and target.auto_migrate),
        'generate_refusal': generate_refusal(target, name),
        'apply_refusal': apply_refusal(target, name),
    }


@_json_errors
def list_schema_connections():
    """Each connection and whether it has a schema file (no database access)."""
    from scribe.schema.loader import schema_file_path, schemas_dir

    path, databases, targets = _project()
    return jsonify({
        'schemas_dir': os.path.isdir(schemas_dir(path)),
        'connections': [
            _connection_summary(path, name, block, targets.get(name), schema_file_path(path, name))
            for name, block in databases.items()
        ],
    })


def _symbol(change):
    if change.additive:
        return '+'
    return '-' if change.destructive else '!'


def _default_text(value):
    from scribe.schema.dsl import SqlExpression

    if value is None:
        return None
    return f"sql({value.text!r})" if isinstance(value, SqlExpression) else repr(value)


def _column_json(column):
    return {
        'name': column.name,
        'type': column.type,
        'primary_key': column.primary_key,
        'autoincrement': column.autoincrement,
        'nullable': column.nullable,
        'unique': column.unique,
        'default': _default_text(column.default),
        'foreign_key': column.foreign_key.target if column.foreign_key else None,
    }


def _change_json(change):
    return {
        'symbol': _symbol(change),
        'kind': change.kind,
        'column': change.column,
        'description': change.description,
        'additive': change.additive,
        'destructive': change.destructive,
    }


def _table_status(table, changes):
    if not table.managed:
        return 'unmanaged'
    if any(c.kind == 'create_table' for c in changes):
        return 'missing'
    return 'changed' if changes else 'in_sync'


@_json_errors
def get_schema(connection_name):
    """The schema file's tables, each compared with the live database."""
    from scribe.schema import SchemaError
    from scribe.schema.actions import check_connection, pending_migrations
    from scribe.schema.writer import table_lines

    path, block, target, file = _connection(connection_name)
    result = _connection_summary(path, connection_name, block, target, file)
    if not result['exists']:
        return jsonify(result)

    try:
        check = check_connection(_connect, connection_name, block, file, target, untracked=True)
    except SchemaError as e:
        # The file is mid-edit or broken; show where, so it can be opened and fixed
        result['error'] = _relative(e)
        return jsonify(result)
    except NotImplementedError as e:
        raise _RequestError(f"'{connection_name}': {e}")

    definition, diff = check.definition, check.diff
    lines = table_lines(file)
    tables = []
    for key, table in definition.tables.items():
        changes = [c for c in diff.changes if c.table.lower() == key]
        tables.append({
            'name': table.name,
            'managed': table.managed,
            'line': lines.get(key),
            'status': _table_status(table, changes),
            'columns': [_column_json(c) for c in table.columns],
            'indexes': [
                {'name': i.name, 'columns': i.columns, 'unique': i.unique}
                for i in definition.indexes_for(table.name)
            ],
            'changes': [_change_json(c) for c in changes],
            'in_database': key in check.live,
        })

    review = diff.needs_review + [r for r in check.raw if r.status != 'new']
    result.update({
        'tables': tables,
        'unmanaged': list(definition.unmanaged.values()),
        'untracked': diff.untracked,
        'raw_sql': [{'name': r.name, 'status': r.status} for r in check.raw],
        'raw_sql_blocks': len(definition.raw_sql),
        'scope': repr(definition.scope) if definition.scope is not None else None,
        'tables_in_scope': len(check.live),
        'total_tables': check.total_tables,
        'counts': {
            'additive': len(diff.additive) + len([r for r in check.raw if r.status == 'new']),
            'review': len(review),
            'destructive': len([c for c in diff.needs_review if c.destructive]),
        },
        'pending': pending_migrations(_connect, connection_name, block, target) if target else [],
    })
    return jsonify(result)


def _body():
    return request.get_json(silent=True) or {}


@_json_errors
def init_schema(connection_name):
    """Create an empty schema file (`scribe schema init` for one connection)."""
    from scribe.schema.writer import write_init_file

    path, block, target, file = _connection(connection_name)
    if not write_init_file(file, connection_name, block.get('type', 'sqlite').lower()):
        raise _RequestError(f"{_rel(path, file)} already exists", 409)
    return jsonify({'file': _rel(path, file), 'message': f"Created {_rel(path, file)}"})


@_json_errors
def pull_schema(connection_name):
    """Add database tables the file doesn't declare yet, as managed=False (`scribe schema pull`)."""
    from scribe.schema.actions import read_live
    from scribe.schema.loader import load_schema
    from scribe.schema.writer import pull_into_file

    path, block, target, file = _connection(connection_name)
    table_filter = load_schema(file).in_scope if os.path.exists(file) else None
    live, total = read_live(_connect, connection_name, block, table_filter)
    added, skipped = pull_into_file(file, connection_name, block.get('type', 'sqlite').lower(), list(live.values()))

    rel = _rel(path, file)
    if added:
        message = f"Added {len(added)} table(s) to {rel} as managed=False"
    else:
        message = f"No new tables ({len(skipped)} already in {rel})"
    if len(live) < total:
        message += f" — {len(live)} of {total} tables in scope"
    return jsonify({'file': rel, 'added': added, 'message': message})


@_json_errors
def set_managed(connection_name):
    """Set managed=True/False on one table's declaration."""
    from scribe.schema.writer import set_table_managed

    path, block, target, file = _connection(connection_name)
    body = _body()
    table, managed = body.get('table'), body.get('managed')
    if not isinstance(table, str) or not isinstance(managed, bool):
        raise _RequestError("Expected {\"table\": name, \"managed\": true|false}")
    if not os.path.exists(file):
        raise _RequestError(f"No schema file for '{connection_name}'", 404)

    changed = set_table_managed(file, table, managed)
    return jsonify({'file': _rel(path, file), 'changed': changed,
                    'message': f"{table}: managed={managed} in {_rel(path, file)}"})


def _check_for_migration(connection_name, path, block, target, file):
    from scribe.schema.actions import check_connection

    if not os.path.exists(file):
        raise _RequestError(f"No schema file for '{connection_name}'", 404)
    return check_connection(_connect, connection_name, block, file, target)


@_json_errors
def generate_schema_migration(connection_name):
    """Preview or write a migration for every change (`scribe schema generate`)."""
    from scribe.schema.actions import generate_refusal, pending_migrations, render_migration, write_migration

    path, block, target, file = _connection(connection_name)
    body = _body()
    refusal = generate_refusal(target, connection_name)
    if refusal:
        raise _RequestError(refusal, 409)

    check = _check_for_migration(connection_name, path, block, target, file)
    if not check.change_count:
        return jsonify({'message': f"Nothing to generate — the database matches {_rel(path, file)}"})

    # The diff is against the live database, so unapplied migrations would be generated again
    pending = pending_migrations(_connect, connection_name, block, target)
    if pending:
        raise _RequestError(
            f"'{connection_name}' has {len(pending)} pending migration(s) ({', '.join(pending)}). "
            f"Run them first (scribe db migrate --database {connection_name}) so the diff includes them.", 409)

    migration = render_migration(check, path)
    result = {'sql': migration.sql, 'live': migration.live, 'review': migration.review}
    if body.get('dry_run'):
        return jsonify(result)
    if migration.live == 0 and not body.get('force'):
        raise _RequestError(
            f"All {migration.review} change(s) need review, so the migration would run nothing. "
            f"Write it anyway to edit the commented-out SQL by hand.", 409)

    rel = _rel(path, write_migration(target, migration, body.get('name') or None))
    result['file'] = rel
    if target.auto_migrate:
        result['message'] = (f"Wrote {rel}. auto_migrate is on, so it runs on the next "
                             f"'scribe dev', 'scribe ide', or 'scribe serve' start — review it before then.")
    else:
        result['message'] = (f"Wrote {rel}. Review it, then run 'scribe db migrate"
                             f"{'' if connection_name == 'default' else ' --database ' + connection_name}'.")
    return jsonify(result)


@_json_errors
def run_pending_migrations(connection_name):
    """Apply the connection's pending migrations (`scribe db migrate --database name`)."""
    from scribe.schema.actions import generate_refusal, pending_migrations, run_pending

    path, block, target, file = _connection(connection_name)
    if target is None:
        raise _RequestError(generate_refusal(target, connection_name), 409)
    pending = pending_migrations(_connect, connection_name, block, target)
    if not pending:
        return jsonify({'ran': [], 'message': 'No pending migrations'})
    try:
        run_pending(_connect, connection_name, block, path, target)
    except Exception as e:
        raise _RequestError(f"Migration failed: {e}", 500)
    return jsonify({'ran': pending, 'message': f"Applied {len(pending)} migration(s): {', '.join(pending)}"})


@_json_errors
def apply_schema(connection_name):
    """Preview or write-and-run a migration of the additive changes (`scribe schema apply`)."""
    from scribe.schema.actions import (
        additive_part, apply_refusal, pending_migrations, render_migration, run_pending, run_written_migration,
        write_migration,
    )

    path, block, target, file = _connection(connection_name)
    body = _body()
    dry_run = bool(body.get('dry_run'))
    refusal = apply_refusal(target, connection_name)
    if refusal:
        raise _RequestError(refusal, 409)
    if not os.path.exists(file):
        raise _RequestError(f"No schema file for '{connection_name}'", 404)

    # This connection would run pending migrations on its next start anyway; do it now
    # so the diff reflects them (a preview only reports them).
    pending = pending_migrations(_connect, connection_name, block, target)
    if pending and not dry_run:
        try:
            run_pending(_connect, connection_name, block, path, target)
        except Exception as e:
            raise _RequestError(f"A pending migration for '{connection_name}' failed: {e}", 500)

    check = _check_for_migration(connection_name, path, block, target, file)
    additive, raw, left_out = additive_part(check)
    result = {'pending': pending, 'left_out': left_out}
    if not additive.changes and not raw:
        result['message'] = "Nothing to apply" + (
            f" — {left_out} change(s) need review; Generate writes them commented out" if left_out else "")
        return jsonify(result)

    migration = render_migration(check, path, additive, raw)
    result.update({'sql': migration.sql, 'live': migration.live})
    if dry_run:
        return jsonify(result)

    written = write_migration(target, migration, body.get('name') or None)
    rel = _rel(path, written)
    error = run_written_migration(_connect, connection_name, block, path, target, written)
    if error:
        raise _RequestError(f"Applying {rel} failed and was rolled back; the file was removed. {error}", 500)

    result['file'] = rel
    message = f"Applied {rel} ({migration.live} statement(s)). Commit it with your schema change."
    if pending:
        message = f"Ran {len(pending)} pending migration(s) first. " + message
    if left_out:
        message += f" {left_out} change(s) need review and were left out."
    result['message'] = message
    return jsonify(result)
