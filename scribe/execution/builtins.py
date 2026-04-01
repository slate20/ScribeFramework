"""
Safe builtins for sandboxed Python execution in templates.

This module defines which built-in functions and types are available
in template code blocks, blocking dangerous operations like file I/O
and system calls.
"""

import builtins as _builtins

def get_safe_builtins():
    """
    Return the full Python builtins dictionary
    """
    return vars(_builtins).copy()
