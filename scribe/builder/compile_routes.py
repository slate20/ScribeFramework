"""
Standalone script executed via the *target project's* venv Python to
precompile route code and lib/ helpers.

This must run as the project's own interpreter (not scribe-build's own,
possibly different, embedded interpreter) because marshal's bytecode format
is only guaranteed compatible within the same Python build/minor version.
Compiling here — with the exact interpreter that will later load this
bytecode inside the frozen executable — sidesteps that version-mismatch
risk entirely instead of hoping the two happen to match.

Must be invoked by path (not via `-m`) with this file sitting next to the
staged `scribe/` runtime bundle, e.g.:

    venv_python /path/to/_scribe_build/_compile_routes.py manifest.json

so that `import scribe...` resolves to the sibling runtime bundle placed
there by staging, not to any scribe install found elsewhere in the venv.
"""

import json
import marshal
import os
import py_compile
import sys


def main(manifest_path):
    with open(manifest_path, 'r', encoding='utf-8') as f:
        manifest = json.load(f)

    from scribe.execution.context import compile_route_code

    code_dir = manifest['code_dir']
    os.makedirs(code_dir, exist_ok=True)
    for route in manifest['routes']:
        code_obj = compile_route_code(route['source'])
        out_path = os.path.join(code_dir, route['code_file'])
        with open(out_path, 'wb') as out_f:
            out_f.write(marshal.dumps(code_obj))

    lib_src_dir = manifest.get('lib_src_dir')
    lib_out_dir = manifest.get('lib_out_dir')
    if lib_src_dir and os.path.isdir(lib_src_dir):
        os.makedirs(lib_out_dir, exist_ok=True)
        for filename in os.listdir(lib_src_dir):
            if not filename.endswith('.py') or filename.startswith('_'):
                continue
            src_path = os.path.join(lib_src_dir, filename)
            out_path = os.path.join(lib_out_dir, filename[:-3] + '.pyc')
            py_compile.compile(src_path, cfile=out_path, doraise=True)

    print(f"  Compiled {len(manifest['routes'])} route(s)"
          + (f" and lib/ helpers from {lib_src_dir}" if lib_src_dir else ""))


if __name__ == '__main__':
    main(sys.argv[1])
