"""
Writing schema files for `scribe schema init` and `scribe schema pull`, and
the IDE's managed toggle.

Pull only ever appends: tables already declared in the file (managed or
not, including unmanaged()) are left exactly as the user wrote them.
"""

import ast
import datetime
import json
import os
from typing import Dict, List, Tuple

from scribe.schema.introspect import LiveTable
from scribe.schema.dsl import SchemaError
from scribe.schema.loader import load_schema
from scribe.schema.normalize import default_to_python, python_literal

IMPORT_LINE = "from scribe.schema import Table, Column, Index, ForeignKey, sql, raw_sql, unmanaged, scope\n"


def render_scope(selected) -> str:
    """Source for a scope() call, wrapped one pattern per line when long."""
    args = []
    for argument, patterns in (('include', selected.include), ('exclude', selected.exclude)):
        if patterns:
            args.append(f"{argument}=[{', '.join(json.dumps(p) for p in patterns)}]")
    one_line = f"scope({', '.join(args)})"
    if len(one_line) <= 100:
        return one_line + "\n"
    lines = ["scope("]
    for argument, patterns in (('include', selected.include), ('exclude', selected.exclude)):
        if patterns:
            lines.append(f"    {argument}=[")
            lines += [f"        {json.dumps(p)}," for p in patterns]
            lines.append("    ],")
    return '\n'.join(lines + [")"]) + "\n"


def render_header(connection_name: str, dialect: str) -> str:
    return (
        f'"""\n'
        f"Schema for the '{connection_name}' database connection ({dialect}).\n"
        f"\n"
        f"Column types are {dialect}'s own types. Tables added by `scribe schema pull`\n"
        f"start as managed=False; set managed=True on tables Scribe should migrate.\n"
        f"\n"
        f"    scribe schema diff --database {connection_name}     # compare with the database\n"
        f"    scribe schema status --database {connection_name}   # summary\n"
        f'"""\n'
        f"\n"
        f"{IMPORT_LINE}"
    )


def render_table(table: LiveTable, dialect: str, managed: bool = False) -> str:
    """Python source declaring a live table (plus its indexes) in the DSL."""
    single_fks = {}
    notes = []
    for fk in table.foreign_keys:
        if len(fk.columns) == 1 and fk.columns[0].lower() not in single_fks:
            single_fks[fk.columns[0].lower()] = fk
        else:
            notes.append(
                f"# Foreign key ({', '.join(fk.columns)}) → {fk.ref_table}({', '.join(fk.ref_columns)}) "
                f"can't be declared on a column; it is not compared by `scribe schema diff`."
            )

    unique_columns = set()
    indexes = []
    for index in table.indexes:
        if index.origin == 'primary_key':
            continue
        if None in index.columns:
            notes.append(
                f"# Expression index {index.name!r} is not compared; declare it with raw_sql() to track it."
            )
        elif index.origin == 'unique' and len(index.columns) == 1:
            unique_columns.add(index.columns[0].lower())
        else:
            indexes.append(index)

    lines = [f"Table({json.dumps(table.name)},"]
    for column in table.columns:
        args = [json.dumps(column.name), json.dumps(column.type)]
        fk = single_fks.get(column.name.lower())
        if fk is not None:
            args.append(f"ForeignKey({json.dumps(f'{fk.ref_table}.{fk.ref_columns[0]}')})")
        if column.primary_key:
            args.append("primary_key=True")
        if column.autoincrement:
            args.append("autoincrement=True")
        if not column.nullable and not column.primary_key:
            args.append("nullable=False")
        if column.name.lower() in unique_columns:
            args.append("unique=True")
        default = None if column.autoincrement else default_to_python(column.default, dialect, column.type)
        if default is not None:
            args.append(f"default={python_literal(default)}")
        lines.append(f"    Column({', '.join(args)}),")
    lines.append(f"    managed={managed},")
    lines.append(")")

    for index in indexes:
        columns = ', '.join(json.dumps(c) for c in index.columns)
        unique = ", unique=True" if index.unique else ""
        lines.append(f"Index({json.dumps(index.name)}, {json.dumps(table.name)}, [{columns}]{unique})")

    return '\n'.join(notes + lines) + '\n'


def write_init_file(path: str, connection_name: str, dialect: str) -> bool:
    """Create an empty schema file. Returns False if it already exists."""
    if os.path.exists(path):
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(render_header(connection_name, dialect))
    return True


def pull_into_file(path: str, connection_name: str, dialect: str,
                   live_tables: List[LiveTable], new_scope=None) -> Tuple[List[str], List[str]]:
    """
    Add live tables that the schema file doesn't declare yet.

    Args:
        path: schemas/schema_{name}.py (created if missing)
        live_tables: Tables read from the database (already limited to the file's scope)
        new_scope: Scope to write into a new file (from `pull --include/--exclude`)

    Returns:
        (added table names, already-declared table names)

    Raises:
        SchemaError: If the existing file doesn't load, or the result doesn't
                     (the file is left unchanged in that case)
    """
    original = None
    declared = None
    if os.path.exists(path):
        declared = load_schema(path)
        with open(path, 'r', encoding='utf-8') as f:
            original = f.read()

    added = [t for t in live_tables if declared is None or not declared.is_declared(t.name)]
    skipped = [t.name for t in live_tables if t not in added]
    if not added:
        return [], skipped

    blocks = '\n\n'.join(render_table(table, dialect) for table in added)
    if original is None:
        header = render_header(connection_name, dialect)
        if new_scope is not None:
            header += "\n" + render_scope(new_scope)
        content = header + '\n\n' + blocks
    else:
        stamp = datetime.date.today().isoformat()
        content = original.rstrip('\n') + f"\n\n\n# --- Added by `scribe schema pull` on {stamp} ---\n\n" + blocks

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

    # The appended code relies on the file's imports; restore the original if it no longer loads
    try:
        load_schema(path)
    except Exception:
        if original is None:
            os.remove(path)
        else:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(original)
        raise

    return [t.name for t in added], skipped


# === Editing declarations in place (IDE) ===

def _table_calls(source: str):
    """(table name, ast.Call) for each Table("name", ...) call in a schema file's source."""
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        called = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
        first = node.args[0]
        if called == 'Table' and isinstance(first, ast.Constant) and isinstance(first.value, str):
            yield first.value, node


def table_lines(path: str) -> Dict[str, int]:
    """Lowercased table name -> line of its Table(...) call, for jumping to a declaration."""
    with open(path, 'r', encoding='utf-8') as f:
        source = f.read()
    try:
        return {name.lower(): call.lineno for name, call in _table_calls(source)}
    except SyntaxError:
        return {}


def set_table_managed(path: str, table_name: str, managed: bool) -> bool:
    """
    Set managed=True/False on a Table(...) call, keeping the rest of the file as written.

    Returns:
        False if the table already had that setting (the file is unchanged)

    Raises:
        SchemaError: If the table isn't declared with a literal Table("name", ...)
                     call, or the edited file doesn't load (it is left unchanged)
    """
    with open(path, 'r', encoding='utf-8') as f:
        original = f.read()

    definition = load_schema(path)
    table = definition.tables.get(table_name.lower())
    if table is None:
        where = "with unmanaged()" if table_name.lower() in definition.unmanaged else "in this file"
        raise SchemaError(f"Table {table_name!r} isn't declared {where}; only Table(...) declarations can be managed")
    if table.managed == managed:
        return False

    calls = [call for name, call in _table_calls(original) if name.lower() == table_name.lower()]
    if len(calls) != 1:
        raise SchemaError(f"Couldn't find the Table({table_name!r}, ...) call to edit; change managed= by hand")
    call = calls[0]

    # ast offsets are UTF-8 byte columns, so edit the encoded source
    data = original.encode('utf-8')
    line_starts = [0]
    for line in data.splitlines(keepends=True):
        line_starts.append(line_starts[-1] + len(line))

    def offset(lineno, col):
        return line_starts[lineno - 1] + col

    value = 'True' if managed else 'False'
    keyword = next((k for k in call.keywords if k.arg == 'managed'), None)
    if keyword is not None:
        start = offset(keyword.value.lineno, keyword.value.col_offset)
        end = offset(keyword.value.end_lineno, keyword.value.end_col_offset)
        data = data[:start] + value.encode() + data[end:]
    else:
        # Add managed=... after the last argument, matching the call's layout
        last = max(call.args + call.keywords, key=lambda n: (n.end_lineno, n.end_col_offset))
        last_end = offset(last.end_lineno, last.end_col_offset)
        between = data[last_end:offset(call.end_lineno, call.end_col_offset) - 1]
        if call.lineno == call.end_lineno:
            insert_at, text = last_end, f", managed={value}"
        else:
            line = data[line_starts[last.lineno - 1]:line_starts[last.lineno]].decode('utf-8')
            indent = line[:len(line) - len(line.lstrip())]
            if b',' in between:
                insert_at, text = last_end + between.index(b',') + 1, f"\n{indent}managed={value},"
            else:
                insert_at, text = last_end, f",\n{indent}managed={value}"
        data = data[:insert_at] + text.encode() + data[insert_at:]

    with open(path, 'wb') as f:
        f.write(data)
    try:
        load_schema(path)
    except SchemaError:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(original)
        raise
    return True
