"""
ScribeEngine - A Python web framework where you write Python directly in templates.

Version: 2.2.0-alpha
Author: ScribeEngine Team
License: MIT (TBD)
"""

__version__ = "2.2.0-alpha"
__author__ = "ScribeEngine Team"

__all__ = ["create_app", "__version__"]


def __getattr__(name):
    # Lazy: scribe.app imports Flask, which not every consumer of this
    # package needs importable. scribe-build in particular runs small
    # scripts (see scribe.builder.compile_routes) through a project's venv
    # that only has to contain that project's *own* dependencies — Flask
    # itself ships bundled inside the scribe/scribe-build binaries, not in
    # the project venv — so importing `scribe` at all must not force Flask
    # to be importable.
    if name == "create_app":
        from scribe.app import create_app
        return create_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
