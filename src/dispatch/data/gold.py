"""
Open gold in DuckDB: find the parquet, mount the views, hand back a connection.

The work runs in this order:

  1. Decide where the parquet comes from. A local directory (an argument, or
     the `DISPATCH_GOLD_DIR` and `DISPATCH_LOOKUPS_DIR` environment variables)
     is read in place; otherwise the seven gold tables and three lookup caches
     are downloaded from their buckets.
  2. Mount one view per gold table over `read_parquet`, recovering the cohort
     `year` from the hive directory names.
  3. Mount the pre-apportioned views, copied from `AdVance-api/lib/duck.ts`.
  4. Mount the lookup caches, newest row per key, internal columns hidden.

Local layout, the same as the API's mirror under `/tmp/advance-gold`:

    <gold>/<table>/year=<YYYY>/*.parquet     six partitioned tables
    <gold>/electorates/*.parquet             electorates, not partitioned
    <lookups>/<cache>/**/*.parquet           affiliations, bias_definitions, content_creators

When only the gold directory is given, lookups default to `<gold>/lookups`.
"""

import os
from dataclasses import dataclass

import duckdb

from dispatch.config import (
    DEFAULT_DOWNLOAD_DIRECTORY,
    DOWNLOAD_DIRECTORY_VARIABLE,
    GOLD_BUCKET,
    GOLD_DIRECTORY_VARIABLE,
    LOOKUPS_BUCKET,
    LOOKUPS_DIRECTORY_VARIABLE,
    LOOKUPS_PREFIX,
    PROJECT_ID,
    environment_value,
)


# ---------------------------------------------------------------- #
# The seven gold tables
# ---------------------------------------------------------------- #

GOLD_TABLES = (
    'ad_daily',
    'adverts',
    'ad_geo',
    'ad_state',
    'ad_demo',
    'ad_platform',
    'electorates',
)

# Every table but electorates is hive-partitioned on the advert's cohort year
UNPARTITIONED_TABLES = ('electorates',)

# The loader's own scratch space in the gold bucket, never the published set
GOLD_STAGING_PREFIX = 'staging/'


# ---------------------------------------------------------------- #
# The pre-apportioned views (copied from AdVance-api/lib/duck.ts)
# ---------------------------------------------------------------- #

# One view per weight table. Each joins ad_daily and multiplies by weight in the
# same expression, so SUM(spend) over the view is correct by construction.
APPORTIONED_VIEWS = {
    'ad_geo_daily': {'source': 'ad_geo', 'buckets': ('unique_electorate_id',)},
    'ad_state_daily': {'source': 'ad_state', 'buckets': ('state',)},
    'ad_demo_daily': {'source': 'ad_demo', 'buckets': ('age_range', 'gender')},
    'ad_platform_daily': {'source': 'ad_platform', 'buckets': ('platform',)},
}


def apportioned_view_sql(name):
    """The CREATE VIEW for one pre-apportioned view, the same SQL the API runs."""
    definition = APPORTIONED_VIEWS[name]

    # Qualify each bucket column with the weight table's alias
    bucket_columns = []
    for bucket in definition['buckets']:
        bucket_columns.append(f'w.{bucket}')
    bucket_list = ', '.join(bucket_columns)

    return (
        f'CREATE OR REPLACE VIEW {name} AS\n'
        f'SELECT d.ad_key, d.date, d.jurisdiction, d.year, {bucket_list}, w.weight,\n'
        f'       d.spend_avg * w.weight AS spend,\n'
        f'       d.impressions_avg * w.weight AS impressions\n'
        f'FROM ad_daily d JOIN {definition["source"]} w USING (ad_key, year)'
    )


# ---------------------------------------------------------------- #
# The lookup caches
# ---------------------------------------------------------------- #

# The column every cache fragment carries, recording when the row was written
WRITTEN_AT_COLUMN = '_cache_written_at'

# The caches Dispatch reads: their key columns and the columns kept hidden
LOOKUP_CACHES = {
    'affiliations': {
        'keys': ('affiliation_id',),
        'hidden': ('affiliation_manual_classified_by',),
    },
    'bias_definitions': {
        'keys': ('bias_id',),
        'hidden': ('bias_manual_classified_by',),
    },
    'content_creators': {
        'keys': ('creator_id',),
        'hidden': ('creator_manual_classified_by',),
    },
}


def lookup_view_sql(name, directory):
    """The CREATE VIEW for one cache: newest row per key, internal columns dropped."""
    cache = LOOKUP_CACHES[name]

    # Quote each hidden column name as a SQL string for the filter
    hidden_names = []
    for column in (WRITTEN_AT_COLUMN,) + cache['hidden']:
        hidden_names.append(f"'{column}'")
    hidden_list = ', '.join(hidden_names)
    key_list = ', '.join(cache['keys'])

    return (
        f'CREATE OR REPLACE VIEW {name} AS\n'
        f'SELECT COLUMNS(lambda c: c NOT IN ({hidden_list}))\n'
        f"FROM read_parquet('{directory}/**/*.parquet', union_by_name = true)\n"
        f'QUALIFY row_number() OVER (PARTITION BY {key_list} ORDER BY {WRITTEN_AT_COLUMN} DESC) = 1'
    )


# ---------------------------------------------------------------- #
# Where the parquet comes from
# ---------------------------------------------------------------- #

@dataclass(frozen=True)
class GoldDirectories:
    """The two local directories gold and the lookup caches are read from."""
    gold: str
    lookups: str


class GoldSource:
    """Puts gold and the lookup caches on local disk and says where they are."""

    def prepare(self):
        """Make the parquet available locally and return its GoldDirectories."""
        raise NotImplementedError


class LocalGoldSource(GoldSource):
    """Gold already on local disk: the test fixtures, or a parquet mirror."""

    def __init__(self, gold_directory, lookups_directory=None):
        """Remember the directories, defaulting lookups to `<gold>/lookups`."""
        self.gold_directory = gold_directory
        self.lookups_directory = lookups_directory
        if self.lookups_directory is None:
            self.lookups_directory = os.path.join(gold_directory, 'lookups')

    def prepare(self):
        """Check the directories exist and return them unchanged."""
        for directory in (self.gold_directory, self.lookups_directory):
            if not os.path.isdir(directory):
                raise FileNotFoundError(f'gold directory not found: {directory}')
        return GoldDirectories(gold=self.gold_directory, lookups=self.lookups_directory)


class GcsGoldSource(GoldSource):
    """Downloads gold and the three lookup caches from their buckets."""

    def __init__(self, download_directory, storage_client=None):
        """Remember where to download to, and the storage client to use."""
        self.download_directory = download_directory
        self.storage_client = storage_client

    def client(self):
        """The storage client, created on first use."""
        if self.storage_client is None:
            from google.cloud import storage
            self.storage_client = storage.Client(project=PROJECT_ID)
        return self.storage_client

    def download_prefix(self, bucket_name, prefix, destination, skip_prefix=None):
        """Download every parquet object under a prefix, keeping its path relative to the prefix."""
        bucket = self.client().bucket(bucket_name)
        downloaded = 0

        for blob in bucket.list_blobs(prefix=prefix):
            # Only parquet, and never the loader's scratch space
            if not blob.name.endswith('.parquet'):
                continue
            if skip_prefix is not None and blob.name.startswith(skip_prefix):
                continue

            relative_path = blob.name[len(prefix):]
            target_path = os.path.join(destination, relative_path)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            blob.download_to_filename(target_path)
            downloaded += 1
        return downloaded

    def prepare(self):
        """Download the seven gold tables and the three caches, and return where they landed."""
        gold_directory = os.path.join(self.download_directory, 'gold')
        lookups_directory = os.path.join(self.download_directory, 'lookups')

        # The whole published gold set
        gold_count = self.download_prefix(GOLD_BUCKET, '', gold_directory, GOLD_STAGING_PREFIX)
        print(f'[gold] downloaded {gold_count} gold file(s)', flush=True)

        # Each cache under its own directory
        for cache_name in LOOKUP_CACHES:
            prefix = f'{LOOKUPS_PREFIX}{cache_name}/'
            destination = os.path.join(lookups_directory, cache_name)
            cache_count = self.download_prefix(LOOKUPS_BUCKET, prefix, destination)
            print(f'[gold] downloaded {cache_count} {cache_name} file(s)', flush=True)

        return GoldDirectories(gold=gold_directory, lookups=lookups_directory)


def resolve_gold_source(gold_directory=None, lookups_directory=None):
    """Pick a source: an explicit directory, then the environment, then the buckets."""
    # An argument wins
    if gold_directory is not None:
        return LocalGoldSource(gold_directory, lookups_directory)

    # Then the environment variables a local run sets
    gold_from_environment = environment_value(GOLD_DIRECTORY_VARIABLE)
    if gold_from_environment is not None:
        lookups_from_environment = environment_value(LOOKUPS_DIRECTORY_VARIABLE)
        return LocalGoldSource(gold_from_environment, lookups_from_environment)

    # Otherwise download into the container's scratch space
    download_directory = environment_value(DOWNLOAD_DIRECTORY_VARIABLE)
    if download_directory is None:
        download_directory = DEFAULT_DOWNLOAD_DIRECTORY
    return GcsGoldSource(download_directory)


# ---------------------------------------------------------------- #
# Mounting the views
# ---------------------------------------------------------------- #

def gold_table_sql(table, gold_directory):
    """The CREATE VIEW pointing one gold table at its parquet."""
    root = os.path.join(gold_directory, table)
    if table in UNPARTITIONED_TABLES:
        source = f"read_parquet('{root}/*.parquet')"
    else:
        source = f"read_parquet('{root}/**/*.parquet', hive_partitioning = true)"
    return f'CREATE OR REPLACE VIEW {table} AS SELECT * FROM {source}'


def open_gold(directories):
    """Open an in-memory DuckDB connection with every gold, apportioned and lookup view mounted."""
    connection = duckdb.connect(':memory:')

    # The seven gold tables
    for table in GOLD_TABLES:
        connection.execute(gold_table_sql(table, directories.gold))

    # The four pre-apportioned views
    for view_name in APPORTIONED_VIEWS:
        connection.execute(apportioned_view_sql(view_name))

    # The three lookup caches
    for cache_name in LOOKUP_CACHES:
        cache_directory = os.path.join(directories.lookups, cache_name)
        if not os.path.isdir(cache_directory):
            raise FileNotFoundError(f'lookup cache not found: {cache_directory}')
        connection.execute(lookup_view_sql(cache_name, cache_directory))

    return connection


def open_gold_from(source):
    """Prepare a source and open gold over it."""
    directories = source.prepare()
    return open_gold(directories)
