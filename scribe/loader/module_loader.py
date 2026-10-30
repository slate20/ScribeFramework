"""
Auto-loader for helper modules from lib/ directory.

Loads all .py files from the project's lib/ directory and makes
their functions and classes available in template code blocks.
"""

import os
import sys
import importlib.util
import importlib.machinery
from typing import Dict, Any


def load_helper_modules(project_path: str) -> Dict[str, Any]:
    """
    Load all Python modules from the lib/ directory.

    Args:
        project_path: Path to the project directory

    Returns:
        Dict of module_name -> module object or function

    Example:
        Project structure:
            myproject/
            ├── lib/
            │   ├── helpers.py      # Contains format_date(), slugify()
            │   └── validators.py   # Contains is_valid_email()
            └── app.stpl

        In template:
            {$
            # format_date and slugify are automatically available
            formatted = format_date(user['created_at'])
            slug = slugify(post['title'])
            $}
    """
    lib_path = os.path.join(project_path, 'lib')

    # If lib/ directory doesn't exist, return empty dict
    if not os.path.exists(lib_path) or not os.path.isdir(lib_path):
        return {}

    helpers = {}

    # Add lib/ to Python path temporarily
    if lib_path not in sys.path:
        sys.path.insert(0, lib_path)

    try:
        # Find all .py files in lib/
        for filename in os.listdir(lib_path):
            if not filename.endswith('.py'):
                continue

            if filename.startswith('_'):
                # Skip private modules (like __init__.py)
                continue

            module_name = filename[:-3]  # Remove .py extension
            module_path = os.path.join(lib_path, filename)

            try:
                # Load the module
                spec = importlib.util.spec_from_file_location(module_name, module_path)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)

                    # Extract all public functions and classes from the module
                    for name in dir(module):
                        if name.startswith('_'):
                            continue

                        obj = getattr(module, name)

                        # Only include functions and classes defined in this module
                        # (skip imported stuff)
                        if hasattr(obj, '__module__') and obj.__module__ == module_name:
                            helpers[name] = obj

                    print(f"  Loaded {len([n for n in dir(module) if not n.startswith('_')])} helper(s) from lib/{filename}")

            except Exception as e:
                print(f"Warning: Failed to load lib/{filename}: {e}")
                continue

    finally:
        # Remove lib/ from Python path
        if lib_path in sys.path:
            sys.path.remove(lib_path)

    return helpers


def load_compiled_helper_modules(lib_compiled_dir: str) -> Dict[str, Any]:
    """
    Load helper modules precompiled to .pyc from a directory.

    Mirrors load_helper_modules(), but loads bytecode-only files via
    SourcelessFileLoader instead of source .py files. Used by a build tool's
    output runtime, which ships lib/ as precompiled bytecode rather than
    source for distribution.

    Args:
        lib_compiled_dir: Directory containing compiled .pyc files (one per
            original lib/*.py module, same base filename)

    Returns:
        Dict of function/class name -> object, same shape as
        load_helper_modules()
    """
    if not os.path.exists(lib_compiled_dir) or not os.path.isdir(lib_compiled_dir):
        return {}

    helpers = {}

    if lib_compiled_dir not in sys.path:
        sys.path.insert(0, lib_compiled_dir)

    try:
        for filename in os.listdir(lib_compiled_dir):
            if not filename.endswith('.pyc'):
                continue

            module_name = filename[:-4]  # Remove .pyc extension
            module_path = os.path.join(lib_compiled_dir, filename)

            try:
                loader = importlib.machinery.SourcelessFileLoader(module_name, module_path)
                spec = importlib.util.spec_from_loader(module_name, loader)
                module = importlib.util.module_from_spec(spec)
                loader.exec_module(module)

                for name in dir(module):
                    if name.startswith('_'):
                        continue

                    obj = getattr(module, name)

                    if hasattr(obj, '__module__') and obj.__module__ == module_name:
                        helpers[name] = obj

            except Exception as e:
                print(f"Warning: Failed to load compiled lib/{filename}: {e}")
                continue

    finally:
        if lib_compiled_dir in sys.path:
            sys.path.remove(lib_compiled_dir)

    return helpers
