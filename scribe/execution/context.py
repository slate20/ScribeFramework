"""
Execution context for sandboxed Python code in templates.

This module provides a controlled environment for executing Python code
from template files, with access to database, session, request, and helpers.
"""

import textwrap
import types
import inspect
from typing import Dict, Any, Optional
from scribe.execution.builtins import get_safe_builtins


class ExecutionContext:
    """
    Execution environment for template Python code.

    Provides access to:
        - Database operations (db)
        - Session management (session)
        - Request data (request)
        - Flask g object (g)
        - Helper functions from lib/
        - Full Python builtins including import
    """

    def __init__(
        self,
        db=None,
        session=None,
        request=None,
        g=None,
        helpers: Optional[Dict[str, Any]] = None,
        route_params: Optional[Dict[str, Any]] = None
    ):
        """
        Initialize execution context.

        Args:
            db: DatabaseAdapter instance
            session: Flask session object
            request: Flask request object
            g: Flask g object
            helpers: Dict of helper functions/objects loaded from lib/
            route_params: Dict of route parameters (e.g., {'post_id': 123})
        """
        self.db = db
        self.session = session
        self.request = request
        self.g = g
        self.helpers = helpers or {}
        self.route_params = route_params or {}

        # Namespace for code execution (variables set in Python blocks)
        self.namespace: Dict[str, Any] = {}

        # Build the execution globals
        self._build_globals()

    def _build_globals(self):
        """
        Build the global namespace for code execution.

        Includes:
            - Full Python builtins (including import)
            - Database adapter (db)
            - Session (session)
            - Request (request)
            - Flask g (g)
            - Helper functions
            - Route parameters
        """
        # Start with full builtins
        self.namespace = get_safe_builtins()

        # Add framework objects
        self.namespace['db'] = self.db
        self.namespace['session'] = self.session
        self.namespace['request'] = self.request
        self.namespace['g'] = self.g

        # Add helpers from lib/ directory
        self.namespace.update(self.helpers)

        # Add route parameters (e.g., post_id from /posts/<int:post_id>)
        self.namespace.update(self.route_params)

        # Pre-import commonly used standard library modules for convenience
        self._add_common_imports()

        self.current_template: Optional[str] = None

    def render(self, template: str, extra_vars: Optional[Dict[str, Any]] = None) -> str:
        """Render a template string using the current context variables."""
        from flask import render_template_string
        
        # Build template context (all user variables + framework objects)
        variables = self.get_variables()
        if extra_vars:
            variables.update(extra_vars)
            
        # Add framework objects
        variables['session'] = self.session
        variables['request'] = self.request
        variables['g'] = self.g
        
        return render_template_string(template, **variables)

    def _add_common_imports(self):
        """Pre-import commonly used modules into the namespace for convenience."""
        import datetime
        import json
        import re
        import math

        self.namespace['datetime'] = datetime
        self.namespace['json'] = json
        self.namespace['re'] = re
        self.namespace['math'] = math

    def execute(self, code: str) -> Any:
        """
        Execute Python code in the template environment.

        ## How this works

        User code is wrapped in a function so that `return` statements are
        syntactically valid (bare `return` is illegal outside a function in
        Python). However, wrapping code in a function introduces a scoping
        problem: any variable the user assigns (e.g. `message = "hello"`)
        becomes a *local* variable of the wrapper function and disappears
        when the function returns — never making it into self.namespace where
        get_variables() can find it for template rendering.

        ### The fix: __locals__ capture dict

        Before calling the wrapper, we inject a dict `__locals__` into the
        namespace. The wrapper function calls `__locals__.update(locals())`
        in two places:

          1. Immediately before every `return` statement, so variables
             assigned before an early return are still captured.
          2. At the very end of the function body, for the normal (no-return)
             case.

        After the function returns, we merge `__locals__` back into
        self.namespace, making all user-assigned variables available to
        get_variables() and therefore to the Jinja2 template.

        ### Safe return transformation

        We do a minimal, safe transformation of `return` lines: a line is
        only transformed if its *stripped* form starts with the keyword
        `return` as a whole word. This means `return` appearing mid-line
        (e.g. inside a string like `"please return your books"`) is never
        touched, because it won't appear at the start of a stripped line.

        Args:
            code: Python code to execute

        Returns:
            The value passed to `return` in the code, or None

        Raises:
            ExecutionError: wraps any exception raised by the user code
        """
        try:
            # Inject the locals capture dict into the namespace so the
            # wrapper function can write into it.
            local_capture: Dict[str, Any] = {}
            self.namespace['__locals__'] = local_capture

            # Inject frame() helper
            def frame(template=None, event=None, **kwargs):
                """
                Renders the current route's template using the caller's local variables.
                """
                target_template = template or self.current_template
                if not target_template:
                    return ""
                
                # Capture caller's locals
                import inspect
                f = inspect.currentframe().f_back
                caller_vars = f.f_locals.copy()
                caller_vars.update(kwargs)
                
                html = self.render(target_template, extra_vars=caller_vars)
                if event:
                    # Fix: handle multiline HTML for SSE
                    data_lines = [f"data: {line}" for line in html.split('\n')]
                    return f"event: {event}\n" + "\n".join(data_lines) + "\n\n"
                return html
            
            self.namespace['frame'] = frame

            # Safe line-by-line return transformation.
            # We only touch a line if its stripped content starts with the
            # `return` keyword — this never fires for `return` mid-line
            # (inside strings or comments) because those don't start a line
            # with `return` after stripping leading whitespace.
            processed_lines = []
            for line in code.split('\n'):
                stripped = line.lstrip()
                line_indent = line[:len(line) - len(stripped)]
                if (stripped == 'return'
                        or stripped.startswith('return ')
                        or stripped.startswith('return\t')):
                    # Capture all locals before this return so that variables
                    # assigned before an early exit are available to templates.
                    processed_lines.append(
                        f"{line_indent}__locals__.update(locals())"
                    )
                    processed_lines.append(line)
                else:
                    processed_lines.append(line)

            # Indent the processed body by 4 spaces (one level inside the
            # wrapper function), then append the end-of-function capture line
            # at the same indentation level.
            indented_body = textwrap.indent('\n'.join(processed_lines), '    ')
            wrapper_src = (
                f"def __scribe_route_handler__():\n"
                f"{indented_body}\n"
                f"    __locals__.update(locals())\n"
            )

            # Execute the function definition in the shared namespace so that
            # the function body can access db, session, request, etc. as globals.
            exec(wrapper_src, self.namespace)  # noqa: S102

            # Call the wrapper and capture any explicit return value.
            result = self.namespace['__scribe_route_handler__']()

            # Merge user-assigned variables back into the shared namespace so
            # that get_variables() can find them for template rendering.
            for k, v in local_capture.items():
                if not k.startswith('_'):
                    self.namespace[k] = v

            # Store an explicit return value (redirect, jsonify, abort, etc.)
            # under the sentinel key so has_return_value() / get_variable()
            # can retrieve it in create_route_handler.
            if result is not None:
                self.namespace['__return__'] = result

            return result

        except Exception as e:
            raise ExecutionError(f"Error executing template code: {e}") from e

    def get_variable(self, name: str, default: Any = None) -> Any:
        """
        Get a variable from the execution namespace.

        Args:
            name: Variable name
            default: Default value if variable doesn't exist

        Returns:
            Variable value or default
        """
        return self.namespace.get(name, default)

    def get_variables(self) -> Dict[str, Any]:
        """
        Get all user-defined variables from the namespace for template rendering.

        Excludes builtins, framework objects, modules, and private names.

        Returns:
            Dict of variable name -> value
        """
        # Names injected by the framework that should never appear in templates
        framework_names = {
            'db', 'session', 'request', 'g',
            '__scribe_route_handler__',
            '__locals__',
        }

        user_vars = {}
        for key, value in self.namespace.items():
            # Skip private / dunder names
            if key.startswith('_'):
                continue

            # Skip framework-injected names
            if key in framework_names:
                continue

            # Skip modules
            if isinstance(value, types.ModuleType):
                continue

            # Skip built-in callables (functions and classes whose module is
            # 'builtins'). This excludes Python's built-ins while keeping any
            # functions the developer defined in their template code.
            if callable(value) and getattr(value, '__module__', None) == 'builtins':
                continue

            if inspect.isclass(value) and value.__module__ == 'builtins':
                continue

            user_vars[key] = value

        return user_vars

    def set_variable(self, name: str, value: Any):
        """
        Set a variable in the execution namespace.

        Args:
            name: Variable name
            value: Variable value
        """
        self.namespace[name] = value

    def has_return_value(self) -> bool:
        """
        Check if the executed code produced a return value
        (e.g. redirect, jsonify, abort).

        Returns:
            True if code returned a non-None value
        """
        return '__return__' in self.namespace


class ExecutionError(Exception):
    """Exception raised when template code execution fails."""
    pass
