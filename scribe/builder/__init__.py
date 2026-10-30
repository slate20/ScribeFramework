"""
scribe-build: compiles a Scribe project directory into a standalone,
distributable executable.

This is a separate tool from the `scribe` dev/serve CLI. It stages a
project's routes and lib/ helpers as precompiled bytecode, then shells out
to the *project's own* venv Python to run PyInstaller — PyInstaller cannot
be invoked from within an already-frozen binary, so a real interpreter is
required regardless of whether scribe-build itself is run frozen or from
source.
"""
