"""
Every filter key a template may name, with its kind and where it reads from.

There are two kinds of key:

  1. `select` keys keep or drop whole adverts. They compile to a WHERE clause
     over the `adverts` table and are implemented in v1.
  2. `weight` keys (age, gender, platform, electorate) narrow the money by a
     share, as ADR 0006 requires. They are registered so a template naming one
     gets a clear message, but are not implemented yet.

A template naming a key that is not here, or one that is not implemented,
fails validation with a message naming the key.
"""

from dataclasses import dataclass


# ---------------------------------------------------------------- #
# Kinds and value types
# ---------------------------------------------------------------- #

# Keeps or drops whole adverts
SELECT_KIND = 'select'

# Multiplies spend by a share from an apportioned view
WEIGHT_KIND = 'weight'

# What each key's values must be
TEXT_VALUES = 'text'
BOOLEAN_VALUES = 'boolean'

# How a key's column is matched
SCALAR_MATCH = 'scalar'
LIST_ANY_MATCH = 'list_any'


@dataclass(frozen=True)
class FilterKey:
    """One filter key: its name, kind, source, value type and whether v1 compiles it."""
    key: str
    kind: str
    source: str
    description: str
    implemented: bool
    value_type: str = TEXT_VALUES
    match: str = SCALAR_MATCH
    column: str = ''


# ---------------------------------------------------------------- #
# The registry
# ---------------------------------------------------------------- #

FILTER_KEYS = (
    FilterKey(
        key='classification',
        kind=SELECT_KIND,
        source='adverts.creator_classification',
        description='Creator classification: political participant, interest group or government.',
        implemented=True,
        column='creator_classification',
    ),
    FilterKey(
        key='affiliation_id',
        kind=SELECT_KIND,
        source='adverts.creator_affiliation_id',
        description='Affiliation ids, e.g. aff_labor. Merged affiliations keep matching.',
        implemented=True,
        column='creator_affiliation_id',
    ),
    FilterKey(
        key='bias',
        kind=SELECT_KIND,
        source='adverts.creator_affiliation_bias',
        description='Bias names as gold holds them, e.g. left, centrist, extreme right.',
        implemented=True,
        column='creator_affiliation_bias',
    ),
    FilterKey(
        key='creator_id',
        kind=SELECT_KIND,
        source='adverts.creator_id',
        description='Content creator ids.',
        implemented=True,
        column='creator_id',
    ),
    FilterKey(
        key='datasource',
        kind=SELECT_KIND,
        source='adverts.datasource',
        description='meta or google.',
        implemented=True,
        column='datasource',
    ),
    FilterKey(
        key='approach',
        kind=SELECT_KIND,
        source='adverts.approach',
        description='Tone: positive, negative, compare & contrast.',
        implemented=True,
        column='approach',
    ),
    FilterKey(
        key='theme',
        kind=SELECT_KIND,
        source='adverts.themes',
        description='Theme names in Title Case. An advert matches when it carries any of them.',
        implemented=True,
        match=LIST_ANY_MATCH,
        column='themes',
    ),
    FilterKey(
        key='is_local_government_content',
        kind=SELECT_KIND,
        source='adverts.is_local_government_content',
        description='true or false: whether the advert is council or local-government content.',
        implemented=True,
        value_type=BOOLEAN_VALUES,
        column='is_local_government_content',
    ),
    FilterKey(
        key='age_range',
        kind=WEIGHT_KIND,
        source='ad_demo',
        description='Age buckets. Narrows the money by share; shares one join with gender.',
        implemented=False,
    ),
    FilterKey(
        key='gender',
        kind=WEIGHT_KIND,
        source='ad_demo',
        description='Genders. Narrows the money by share; shares one join with age_range.',
        implemented=False,
    ),
    FilterKey(
        key='platform',
        kind=WEIGHT_KIND,
        source='ad_platform',
        description='Delivery platforms. Narrows the money by share.',
        implemented=False,
    ),
    FilterKey(
        key='electorate_id',
        kind=WEIGHT_KIND,
        source='ad_geo',
        description='unique_electorate_id values. Narrows the money by share.',
        implemented=False,
    ),
)


def filter_keys_by_name():
    """Return the registry as a map of key name to its definition."""
    keys_by_name = {}
    for filter_key in FILTER_KEYS:
        keys_by_name[filter_key.key] = filter_key
    return keys_by_name


def check_filter_key(key):
    """Return the definition of a key a template may use, raising ValueError for any other."""
    keys_by_name = filter_keys_by_name()

    # A key nobody has registered
    if key not in keys_by_name:
        known = ', '.join(sorted(keys_by_name))
        raise ValueError(f'unknown filter key "{key}". Known keys: {known}')

    # A registered key the job cannot compile yet
    filter_key = keys_by_name[key]
    if not filter_key.implemented:
        raise ValueError(
            f'filter key "{key}" is a {filter_key.kind} key and is not implemented yet'
        )
    return filter_key


def catalogue_entries():
    """Describe every key for the catalogue the MCP tools read."""
    entries = []
    for filter_key in FILTER_KEYS:
        entries.append({
            'key': filter_key.key,
            'kind': filter_key.kind,
            'source': filter_key.source,
            'description': filter_key.description,
            'implemented': filter_key.implemented,
            'value_type': filter_key.value_type,
        })
    return entries
