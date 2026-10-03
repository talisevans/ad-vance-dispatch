"""
Apportioned view parity: the views Dispatch mounts must match the API's
(`AdVance-api/lib/duck.ts`), which are copied, not imported.

  1. Rebuild the API's own view test fixture and check the same figures its
     `tests/mcp/views.test.ts` asserts: meta_1 puts $150 into federal_144,
     and federal_144 receives $250 in all.
  2. When the API repository sits beside this one, compare the view SQL text
     in duck.ts with ours, so a change there fails here.
"""

import os
import re

import duckdb
import pytest

from dispatch.data.gold import APPORTIONED_VIEWS, apportioned_view_sql


# ---------------------------------------------------------------- #
# The API's fixture
# ---------------------------------------------------------------- #

API_FIXTURE_SQL = [
    'CREATE TABLE ad_daily (date DATE, ad_key VARCHAR, jurisdiction VARCHAR, '
    'spend_avg DOUBLE, impressions_avg DOUBLE, year BIGINT)',
    "INSERT INTO ad_daily VALUES "
    "(DATE '2026-04-01', 'meta_1', 'federal', 150.0, 1500.0, 2026), "
    "(DATE '2026-04-02', 'meta_1', 'federal', 150.0, 1500.0, 2026), "
    "(DATE '2026-04-01', 'meta_2', 'federal', 50.0, NULL, 2026), "
    "(DATE '2026-04-02', 'meta_2', 'federal', 50.0, NULL, 2026)",
    'CREATE TABLE ad_geo (ad_key VARCHAR, unique_electorate_id VARCHAR, weight DOUBLE, year BIGINT)',
    "INSERT INTO ad_geo VALUES ('meta_1', 'federal_144', 0.5, 2026), ('meta_1', 'federal_145', 0.3, 2026), "
    "('meta_1', 'federal_146', 0.2, 2026), ('meta_2', 'federal_144', 1.0, 2026)",
    'CREATE TABLE ad_state (ad_key VARCHAR, state VARCHAR, weight DOUBLE, year BIGINT)',
    "INSERT INTO ad_state VALUES ('meta_1', 'NSW', 0.8, 2026), ('meta_1', 'VIC', 0.2, 2026), "
    "('meta_2', 'NSW', 1.0, 2026)",
    'CREATE TABLE ad_demo (ad_key VARCHAR, age_range VARCHAR, gender VARCHAR, weight DOUBLE, year BIGINT)',
    "INSERT INTO ad_demo VALUES ('meta_1', '25-34', 'male', 0.5, 2026), "
    "('meta_1', '25-34', 'female', 0.5, 2026), ('meta_2', NULL, NULL, 1.0, 2026)",
    'CREATE TABLE ad_platform (ad_key VARCHAR, platform VARCHAR, weight DOUBLE, year BIGINT)',
    "INSERT INTO ad_platform VALUES ('meta_1', 'facebook', 0.5, 2026), "
    "('meta_1', 'instagram', 0.5, 2026), ('meta_2', 'facebook', 1.0, 2026)",
]

# The API repository, beside this one in the workspace
API_DUCK_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'AdVance-api', 'lib', 'duck.ts',
)


@pytest.fixture
def api_fixture():
    """An in-memory DuckDB holding the API's view fixture, with our views mounted."""
    connection = duckdb.connect(':memory:')
    for statement in API_FIXTURE_SQL:
        connection.execute(statement)
    for view_name in APPORTIONED_VIEWS:
        connection.execute(apportioned_view_sql(view_name))
    yield connection
    connection.close()


def single_value(connection, sql):
    """The one value a query returns."""
    return connection.execute(sql).fetchone()[0]


# ---------------------------------------------------------------- #
# Figures
# ---------------------------------------------------------------- #

def test_one_advert_into_one_seat_matches_the_api(api_fixture):
    """meta_1 spends $300 over two days, half of it into federal_144: $150."""
    value = single_value(
        api_fixture,
        "SELECT SUM(spend) FROM ad_geo_daily WHERE ad_key = 'meta_1' AND unique_electorate_id = 'federal_144'",
    )
    assert value == pytest.approx(150)


def test_seat_total_matches_the_api(api_fixture):
    """federal_144 receives $150 from meta_1 and $100 from meta_2: $250."""
    value = single_value(api_fixture, "SELECT SUM(spend) FROM ad_geo_daily WHERE unique_electorate_id = 'federal_144'")
    assert value == pytest.approx(250)


def test_every_view_sums_to_ad_daily(api_fixture):
    """Weights within an advert sum to one, so every view's total equals ad_daily's $400."""
    for view_name in APPORTIONED_VIEWS:
        value = single_value(api_fixture, f'SELECT SUM(spend) FROM {view_name}')
        assert value == pytest.approx(400)


# ---------------------------------------------------------------- #
# Text parity with duck.ts
# ---------------------------------------------------------------- #

def normalise(sql):
    """Collapse whitespace so formatting differences do not count."""
    return re.sub(r'\s+', ' ', sql).strip()


@pytest.mark.skipif(not os.path.isfile(API_DUCK_PATH), reason='AdVance-api is not beside this repository')
def test_view_sql_matches_duck_ts():
    """The view template and bucket lists in duck.ts match ours."""
    with open(API_DUCK_PATH, encoding='utf-8') as duck_file:
        source = duck_file.read()

    # The SQL template literal inside apportionedViewSql
    template_start = source.index('return `CREATE OR REPLACE VIEW ${name} AS')
    template_end = source.index('`;', template_start)
    api_template = source[template_start + len('return `'):template_end]

    # Our SQL for the geo view, with its names put back as the API's placeholders
    ours = apportioned_view_sql('ad_geo_daily')
    ours = ours.replace('ad_geo_daily', '${name}', 1)
    ours = ours.replace('w.unique_electorate_id', '${bucketColumns}')
    ours = ours.replace('JOIN ad_geo w', 'JOIN ${source} w')
    assert normalise(ours) == normalise(api_template)

    # Each view's source and buckets, as duck.ts declares them
    for view_name, definition in APPORTIONED_VIEWS.items():
        bucket_list = ', '.join(f"'{bucket}'" for bucket in definition['buckets'])
        declaration = f"{view_name}: {{ source: '{definition['source']}', buckets: [{bucket_list}] }}"
        assert declaration in source
