"""
ScribeEngine GUI IDE Module

This module provides a web-based integrated development environment (IDE)
for developing ScribeEngine applications. It includes:
- Code editor with .stpl syntax highlighting (Monaco Editor)
- Live preview panel for real-time template rendering
- Database browser for visual DB exploration
- File management UI
- Route explorer

The GUI is designed to run on localhost only by default for security.
"""

from flask import Blueprint


def create_blueprint():
    """
    Create and configure GUI blueprint for standalone mode.

    The blueprint is always mounted at root (/) with static files at /_gui_static/
    to avoid conflicts with the application's /static folder.

    Returns:
        Flask Blueprint instance configured for GUI IDE
    """
    bp = Blueprint(
        'gui',
        __name__,
        template_folder='templates',
        static_folder='static',
        static_url_path='/_gui_static',  # Avoid conflict with app /static
        url_prefix=''  # Mount at root
    )

    _register_routes(bp)
    return bp


def _register_routes(bp):
    """
    Register all GUI routes on the blueprint programmatically.

    This approach allows us to create the blueprint dynamically without
    decorator-based binding issues.
    """
    from scribe.gui import routes

    # Main pages
    bp.add_url_rule('/', 'index', routes.index, methods=['GET'])
    bp.add_url_rule('/test', 'test', routes.test, methods=['GET'])
    bp.add_url_rule('/debug', 'debug', routes.debug, methods=['GET'])

    # API - Files
    bp.add_url_rule('/api/files', 'list_files', routes.list_files, methods=['GET'])
    bp.add_url_rule('/api/file/<path:filepath>', 'get_file', routes.get_file, methods=['GET'])
    bp.add_url_rule('/api/file/<path:filepath>', 'save_file', routes.save_file, methods=['POST'])
    bp.add_url_rule('/api/file/<path:filepath>', 'delete_file', routes.delete_file, methods=['DELETE'])
    bp.add_url_rule('/api/file/new', 'create_file', routes.create_file, methods=['POST'])

    # API - Routes
    bp.add_url_rule('/api/routes', 'get_routes', routes.get_routes, methods=['GET'])

    # API - Database
    bp.add_url_rule('/api/database/connections', 'get_database_connections',
                    routes.get_database_connections, methods=['GET'])
    bp.add_url_rule('/api/database/<connection_name>/tables', 'get_database_tables',
                    routes.get_database_tables, methods=['GET'])
    bp.add_url_rule('/api/database/<connection_name>/table/<table_name>', 'get_table_data',
                    routes.get_table_data, methods=['GET'])


__all__ = ['create_blueprint']
