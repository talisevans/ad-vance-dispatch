"""
Turn a template's filter sets into one DuckDB WHERE fragment and its parameters.

The rules, from decision D8:

  1. Values in one key's list are OR'd; keys are AND'd.
  2. Every filter set given (the template's globals, then the section's own)
     is AND'd onto the others, so a section can only narrow.
  3. `None` in a list means "unmapped": it matches a null column (or, for
     themes, an advert carrying no theme at all).
  4. `affiliation_id` values are widened to every id in the same merge group,
     so a merged affiliation keeps matching whichever id gold holds.

The fragment reads columns through the alias `adverts` and binds every value
as a named parameter (`$filter_0`, `$filter_1`, ...). No value is ever written
into the SQL text.
"""

from dataclasses import dataclass, field

from dispatch.filters.registry import BOOLEAN_VALUES, LIST_ANY_MATCH, check_filter_key


# ---------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------- #

# The alias every fragment reads its columns through
ADVERTS_ALIAS = 'adverts'

# The prefix on every parameter this module binds
PARAMETER_PREFIX = 'filter_'

# The fragment for "no filter at all"
MATCH_EVERYTHING = 'TRUE'


@dataclass
class CompiledFilter:
    """A WHERE fragment over the `adverts` alias and the named parameters it binds."""
    sql: str = MATCH_EVERYTHING
    parameters: dict = field(default_factory=dict)


# ---------------------------------------------------------------- #
# Parameters
# ---------------------------------------------------------------- #

class ParameterBinder:
    """Hands out parameter names in order and remembers the value bound to each."""

    def __init__(self):
        """Start with no parameters bound."""
        self.parameters = {}

    def bind(self, value):
        """Bind one value and return its placeholder, as in `$filter_3`."""
        name = f'{PARAMETER_PREFIX}{len(self.parameters)}'
        self.parameters[name] = value
        return f'${name}'

    def bind_all(self, values):
        """Bind every value in a list and return their placeholders joined by commas."""
        placeholders = []
        for value in values:
            placeholders.append(self.bind(value))
        return ', '.join(placeholders)


# ---------------------------------------------------------------- #
# Values
# ---------------------------------------------------------------- #

def split_null(values):
    """Split a value list into its non-null values and whether it held a null."""
    present_values = []
    holds_null = False

    # Sort each value into one side or the other
    for value in values:
        if value is None:
            holds_null = True
        else:
            present_values.append(value)
    return present_values, holds_null


def check_value_types(filter_key, values):
    """Raise ValueError when a value does not match the key's declared type."""
    for value in values:
        if value is None:
            continue

        # Boolean keys take true or false only
        if filter_key.value_type == BOOLEAN_VALUES:
            if not isinstance(value, bool):
                raise ValueError(f'filter key "{filter_key.key}" takes true or false, got {value!r}')
            continue

        # Every other key takes text
        if not isinstance(value, str):
            raise ValueError(f'filter key "{filter_key.key}" takes text, got {value!r}')


def widen_affiliations(values, affiliation_group):
    """Replace each affiliation id with every id in its merge group, keeping order and dropping repeats."""
    widened = []
    for value in values:
        group = affiliation_group(value)
        for affiliation_id in group:
            if affiliation_id in widened:
                continue
            widened.append(affiliation_id)
    return widened


# ---------------------------------------------------------------- #
# Clauses for one column
# ---------------------------------------------------------------- #

def include_scalar_clause(column, present_values, holds_null, binder):
    """Keep adverts whose column is one of the values, or null when null was listed."""
    parts = []
    if present_values:
        placeholders = binder.bind_all(present_values)
        parts.append(f'{column} IN ({placeholders})')
    if holds_null:
        parts.append(f'{column} IS NULL')
    return '(' + ' OR '.join(parts) + ')'


def exclude_scalar_clause(column, present_values, holds_null, binder):
    """Drop adverts whose column is one of the values, or null when null was listed."""
    parts = []

    # A null column is not "in" the list, so it is kept unless null was listed
    if present_values:
        placeholders = binder.bind_all(present_values)
        parts.append(f'coalesce({column} NOT IN ({placeholders}), TRUE)')
    if holds_null:
        parts.append(f'{column} IS NOT NULL')
    return '(' + ' AND '.join(parts) + ')'


def include_list_clause(column, present_values, holds_null, binder):
    """Keep adverts whose list carries any of the values, or no value at all when null was listed."""
    parts = []
    if present_values:
        placeholders = binder.bind_all(present_values)
        parts.append(f'list_has_any({column}, [{placeholders}])')
    if holds_null:
        parts.append(f'({column} IS NULL OR len({column}) = 0)')
    return '(' + ' OR '.join(parts) + ')'


def exclude_list_clause(column, present_values, holds_null, binder):
    """Drop adverts whose list carries any of the values, or no value at all when null was listed."""
    parts = []
    if present_values:
        placeholders = binder.bind_all(present_values)
        parts.append(f'NOT coalesce(list_has_any({column}, [{placeholders}]), FALSE)')
    if holds_null:
        parts.append(f'({column} IS NOT NULL AND len({column}) > 0)')
    return '(' + ' AND '.join(parts) + ')'


def key_clause(key, values, is_include, binder, affiliation_group):
    """Compile one key and its value list, from an include or an exclude map."""
    filter_key = check_filter_key(key)
    check_value_types(filter_key, values)

    # An empty list would silently match everything or nothing, so it is refused
    if len(values) == 0:
        raise ValueError(f'filter key "{key}" has an empty value list')

    present_values, holds_null = split_null(values)

    # Widen affiliation ids across their merge group
    is_affiliation = key == 'affiliation_id'
    if is_affiliation and affiliation_group is not None:
        present_values = widen_affiliations(present_values, affiliation_group)

    column = f'{ADVERTS_ALIAS}.{filter_key.column}'
    is_list_column = filter_key.match == LIST_ANY_MATCH

    # Pick the clause shape for this key's column and map
    if is_list_column and is_include:
        return include_list_clause(column, present_values, holds_null, binder)
    if is_list_column:
        return exclude_list_clause(column, present_values, holds_null, binder)
    if is_include:
        return include_scalar_clause(column, present_values, holds_null, binder)
    return exclude_scalar_clause(column, present_values, holds_null, binder)


# ---------------------------------------------------------------- #
# Whole filter sets
# ---------------------------------------------------------------- #

def compile_filters(filter_sets, affiliation_group=None):
    """
    Compile filter sets into one fragment, every set and every key AND'd together.

    `filter_sets` is a list of objects with `include` and `exclude` maps (a
    `FilterSet`, or None to skip). `affiliation_group` maps one affiliation id
    to every id in its merge group; when it is None, ids are used as written.
    """
    binder = ParameterBinder()
    clauses = []

    # Each set adds its include clauses, then its exclude clauses
    for filter_set in filter_sets:
        if filter_set is None:
            continue

        for key, values in filter_set.include.items():
            clause = key_clause(key, list(values), True, binder, affiliation_group)
            clauses.append(clause)

        for key, values in filter_set.exclude.items():
            clause = key_clause(key, list(values), False, binder, affiliation_group)
            clauses.append(clause)

    # No clauses at all means no narrowing
    if not clauses:
        return CompiledFilter(sql=MATCH_EVERYTHING, parameters={})

    joined = ' AND '.join(clauses)
    return CompiledFilter(sql=joined, parameters=binder.parameters)
