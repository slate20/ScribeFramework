"""
GUI IDE Routes

Handles all routes for the ScribeEngine IDE interface.

Note: Routes are registered programmatically in scribe/gui/__init__.py
via the _register_routes() function. Do not use decorators here.
"""

import os
import json
from flask import render_template, request, jsonify, send_from_directory, abort, g, current_app
from pathlib import Path


def get_project_root():
    """Get project root path from app config or fallback to current directory"""
    return Path(current_app.config.get('PROJECT_PATH', os.getcwd()))


def index():
    """Main IDE interface"""
    from flask import current_app, url_for, request

    # Get the actual registered blueprint (not the module-level one)
    # to get the correct URL prefix
    registered_bp = current_app.blueprints[request.blueprint]
    api_base = registered_bp.url_prefix or ''

    # Get app server port from config
    app_port = current_app.config.get('APP_SERVER_PORT', 5000)

    return render_template('ide.html', api_base=api_base, app_port=app_port)


def test():
    """Test page for API endpoints"""
    return render_template('test.html')


def debug():
    """Debug page to test API endpoints"""
    import os
    from flask import current_app

    project_root = get_project_root()

    debug_info = {
        'project_root': str(project_root),
        'gui_blueprint_registered': True,
        'static_folder': gui_bp.static_folder,
        'template_folder': gui_bp.template_folder,
        'db_available': current_app.config.get('DB') is not None,
    }

    return f"<pre>{json.dumps(debug_info, indent=2)}</pre>"


def list_files():
    """
    List all files in the project directory
    Returns a tree structure of files and folders
    """
    project_root = get_project_root()

    def build_tree(path):
        """Recursively build file tree"""
        items = []

        try:
            for item in sorted(path.iterdir()):
                # Skip hidden files, __pycache__, .git, etc.
                if item.name.startswith('.') or item.name == '__pycache__':
                    continue

                if item.is_dir():
                    items.append({
                        'name': item.name,
                        'type': 'directory',
                        'path': str(item.relative_to(project_root)),
                        'children': build_tree(item)
                    })
                else:
                    items.append({
                        'name': item.name,
                        'type': 'file',
                        'path': str(item.relative_to(project_root)),
                        'extension': item.suffix
                    })
        except PermissionError:
            pass

        return items

    tree = build_tree(project_root)
    return jsonify({'files': tree, 'root': str(project_root)})


def get_file(filepath):
    """
    Get contents of a specific file
    """
    project_root = get_project_root()
    file_path = project_root / filepath

    # Security: ensure file is within project directory
    try:
        file_path = file_path.resolve()
        project_root = project_root.resolve()
        if not str(file_path).startswith(str(project_root)):
            abort(403)
    except Exception:
        abort(404)

    if not file_path.exists() or not file_path.is_file():
        abort(404)

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        return jsonify({
            'path': filepath,
            'content': content,
            'language': get_language_from_extension(file_path.suffix)
        })
    except UnicodeDecodeError:
        # Binary file
        return jsonify({
            'path': filepath,
            'content': None,
            'error': 'Binary file cannot be displayed',
            'language': 'text'
        }), 400


def save_file(filepath):
    """
    Save contents to a file
    """
    project_root = get_project_root()
    file_path = project_root / filepath

    # Security: ensure file is within project directory
    try:
        file_path = file_path.resolve()
        project_root = project_root.resolve()
        if not str(file_path).startswith(str(project_root)):
            abort(403)
    except Exception:
        abort(404)

    data = request.get_json()
    content = data.get('content', '')

    try:
        # Create parent directories if they don't exist
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)

        return jsonify({'success': True, 'path': filepath})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def delete_file(filepath):
    """
    Delete a file
    """
    project_root = get_project_root()
    file_path = project_root / filepath

    # Security: ensure file is within project directory
    try:
        file_path = file_path.resolve()
        project_root = project_root.resolve()
        if not str(file_path).startswith(str(project_root)):
            abort(403)
    except Exception:
        abort(404)

    if not file_path.exists():
        abort(404)

    try:
        if file_path.is_file():
            file_path.unlink()
        elif file_path.is_dir():
            # Only delete if empty
            file_path.rmdir()

        return jsonify({'success': True, 'path': filepath})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def create_file():
    """
    Create a new file or directory
    """
    project_root = get_project_root()
    data = request.get_json()

    path = data.get('path', '')
    file_type = data.get('type', 'file')  # 'file' or 'directory'

    file_path = project_root / path

    # Security: ensure file is within project directory
    try:
        file_path = file_path.resolve()
        project_root = project_root.resolve()
        if not str(file_path).startswith(str(project_root)):
            abort(403)
    except Exception:
        abort(404)

    try:
        if file_type == 'directory':
            file_path.mkdir(parents=True, exist_ok=True)
        else:
            # Create parent directories if needed
            file_path.parent.mkdir(parents=True, exist_ok=True)
            # Create empty file
            file_path.touch()

        return jsonify({'success': True, 'path': path})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def get_routes():
    """
    Get all routes defined in .stpl files
    This will be used for the route explorer
    """
    from scribe.parser import TemplateParser
    import glob

    project_root = get_project_root()
    parser = TemplateParser()
    all_routes = []

    # Find all .stpl files
    stpl_files = list(project_root.glob('**/*.stpl'))

    for stpl_file in stpl_files:
        try:
            routes = parser.parse_file(str(stpl_file))

            for route in routes:
                all_routes.append({
                    'path': route.path,
                    'methods': route.methods,
                    'decorators': route.decorators,
                    'file': str(stpl_file.relative_to(project_root))
                })
        except Exception as e:
            # Skip files that fail to parse
            continue

    return jsonify({'routes': all_routes})


def get_database_connections():
    """
    Get list of available database connections
    """
    from flask import current_app

    try:
        db_manager = current_app.config.get('DB')
        if not db_manager:
            return jsonify({'connections': [], 'error': 'No database configured'}), 500

        # Get all connection names
        connections = list(db_manager.keys())

        return jsonify({'connections': connections})

    except Exception as e:
        return jsonify({'connections': [], 'error': str(e)}), 500


def get_database_tables(connection_name):
    """
    Get list of all database tables for a specific connection
    """
    from flask import current_app

    try:
        db_manager = current_app.config.get('DB')
        if not db_manager:
            return jsonify({'tables': [], 'error': 'No database configured'}), 500

        if connection_name not in db_manager:
            return jsonify({'tables': [], 'error': f'Connection "{connection_name}" not found'}), 404

        db = db_manager[connection_name]
        db_type = db.config.get('type', 'sqlite').lower()

        if db_type == 'sqlite':
            rows = db.query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            tables = [row['name'] for row in rows]
        elif db_type == 'postgresql':
            rows = db.query("""
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                ORDER BY table_schema, table_name
            """)
            tables = [f"{row['table_schema']}.{row['table_name']}" for row in rows]
        elif db_type == 'mssql':
            rows = db.query("""
                SELECT TABLE_NAME
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_TYPE = 'BASE TABLE'
                ORDER BY TABLE_NAME
            """)
            tables = [row['TABLE_NAME'] for row in rows]
        else:
            return jsonify({'tables': [], 'error': f'Database type {db_type} not supported yet'}), 500

        return jsonify({'tables': tables})

    except Exception as e:
        return jsonify({'tables': [], 'error': str(e)}), 500


def _get_table_columns(db, db_type, table_name):
    """Get ordered column names for a table via schema queries (used when table is empty)."""
    if db_type == 'sqlite':
        rows = db.query(f"PRAGMA table_info({table_name})")
        return [row['name'] for row in rows]
    elif db_type == 'postgresql':
        parts = table_name.split('.', 1)
        if len(parts) == 2:
            rows = db.query(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position",
                (parts[0], parts[1])
            )
        else:
            rows = db.query(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') AND table_name = ? "
                "ORDER BY ordinal_position",
                (table_name,)
            )
        return [row['column_name'] for row in rows]
    elif db_type == 'mssql':
        rows = db.query(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION",
            (table_name,)
        )
        return [row['COLUMN_NAME'] for row in rows]
    return []


def _serialize_value(v):
    """Convert non-JSON-serializable database values to strings."""
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    return str(v)


def get_table_data(connection_name, table_name):
    """
    Get data from a specific table with pagination
    """
    from flask import current_app

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    try:
        db_manager = current_app.config.get('DB')
        if not db_manager:
            return jsonify({'error': 'No database configured'}), 500

        if connection_name not in db_manager:
            return jsonify({'error': f'Connection "{connection_name}" not found'}), 404

        db = db_manager[connection_name]

        # Security: validate table name - allow schema.table format, each part alphanumeric/underscore
        parts = table_name.split('.')
        if len(parts) > 2 or not all(p and p.replace('_', '').isalnum() for p in parts):
            return jsonify({'error': 'Invalid table name'}), 400

        db_type = db.config.get('type', 'sqlite').lower()

        if db_type not in ('sqlite', 'postgresql', 'mssql'):
            return jsonify({'error': f'Database type {db_type} not supported yet'}), 500

        # Get total count
        count_rows = db.query(f"SELECT COUNT(*) AS cnt FROM {table_name}")
        total = list(count_rows[0].values())[0] if count_rows else 0

        # Get paginated data
        offset = (page - 1) * per_page
        if db_type == 'mssql':
            rows = db.query(
                f"SELECT * FROM {table_name} ORDER BY (SELECT NULL) OFFSET ? ROWS FETCH NEXT ? ROWS ONLY",
                (offset, per_page)
            )
        else:
            rows = db.query(f"SELECT * FROM {table_name} LIMIT ? OFFSET ?", (per_page, offset))

        # Get columns from data if available, otherwise query the schema
        if rows:
            columns = list(rows[0].keys())
        else:
            columns = _get_table_columns(db, db_type, table_name)

        if not columns:
            return jsonify({'error': 'Table not found'}), 404

        data = [{k: _serialize_value(v) for k, v in row.items()} for row in rows]

        return jsonify({
            'table': table_name,
            'columns': columns,
            'data': data,
            'total': total,
            'page': page,
            'per_page': per_page
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


def get_language_from_extension(ext):
    """Map file extension to Monaco Editor language identifier"""
    language_map = {
        '.stpl': 'scribe-template',  # Custom language we'll define
        '.py': 'python',
        '.js': 'javascript',
        '.json': 'json',
        '.html': 'html',
        '.css': 'css',
        '.sql': 'sql',
        '.md': 'markdown',
        '.txt': 'plaintext',
        '.yml': 'yaml',
        '.yaml': 'yaml',
        '.xml': 'xml',
        '.sh': 'shell',
    }

    return language_map.get(ext.lower(), 'plaintext')
