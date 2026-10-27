"""
Normalizing types and defaults so declared and live values can be compared.

Schema files use each connection's native types, so normalization only
smooths over spelling differences within one dialect (PostgreSQL reports
'varchar(255)' as 'character varying(255)', MSSQL wraps defaults in
parentheses, and so on). It never maps types between dialects.
"""

import json
import re
from typing import Any, Optional, Tuple

from scribe.schema.dsl import SqlExpression

# PostgreSQL aliases -> the name format_type() reports
_PG_TYPE_ALIASES = {
    'int': 'integer', 'int4': 'integer',
    'int8': 'bigint',
    'int2': 'smallint',
    'bool': 'boolean',
    'varchar': 'character varying',
    'char': 'character', 'bpchar': 'character',
    'decimal': 'numeric',
    'float8': 'double precision', 'float': 'double precision',
    'float4': 'real',
    'timestamptz': 'timestamp with time zone',
    'timetz': 'time with time zone',
}

# PostgreSQL pseudo-types that imply an autoincrementing column
_PG_SERIAL_TYPES = {
    'serial': 'integer', 'serial4': 'integer',
    'bigserial': 'bigint', 'serial8': 'bigint',
    'smallserial': 'smallint', 'serial2': 'smallint',
}

_MSSQL_TYPE_ALIASES = {
    'integer': 'int',
    'dec': 'decimal',
    'double precision': 'float',
    'character': 'char',
    'character varying': 'varchar',
}


def normalize_type(type_name: str, dialect: str) -> Tuple[str, bool]:
    """
    Normalize a type name for comparison.

    Returns:
        (normalized type, whether the type itself implies autoincrement)
    """
    text = re.sub(r'\s+', ' ', type_name.strip().lower())
    text = re.sub(r'\s*\(\s*', '(', text)
    text = re.sub(r'\s*\)', ')', text)
    text = re.sub(r'\s*,\s*', ',', text)

    if dialect == 'postgresql':
        return _normalize_pg_type(text)
    if dialect == 'mssql':
        base, args = _split_args(text)
        return _MSSQL_TYPE_ALIASES.get(base, base) + args, False
    return text, False


def _split_args(text: str) -> Tuple[str, str]:
    """'numeric(12,2)' -> ('numeric', '(12,2)')"""
    match = re.match(r'^([a-z0-9_ ]+?)(\(.*\))?$', text)
    if not match:
        return text, ''
    return match.group(1), match.group(2) or ''


def _normalize_pg_type(text: str) -> Tuple[str, bool]:
    array = text.endswith('[]')
    if array:
        text = text[:-2]

    if text in _PG_SERIAL_TYPES:
        return _PG_SERIAL_TYPES[text] + ('[]' if array else ''), True

    # timestamp/time keep their precision before the time zone clause
    match = re.match(r'^(timestamp|time)(\(\d+\))?( with time zone| without time zone)?$', text)
    if match:
        zone = match.group(3) or ' without time zone'
        return f"{match.group(1)}{match.group(2) or ''}{zone}" + ('[]' if array else ''), False

    base, args = _split_args(text)
    base = _PG_TYPE_ALIASES.get(base, base)
    if base == 'character' and not args:
        args = '(1)'
    return base + args + ('[]' if array else ''), False


def declared_default_sql(value: Any, dialect: str) -> Optional[str]:
    """SQL text for a default declared in a schema file (None = no default)."""
    if value is None:
        return None
    if isinstance(value, SqlExpression):
        return value.text
    if isinstance(value, bool):
        if dialect == 'postgresql':
            return 'true' if value else 'false'
        return '1' if value else '0'
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def normalize_default(text: Optional[str], dialect: str) -> Optional[str]:
    """
    Normalize a default expression for comparison.

    Strips MSSQL's wrapping parentheses and PostgreSQL's type casts, treats
    NULL as no default, and unifies boolean spellings as 1/0.
    """
    if text is None:
        return None
    text = text.strip()

    while _wrapped_in_parens(text):
        text = text[1:-1].strip()

    if dialect == 'postgresql':
        # 'open'::text, 'x'::character varying, 0::numeric(12,2)
        previous = None
        while previous != text:
            previous = text
            text = re.sub(r"::[a-z_ ]+(\(\d+(,\s*\d+)?\))?(\[\])?$", '', text, flags=re.IGNORECASE).strip()
            while _wrapped_in_parens(text):
                text = text[1:-1].strip()

    if dialect == 'mssql' and re.match(r"^N'", text):
        text = text[1:]

    if text.startswith("'"):
        return text
    upper = text.upper()
    if upper == 'NULL':
        return None
    if upper == 'TRUE':
        return '1'
    if upper == 'FALSE':
        return '0'
    if re.match(r'^-?\d+(\.\d+)?$', text):
        return repr(float(text)) if '.' in text else str(int(text))
    if dialect == 'postgresql' and upper == 'NOW()':
        return 'CURRENT_TIMESTAMP'
    return upper


def _wrapped_in_parens(text: str) -> bool:
    """True if the outer parentheses enclose the whole expression: '(1)' yes, '(a) + (b)' no."""
    if not (text.startswith('(') and text.endswith(')')):
        return False
    depth = 0
    in_string = False
    for i, char in enumerate(text):
        if char == "'":
            in_string = not in_string
        elif not in_string:
            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
                if depth == 0 and i != len(text) - 1:
                    return False
    return True


def default_to_python(text: Optional[str], dialect: str, type_name: str = '') -> Any:
    """
    Convert a live default into the value `scribe schema pull` writes:
    a Python literal where possible, otherwise sql("...").
    """
    if text is None:
        return None
    raw = text.strip()

    if dialect == 'postgresql' and normalize_type(type_name, dialect)[0] == 'boolean':
        stripped = normalize_default(raw, dialect)
        if stripped in ('1', '0'):
            return stripped == '1'

    normalized = normalize_default(raw, dialect)
    if normalized is None:
        return None
    if normalized.startswith("'") and normalized.endswith("'") and len(normalized) >= 2:
        return normalized[1:-1].replace("''", "'")
    if re.match(r'^-?\d+$', normalized):
        return int(normalized)
    if re.match(r'^-?\d+\.\d+$', normalized):
        return float(normalized)

    # Keep the database's own spelling for expressions, minus wrapping parens/casts
    expression = raw
    while _wrapped_in_parens(expression):
        expression = expression[1:-1].strip()
    if dialect == 'postgresql':
        expression = re.sub(r"::[a-z_ ]+(\(\d+(,\s*\d+)?\))?(\[\])?$", '', expression, flags=re.IGNORECASE).strip()
    return SqlExpression(expression)


def python_literal(value: Any) -> str:
    """Source code for a default value in a generated schema file."""
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return repr(value)
