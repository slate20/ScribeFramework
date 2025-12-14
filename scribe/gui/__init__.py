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

# Create the default GUI blueprint
gui_bp = Blueprint(
    'gui',
    __name__,
    template_folder='templates',
    static_folder='static',
    url_prefix='/__scribe_gui'
)

# Import routes after blueprint creation to avoid circular imports
from scribe.gui import routes


def create_gui_blueprint(url_prefix='/__scribe_gui'):
    """
    Create GUI blueprint with configurable URL prefix.

    Args:
        url_prefix: URL prefix for all GUI routes (default: '/__scribe_gui')
                   Use '' for root mounting in standalone GUI mode

    Returns:
        Flask Blueprint instance
    """
    # If requesting default prefix, return the existing blueprint
    if url_prefix == '/__scribe_gui':
        return gui_bp

    # Otherwise, create a new blueprint with custom prefix
    # and copy all deferred functions (route registrations) from original
    #
    # For static files:
    # - When url_prefix='/__scribe_gui': static files at /__scribe_gui/static (default behavior)
    # - When url_prefix='' (root): static files at /_gui_static to avoid conflict with app's /static
    static_url_path = '/_gui_static' if url_prefix == '' else None

    new_bp = Blueprint(
        'gui',
        __name__,
        template_folder='templates',
        static_folder='static',
        static_url_path=static_url_path,  # Use unique path for root-mounted GUI
        url_prefix=url_prefix
    )

    # Copy all deferred route registrations to the new blueprint
    new_bp.deferred_functions = gui_bp.deferred_functions.copy()

    return new_bp


__all__ = ['gui_bp', 'create_gui_blueprint']
