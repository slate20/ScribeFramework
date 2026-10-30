"""
Abstract Syntax Tree (AST) node definitions for ScribeEngine templates.

These classes represent the parsed structure of .stpl files.
"""

from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class PythonBlock:
    """Represents a Python code block: {$ ... $}"""
    code: str
    line_number: int = 0

    def __str__(self):
        return f"PythonBlock(lines={len(self.code.splitlines())}, start_line={self.line_number})"


@dataclass
class TemplateBlock:
    """Represents an HTML/Jinja2 template block"""
    content: str
    line_number: int = 0

    def __str__(self):
        return f"TemplateBlock(length={len(self.content)}, start_line={self.line_number})"


@dataclass
class Route:
    """
    Represents a complete route definition.

    A route consists of:
    - Path pattern (e.g., '/posts/<int:post_id>')
    - HTTP methods (GET, POST, etc.)
    - Optional decorators (@require_auth, @rate_limit, etc.)
    - Python code block to execute
    - HTML/Jinja2 template to render

    Flags:
    - no_layout: When True, the template is rendered as-is without being wrapped in base.stpl.
    - csrf_exempt: When True, this route is exempted from Flask-WTF's CSRF
      protection (see scribe/app.py register_routes()). Intended for
      bearer-token/API routes that can't carry the session-bound CSRF cookie.
    """
    path: str
    methods: List[str] = field(default_factory=lambda: ['GET'])
    decorators: List[str] = field(default_factory=list)
    python_code: Optional[str] = None
    template: Optional[str] = None
    line_number: int = 0
    source_file: Optional[str] = None
    no_layout: bool = False
    is_sse: bool = False
    csrf_exempt: bool = False

    # Precompiled code object for this route's Python block (a
    # types.CodeType produced by scribe.execution.context.compile_route_code
    # and reloaded via marshal). Set only when a route is reconstructed from
    # a build tool's precompiled artifacts instead of parsed from a .stpl
    # file; python_code is None in that case. See scribe/app.py
    # create_route_handler().
    compiled_code: Optional[Any] = field(default=None, repr=False, compare=False)

    # Extracted from path pattern
    path_parameters: List[str] = field(default_factory=list)

    def __post_init__(self):
        """Extract path parameters from the route path."""
        import re
        # Extract parameters like <int:post_id>, <username>, etc.
        pattern = r'<(?:(?P<type>\w+):)?(?P<name>\w+)>'
        matches = re.finditer(pattern, self.path)
        self.path_parameters = [match.group('name') for match in matches]

    def __str__(self):
        methods_str = ','.join(self.methods)
        decorators_str = f" [{', '.join(self.decorators)}]" if self.decorators else ""
        layout_str = " [no_layout]" if self.no_layout else ""
        return f"Route({self.path} [{methods_str}]{decorators_str})"

    def get_function_name(self):
        """
        Generate a unique function name for this route.

        Examples:
            '/' -> 'route_root'
            '/about' -> 'route_about'
            '/posts/<int:post_id>' -> 'route_posts_post_id'
        """
        import re
        # Remove leading/trailing slashes
        path = self.path.strip('/')
        if not path:
            return 'route_root'

        # Replace slashes with underscores
        path = path.replace('/', '_')

        # Remove parameter type annotations and angle brackets
        path = re.sub(r'<(?:\w+:)?(\w+)>', r'\1', path)

        # Replace any remaining special characters with underscores
        path = re.sub(r'[^a-zA-Z0-9_]', '_', path)

        return f'route_{path}'
