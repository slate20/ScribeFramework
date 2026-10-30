"""
Loading schemas/schema_{name}.py files.
"""

import importlib.util
import os
import traceback
from typing import Optional

from scribe.schema import dsl
from scribe.schema.dsl import SchemaDefinition, SchemaError

SCHEMAS_DIR = 'schemas'

DSL_NAMES = ('Table', 'Column', 'Index', 'ForeignKey', 'sql', 'raw_sql', 'unmanaged', 'scope')


def schemas_dir(project_path: str) -> str:
    return os.path.join(project_path, SCHEMAS_DIR)


def schema_file_path(project_path: str, connection_name: str) -> str:
    """Path of the schema file for a connection: schemas/schema_{name}.py"""
    return os.path.join(schemas_dir(project_path), f"schema_{connection_name}.py")


def load_schema(path: str) -> SchemaDefinition:
    """
    Run a schema file and collect what it declares.

    Args:
        path: Path to a schema_{name}.py file

    Returns:
        SchemaDefinition

    Raises:
        SchemaError: If the file fails to run or declares something invalid.
                     The message includes the file and line where possible.
    """
    definition = SchemaDefinition(source=path)
    module_name = f"_scribe_schema_{os.path.splitext(os.path.basename(path))[0]}"

    dsl._active = definition
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise SchemaError(f"{path}: not a Python file")
        module = importlib.util.module_from_spec(spec)
        # The DSL is available without imports, so a file written by an older
        # `scribe schema pull` can use newer calls such as scope()
        module.__dict__.update({name: getattr(dsl, name) for name in DSL_NAMES})
        spec.loader.exec_module(module)
    except SchemaError as e:
        raise SchemaError(f"{_location(path, e)}{e}") from e
    except SyntaxError as e:
        raise SchemaError(f"{path}:{e.lineno}: {e.msg}") from e
    except Exception as e:
        message = str(e).replace('.__init__()', '()')
        raise SchemaError(f"{_location(path, e)}{type(e).__name__}: {message}") from e
    finally:
        dsl._active = None

    try:
        definition.validate()
    except SchemaError as e:
        raise SchemaError(f"{path}: {e}") from e
    return definition


def load_schema_if_exists(project_path: str, connection_name: str) -> Optional[SchemaDefinition]:
    path = schema_file_path(project_path, connection_name)
    return load_schema(path) if os.path.exists(path) else None


def _location(path: str, error: Exception) -> str:
    """'path:line: ' for the deepest traceback frame inside the schema file."""
    target = os.path.abspath(path)
    line = None
    for frame in traceback.extract_tb(error.__traceback__):
        if os.path.abspath(frame.filename) == target:
            line = frame.lineno
    return f"{path}:{line}: " if line else f"{path}: "
