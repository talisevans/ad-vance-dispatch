"""
Build the small gold and lookup parquet set the tests and fixture renders read.

    .venv/bin/python tests/fixtures/build_fixtures.py

Every advert spends a whole number of dollars every day between its first and
last date, and every weight is a round share, so each figure can be checked
by hand. `tests/fixtures/README.md` lists the key totals.

The output layout matches the API's local mirror:

    gold/<table>/year=<YYYY>/part-0.parquet
    gold/electorates/part-0.parquet
    lookups/<cache>/part-0.parquet
"""

import datetime
import os
import shutil
from dataclasses import dataclass, field

import pyarrow
import pyarrow.parquet


# ---------------------------------------------------------------- #
# Paths and fixed values
# ---------------------------------------------------------------- #

FIXTURES_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
GOLD_DIRECTORY = os.path.join(FIXTURES_DIRECTORY, 'gold')
LOOKUPS_DIRECTORY = os.path.join(FIXTURES_DIRECTORY, 'lookups')

# The day the gold set was loaded
DATA_DATE = datetime.date(2026, 10, 2)

# Impressions are always ten per dollar
IMPRESSIONS_PER_DOLLAR = 10

# When the cache rows were written; one affiliation also has an older row
CACHE_WRITTEN_AT = datetime.datetime(2026, 10, 2, 6, 0, tzinfo=datetime.timezone.utc)
OLDER_CACHE_WRITTEN_AT = datetime.datetime(2026, 6, 1, 6, 0, tzinfo=datetime.timezone.utc)


def day(text):
    """Read a `YYYY-MM-DD` string as a date."""
    return datetime.date.fromisoformat(text)


# ---------------------------------------------------------------- #
# Reference data
# ---------------------------------------------------------------- #

# Bias definitions, the same five the live cache holds
BIAS_DEFINITIONS = [
    ('extreme_left', 'extreme left', -2.0, '#991b1b'),
    ('left', 'left', -1.0, '#ef4444'),
    ('centrist', 'centrist', 0.0, '#94a3b8'),
    ('right', 'right', 1.0, '#3b82f6'),
    ('extreme_right', 'extreme right', 2.0, '#1e40af'),
]

# Affiliations: id, name, bias, stored colour, superseded by
AFFILIATIONS = [
    ('aff_labor', 'Labor', 'left', None, None),
    ('aff_liberal', 'Liberal', 'right', None, None),
    ('aff_lib_old', 'Liberal Party (Victorian Division)', 'right', None, 'aff_liberal'),
    ('aff_greens', 'Greens', 'left', None, None),
    ('aff_climate_200', 'Climate 200', 'centrist', '#0F766E', None),
    ('aff_one_nation', 'One Nation', 'extreme right', None, None),
    ('aff_ipa', 'Institute of Public Affairs', 'right', None, None),
    ('aff_vic_government', 'Victorian Government', None, None, None),
    ('aff_fed_government', 'Australian Government', None, None, None),
    ('aff_socialist_alliance', 'Socialist Alliance', 'extreme left', None, None),
]

# An older row for the Greens, which the newest-row rule must hide
STALE_AFFILIATION = ('aff_greens', 'Australian Greens (stale row)', 'left', None, None)

# Creators: id, name, classification, affiliation id
CREATORS = [
    ('c_labor_vic', 'Victorian Labor', 'political participant', 'aff_labor'),
    ('c_liberal_vic', 'Liberal Victoria', 'political participant', 'aff_liberal'),
    ('c_liberal_old', 'Liberal Victorian Division (old page)', 'political participant', 'aff_lib_old'),
    ('c_greens_vic', 'Victorian Greens', 'political participant', 'aff_greens'),
    ('c_teal_kew', 'Sophie Teal for Kew', 'political participant', 'aff_climate_200'),
    ('c_jane_smith', 'Jane Smith for Kew', 'political participant', None),
    ('c_bob_lee', 'Bob Lee Independent', 'political participant', None),
    ('c_vic_gov', 'Victorian Government', 'government', 'aff_vic_government'),
    ('c_ipa', 'Institute of Public Affairs', 'interest group', 'aff_ipa'),
    ('c_concerned', 'Concerned Citizens of Brunswick', 'interest group', None),
    ('c_labor_nsw', 'NSW Labor', 'political participant', 'aff_labor'),
    ('c_liberal_nsw', 'NSW Liberals', 'political participant', 'aff_liberal'),
    ('c_one_nation_nsw', 'One Nation NSW', 'political participant', 'aff_one_nation'),
    ('c_labor_fed', 'Australian Labor Party', 'political participant', 'aff_labor'),
    ('c_liberal_fed', 'Liberal Party of Australia', 'political participant', 'aff_liberal'),
    ('c_fed_gov', 'Australian Government', 'government', 'aff_fed_government'),
    ('c_greens_fed', 'Australian Greens', 'political participant', 'aff_greens'),
    ('c_fair_go', 'Fair Go Alliance', 'interest group', None),
]

# Seats: unique id, name, state, jurisdiction
ELECTORATES = [
    ('state_20001', 'Kew', 'VIC', 'state'),
    ('state_20002', 'Hawthorn', 'VIC', 'state'),
    ('state_20003', 'Brunswick', 'VIC', 'state'),
    ('state_10078', 'Sydney', 'NSW', 'state'),
    ('state_10084', 'Vaucluse', 'NSW', 'state'),
    ('federal_225', 'Kooyong', 'VIC', 'federal'),
    ('federal_232', 'Melbourne', 'VIC', 'federal'),
    ('federal_144', 'Wentworth', 'NSW', 'federal'),
    ('federal_141', 'Sydney', 'NSW', 'federal'),
]


# ---------------------------------------------------------------- #
# Adverts
# ---------------------------------------------------------------- #

@dataclass
class FixtureAdvert:
    """One advert: who ran it, its tone and themes, its daily spend, its dates and its weights."""
    ad_key: str
    datasource: str
    creator_id: str
    jurisdiction: str
    daily_spend: int
    first_date: datetime.date
    last_date: datetime.date
    approach: object
    themes: list
    states: dict
    seats: dict
    is_local_government_content: bool = False
    people: list = field(default_factory=list)

    @property
    def days(self):
        """How many days the advert ran, both ends included."""
        return (self.last_date - self.first_date).days + 1

    @property
    def year(self):
        """The cohort partition: the year of the first date."""
        return self.first_date.year


ADVERTS = [
    # ---------------- Victorian state adverts ----------------
    FixtureAdvert('meta_V01', 'meta', 'c_labor_vic', 'state', 100, day('2026-08-01'), day('2026-10-01'),
                  'positive', ['Health', 'Cost of Living'], {'VIC': 1.0},
                  {'state_20001': 0.5, 'state_20002': 0.3, 'state_20003': 0.2}),
    FixtureAdvert('meta_V02', 'meta', 'c_liberal_vic', 'state', 80, day('2026-08-01'), day('2026-10-01'),
                  'negative', ['Cost of Living', 'Crime'], {'VIC': 1.0},
                  {'state_20001': 0.5, 'state_20002': 0.5}),
    FixtureAdvert('meta_V03', 'meta', 'c_liberal_old', 'state', 20, day('2026-09-01'), day('2026-10-01'),
                  'compare & contrast', ['Crime'], {'VIC': 1.0},
                  {'state_20001': 1.0}),
    FixtureAdvert('meta_V04', 'meta', 'c_greens_vic', 'state', 50, day('2026-09-15'), day('2026-10-01'),
                  'positive', ['Climate'], {'VIC': 1.0},
                  {'state_20003': 1.0}),
    FixtureAdvert('meta_V05', 'meta', 'c_teal_kew', 'state', 150, day('2026-09-20'), day('2026-10-01'),
                  None, ['Climate', 'Integrity'], {'VIC': 1.0},
                  {'state_20001': 1.0}),
    FixtureAdvert('meta_V06', 'meta', 'c_jane_smith', 'state', 30, day('2026-09-25'), day('2026-10-01'),
                  'positive', ['Local Roads'], {'VIC': 1.0},
                  {'state_20001': 1.0}),
    FixtureAdvert('meta_V07', 'meta', 'c_bob_lee', 'state', 30, day('2026-09-25'), day('2026-10-01'),
                  'negative', [], {'VIC': 1.0},
                  {'state_20001': 1.0}),
    FixtureAdvert('meta_V08', 'meta', 'c_vic_gov', 'state', 200, day('2026-08-01'), day('2026-10-01'),
                  'positive', ['Health'], {'VIC': 1.0},
                  {'state_20001': 0.4, 'state_20002': 0.3, 'state_20003': 0.3}),
    FixtureAdvert('meta_V09', 'meta', 'c_ipa', 'state', 40, day('2026-09-01'), day('2026-10-01'),
                  'negative', ['Energy', 'Cost of Living'], {'VIC': 1.0},
                  {'state_20002': 1.0}),
    FixtureAdvert('google_V10', 'google', 'c_concerned', 'state', 25, day('2026-09-10'), day('2026-10-02'),
                  None, ['Housing'], {'VIC': 1.0},
                  {'state_20003': 1.0}),
    FixtureAdvert('google_V11', 'google', 'c_labor_vic', 'state', 60, day('2026-09-01'), day('2026-10-02'),
                  'positive', ['Health'], {'VIC': 1.0},
                  {'state_20001': 0.5, 'state_20003': 0.5}),
    FixtureAdvert('meta_V12', 'meta', 'c_labor_vic', 'state', 10, day('2025-12-01'), day('2026-08-31'),
                  'positive', ['Health'], {'VIC': 1.0},
                  {'state_20002': 1.0}),
    FixtureAdvert('meta_V13', 'meta', 'c_concerned', 'state', 10, day('2026-09-25'), day('2026-10-01'),
                  'positive', ['Local Roads'], {'VIC': 1.0},
                  {'state_20003': 1.0}, is_local_government_content=True),

    # ---------------- New South Wales state adverts ----------------
    FixtureAdvert('meta_N01', 'meta', 'c_labor_nsw', 'state', 70, day('2026-08-15'), day('2026-10-01'),
                  'positive', ['Housing'], {'NSW': 1.0},
                  {'state_10078': 0.6, 'state_10084': 0.4}),
    FixtureAdvert('meta_N02', 'meta', 'c_liberal_nsw', 'state', 90, day('2026-08-15'), day('2026-10-01'),
                  'negative', ['Housing', 'Crime'], {'NSW': 1.0},
                  {'state_10084': 1.0}),
    FixtureAdvert('meta_N03', 'meta', 'c_one_nation_nsw', 'state', 15, day('2026-09-01'), day('2026-10-01'),
                  'negative', ['Immigration'], {'NSW': 1.0},
                  {'state_10078': 1.0}),

    # ---------------- Federal adverts ----------------
    FixtureAdvert('meta_F01', 'meta', 'c_labor_fed', 'federal', 300, day('2026-08-01'), day('2026-10-01'),
                  'positive', ['Cost of Living'], {'VIC': 0.4, 'NSW': 0.6},
                  {'federal_225': 0.2, 'federal_232': 0.2, 'federal_144': 0.3, 'federal_141': 0.3}),
    FixtureAdvert('google_F02', 'google', 'c_liberal_fed', 'federal', 120, day('2026-09-01'), day('2026-10-02'),
                  'negative', ['Cost of Living', 'Defence'], {'VIC': 0.5, 'NSW': 0.5},
                  {'federal_225': 0.5, 'federal_144': 0.5}),
    FixtureAdvert('meta_F03', 'meta', 'c_fed_gov', 'federal', 500, day('2026-08-01'), day('2026-10-01'),
                  'positive', ['Health'], {'VIC': 0.5, 'NSW': 0.5},
                  {'federal_225': 0.25, 'federal_232': 0.25, 'federal_144': 0.25, 'federal_141': 0.25}),
    FixtureAdvert('meta_F04', 'meta', 'c_greens_fed', 'federal', 40, day('2026-09-25'), day('2026-10-01'),
                  'positive', ['Climate'], {'VIC': 1.0},
                  {'federal_232': 1.0}),
    FixtureAdvert('meta_F05', 'meta', 'c_fair_go', 'federal', 20, day('2026-09-01'), day('2026-10-01'),
                  'compare & contrast', ['Cost of Living'], {'NSW': 1.0},
                  {'federal_144': 1.0}),
]


# ---------------------------------------------------------------- #
# Lookups by id
# ---------------------------------------------------------------- #

def creators_by_id():
    """The creator rows keyed by id."""
    rows = {}
    for creator in CREATORS:
        rows[creator[0]] = creator
    return rows


def affiliations_by_id():
    """The affiliation rows keyed by id."""
    rows = {}
    for affiliation in AFFILIATIONS:
        rows[affiliation[0]] = affiliation
    return rows


# ---------------------------------------------------------------- #
# Gold tables
# ---------------------------------------------------------------- #

AD_DAILY_SCHEMA = pyarrow.schema([
    ('date', pyarrow.date32()),
    ('ad_key', pyarrow.string()),
    ('jurisdiction', pyarrow.string()),
    ('spend_avg', pyarrow.float64()),
    ('impressions_avg', pyarrow.float64()),
])

ADVERTS_SCHEMA = pyarrow.schema([
    ('ad_key', pyarrow.string()),
    ('datasource', pyarrow.string()),
    ('datasource_ad_id', pyarrow.string()),
    ('ad_type', pyarrow.string()),
    ('ad_snapshot_url', pyarrow.string()),
    ('media_gcs_uri', pyarrow.string()),
    ('ad_created_first_served', pyarrow.date32()),
    ('jurisdiction', pyarrow.string()),
    ('approach', pyarrow.string()),
    ('themes', pyarrow.list_(pyarrow.string())),
    ('people', pyarrow.list_(pyarrow.string())),
    ('creator_id', pyarrow.string()),
    ('creator_name', pyarrow.string()),
    ('creator_classification', pyarrow.string()),
    ('creator_affiliation_id', pyarrow.string()),
    ('creator_affiliation', pyarrow.string()),
    ('creator_affiliation_bias', pyarrow.string()),
    ('is_local_government_content', pyarrow.bool_()),
    ('geo_unattributed_weight', pyarrow.float64()),
    ('geo_overseas_weight', pyarrow.float64()),
    ('artificial_cutoff', pyarrow.date32()),
    ('dataDate', pyarrow.date32()),
    ('first_date', pyarrow.date32()),
    ('last_date', pyarrow.date32()),
    ('active_days', pyarrow.int64()),
    ('electorate_count', pyarrow.int64()),
    ('spend_total', pyarrow.float64()),
    ('impressions_total', pyarrow.float64()),
])

AD_GEO_SCHEMA = pyarrow.schema([
    ('ad_key', pyarrow.string()),
    ('unique_electorate_id', pyarrow.string()),
    ('weight', pyarrow.float64()),
])

AD_STATE_SCHEMA = pyarrow.schema([
    ('ad_key', pyarrow.string()),
    ('state', pyarrow.string()),
    ('weight', pyarrow.float64()),
])

AD_DEMO_SCHEMA = pyarrow.schema([
    ('ad_key', pyarrow.string()),
    ('age_range', pyarrow.string()),
    ('gender', pyarrow.string()),
    ('weight', pyarrow.float64()),
])

AD_PLATFORM_SCHEMA = pyarrow.schema([
    ('ad_key', pyarrow.string()),
    ('platform', pyarrow.string()),
    ('weight', pyarrow.float64()),
])

ELECTORATES_SCHEMA = pyarrow.schema([
    ('unique_electorate_id', pyarrow.string()),
    ('source_electorate_id', pyarrow.string()),
    ('electorate_name', pyarrow.string()),
    ('state', pyarrow.string()),
    ('jurisdiction', pyarrow.string()),
])

# How each advert's money splits across platforms
META_PLATFORMS = {'facebook': 0.7, 'instagram': 0.3}
GOOGLE_PLATFORMS = {'youtube': 1.0}

# How each advert's money splits across age and gender
DEMOGRAPHICS = [('25-34', 'female', 0.5), ('25-34', 'male', 0.5)]


def ad_daily_rows(advert):
    """One row per day the advert ran, each at its daily spend."""
    rows = []
    current = advert.first_date
    while current <= advert.last_date:
        rows.append({
            'date': current,
            'ad_key': advert.ad_key,
            'jurisdiction': advert.jurisdiction,
            'spend_avg': float(advert.daily_spend),
            'impressions_avg': float(advert.daily_spend * IMPRESSIONS_PER_DOLLAR),
        })
        current = current + datetime.timedelta(days=1)
    return rows


def advert_row(advert):
    """The advert's row, with the creator's fields denormalised as gold does."""
    creator = creators_by_id()[advert.creator_id]
    _creator_id, creator_name, classification, affiliation_id = creator

    # Gold carries the affiliation's name and bias; government and unmapped creators carry no bias
    affiliation_name = None
    bias = None
    if affiliation_id is not None:
        affiliation = affiliations_by_id()[affiliation_id]
        affiliation_name = affiliation[1]
        bias = affiliation[2]
    if classification == 'government':
        bias = None

    spend_total = float(advert.daily_spend * advert.days)
    return {
        'ad_key': advert.ad_key,
        'datasource': advert.datasource,
        'datasource_ad_id': advert.ad_key.split('_')[1],
        'ad_type': 'image',
        'ad_snapshot_url': None,
        'media_gcs_uri': None,
        'ad_created_first_served': advert.first_date,
        'jurisdiction': advert.jurisdiction,
        'approach': advert.approach,
        'themes': advert.themes,
        'people': advert.people,
        'creator_id': advert.creator_id,
        'creator_name': creator_name,
        'creator_classification': classification,
        'creator_affiliation_id': affiliation_id,
        'creator_affiliation': affiliation_name,
        'creator_affiliation_bias': bias,
        'is_local_government_content': advert.is_local_government_content,
        'geo_unattributed_weight': 0.0,
        'geo_overseas_weight': 0.0,
        'artificial_cutoff': None,
        'dataDate': DATA_DATE,
        'first_date': advert.first_date,
        'last_date': advert.last_date,
        'active_days': advert.days,
        'electorate_count': len(advert.seats),
        'spend_total': spend_total,
        'impressions_total': spend_total * IMPRESSIONS_PER_DOLLAR,
    }


def weight_rows(advert, weights, bucket_column):
    """One row per bucket the advert's money is split across."""
    rows = []
    for bucket, weight in weights.items():
        rows.append({'ad_key': advert.ad_key, bucket_column: bucket, 'weight': weight})
    return rows


def platform_rows(advert):
    """The advert's platform split."""
    platforms = META_PLATFORMS
    if advert.datasource == 'google':
        platforms = GOOGLE_PLATFORMS
    return weight_rows(advert, platforms, 'platform')


def demographic_rows(advert):
    """The advert's age and gender split."""
    rows = []
    for age_range, gender, weight in DEMOGRAPHICS:
        rows.append({'ad_key': advert.ad_key, 'age_range': age_range, 'gender': gender, 'weight': weight})
    return rows


def write_partitioned(table_name, schema, rows_by_year):
    """Write one partitioned table, one parquet file per cohort year."""
    for year, rows in sorted(rows_by_year.items()):
        directory = os.path.join(GOLD_DIRECTORY, table_name, f'year={year}')
        os.makedirs(directory, exist_ok=True)
        table = pyarrow.Table.from_pylist(rows, schema=schema)
        pyarrow.parquet.write_table(table, os.path.join(directory, 'part-0.parquet'))


def add_rows(rows_by_year, year, rows):
    """Append rows to the list for one year."""
    if year not in rows_by_year:
        rows_by_year[year] = []
    for row in rows:
        rows_by_year[year].append(row)


def write_gold():
    """Write all seven gold tables."""
    daily_by_year = {}
    adverts_by_year = {}
    geo_by_year = {}
    state_by_year = {}
    demo_by_year = {}
    platform_by_year = {}

    # Gather every advert's rows under its cohort year
    for advert in ADVERTS:
        add_rows(daily_by_year, advert.year, ad_daily_rows(advert))
        add_rows(adverts_by_year, advert.year, [advert_row(advert)])
        add_rows(geo_by_year, advert.year, weight_rows(advert, advert.seats, 'unique_electorate_id'))
        add_rows(state_by_year, advert.year, weight_rows(advert, advert.states, 'state'))
        add_rows(demo_by_year, advert.year, demographic_rows(advert))
        add_rows(platform_by_year, advert.year, platform_rows(advert))

    write_partitioned('ad_daily', AD_DAILY_SCHEMA, daily_by_year)
    write_partitioned('adverts', ADVERTS_SCHEMA, adverts_by_year)
    write_partitioned('ad_geo', AD_GEO_SCHEMA, geo_by_year)
    write_partitioned('ad_state', AD_STATE_SCHEMA, state_by_year)
    write_partitioned('ad_demo', AD_DEMO_SCHEMA, demo_by_year)
    write_partitioned('ad_platform', AD_PLATFORM_SCHEMA, platform_by_year)

    # Electorates are not partitioned
    electorate_rows = []
    for unique_id, name, state, jurisdiction in ELECTORATES:
        source_id = unique_id.split('_')[1]
        electorate_rows.append({
            'unique_electorate_id': unique_id,
            'source_electorate_id': source_id,
            'electorate_name': name,
            'state': state,
            'jurisdiction': jurisdiction,
        })
    directory = os.path.join(GOLD_DIRECTORY, 'electorates')
    os.makedirs(directory, exist_ok=True)
    table = pyarrow.Table.from_pylist(electorate_rows, schema=ELECTORATES_SCHEMA)
    pyarrow.parquet.write_table(table, os.path.join(directory, 'part-0.parquet'))


# ---------------------------------------------------------------- #
# Lookup caches
# ---------------------------------------------------------------- #

TIMESTAMP_TYPE = pyarrow.timestamp('us', tz='UTC')

AFFILIATIONS_SCHEMA = pyarrow.schema([
    ('affiliation_id', pyarrow.string()),
    ('affiliation_name', pyarrow.string()),
    ('affiliation_bias', pyarrow.string()),
    ('affiliation_last_refreshed', TIMESTAMP_TYPE),
    ('affiliation_is_manual_classification', pyarrow.bool_()),
    ('affiliation_manual_classified_at', TIMESTAMP_TYPE),
    ('affiliation_manual_classified_by', pyarrow.string()),
    ('affiliation_superseded_by', pyarrow.string()),
    ('colour', pyarrow.string()),
    ('_cache_written_at', TIMESTAMP_TYPE),
])

BIAS_DEFINITIONS_SCHEMA = pyarrow.schema([
    ('bias_id', pyarrow.string()),
    ('bias_name', pyarrow.string()),
    ('bias_position', pyarrow.float64()),
    ('bias_colour', pyarrow.string()),
    ('bias_description', pyarrow.string()),
    ('bias_example_affiliation_ids', pyarrow.list_(pyarrow.string())),
    ('bias_manual_classified_at', TIMESTAMP_TYPE),
    ('bias_manual_classified_by', pyarrow.string()),
    ('_cache_written_at', TIMESTAMP_TYPE),
])

CONTENT_CREATORS_SCHEMA = pyarrow.schema([
    ('creator_id', pyarrow.string()),
    ('creator_name', pyarrow.string()),
    ('platform', pyarrow.string()),
    ('platform_id', pyarrow.string()),
    ('creator_classification', pyarrow.string()),
    ('creator_affiliation_id', pyarrow.string()),
    ('creator_chamber', pyarrow.string()),
    ('creator_local_government_focus', pyarrow.bool_()),
    ('creator_geography_electorate', pyarrow.string()),
    ('creator_geography_state', pyarrow.string()),
    ('creator_geography_tier', pyarrow.string()),
    ('creator_leadership_role', pyarrow.string()),
    ('creator_ministry_leader_role', pyarrow.bool_()),
    ('creator_classification_confidence', pyarrow.float64()),
    ('creator_classified_by', pyarrow.string()),
    ('exclusion_reason', pyarrow.string()),
    ('superseded_by', pyarrow.string()),
    ('creator_last_refreshed', TIMESTAMP_TYPE),
    ('creator_is_manual_classification', pyarrow.bool_()),
    ('creator_manual_classified_at', TIMESTAMP_TYPE),
    ('creator_manual_classified_by', pyarrow.string()),
    ('_cache_written_at', TIMESTAMP_TYPE),
])


def affiliation_cache_row(affiliation, written_at):
    """One affiliation cache row."""
    affiliation_id, name, bias, colour, superseded_by = affiliation
    return {
        'affiliation_id': affiliation_id,
        'affiliation_name': name,
        'affiliation_bias': bias,
        'affiliation_last_refreshed': written_at,
        'affiliation_is_manual_classification': False,
        'affiliation_manual_classified_at': None,
        'affiliation_manual_classified_by': None,
        'affiliation_superseded_by': superseded_by,
        'colour': colour,
        '_cache_written_at': written_at,
    }


def write_cache(cache_name, schema, rows):
    """Write one lookup cache as a single fragment."""
    directory = os.path.join(LOOKUPS_DIRECTORY, cache_name)
    os.makedirs(directory, exist_ok=True)
    table = pyarrow.Table.from_pylist(rows, schema=schema)
    pyarrow.parquet.write_table(table, os.path.join(directory, 'part-0.parquet'))


def write_lookups():
    """Write the affiliations, bias definitions and content creators caches."""
    # Affiliations, with one stale older row the view must hide
    affiliation_rows = [affiliation_cache_row(STALE_AFFILIATION, OLDER_CACHE_WRITTEN_AT)]
    for affiliation in AFFILIATIONS:
        affiliation_rows.append(affiliation_cache_row(affiliation, CACHE_WRITTEN_AT))
    write_cache('affiliations', AFFILIATIONS_SCHEMA, affiliation_rows)

    # Bias definitions
    bias_rows = []
    for bias_id, name, position, colour in BIAS_DEFINITIONS:
        bias_rows.append({
            'bias_id': bias_id,
            'bias_name': name,
            'bias_position': position,
            'bias_colour': colour,
            'bias_description': f'The {name} bias.',
            'bias_example_affiliation_ids': [],
            'bias_manual_classified_at': None,
            'bias_manual_classified_by': None,
            '_cache_written_at': CACHE_WRITTEN_AT,
        })
    write_cache('bias_definitions', BIAS_DEFINITIONS_SCHEMA, bias_rows)

    # Content creators
    creator_rows = []
    for creator_id, name, classification, affiliation_id in CREATORS:
        creator_rows.append({
            'creator_id': creator_id,
            'creator_name': name,
            'platform': 'facebook',
            'platform_id': creator_id,
            'creator_classification': classification,
            'creator_affiliation_id': affiliation_id,
            'creator_chamber': None,
            'creator_local_government_focus': False,
            'creator_geography_electorate': None,
            'creator_geography_state': None,
            'creator_geography_tier': None,
            'creator_leadership_role': None,
            'creator_ministry_leader_role': False,
            'creator_classification_confidence': 1.0,
            'creator_classified_by': 'fixture',
            'exclusion_reason': None,
            'superseded_by': None,
            'creator_last_refreshed': CACHE_WRITTEN_AT,
            'creator_is_manual_classification': False,
            'creator_manual_classified_at': None,
            'creator_manual_classified_by': None,
            '_cache_written_at': CACHE_WRITTEN_AT,
        })
    write_cache('content_creators', CONTENT_CREATORS_SCHEMA, creator_rows)


# ---------------------------------------------------------------- #
# Entry point
# ---------------------------------------------------------------- #

def main():
    """Rebuild the fixtures from scratch."""
    for directory in (GOLD_DIRECTORY, LOOKUPS_DIRECTORY):
        if os.path.isdir(directory):
            shutil.rmtree(directory)

    write_gold()
    write_lookups()
    print(f'wrote fixtures under {FIXTURES_DIRECTORY}')


if __name__ == '__main__':
    main()
