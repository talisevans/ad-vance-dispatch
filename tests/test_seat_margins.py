"""
Seat margin tests: the election_margins cache is mounted from its path in both
the local and the download layouts, read into ReferenceData keyed by seat, and
shown by Top Seats' `margin_cell` as the holder and margin on a badge tinted in
the holder's colour. The Margin column hides when no margins are published.
"""

import dataclasses
import os
import shutil

import duckdb
import pytest

from dispatch.config import LOOKUPS_PREFIX
from dispatch.data.gold import (
    LOOKUP_CACHES,
    GcsGoldSource,
    LocalGoldSource,
    lookup_cache_directory,
    lookup_cache_path,
    open_gold_from,
)
from dispatch.data.reference import ReferenceData
from dispatch.sections.top_seats.top_seats import (
    Params,
    Seat,
    Spender,
    NEUTRAL_BADGE_BACKGROUND,
    NEUTRAL_BADGE_TEXT,
    MarginCell,
    format_margin_percent,
    margin_cell,
    seat_row,
)
from tests.conftest import FIXTURE_GOLD_DIRECTORY, FIXTURE_LOOKUPS_DIRECTORY
from tests.test_section_partials import render_for
from tests.test_section_top_seats import build_seats, render_top_seats, rows_by_seat


# ---------------------------------------------------------------- #
# Margin rows
# ---------------------------------------------------------------- #

# The fixture gold's seat ids for Kew, Hawthorn and Brunswick
KEW_ID = 'state_20001'
HAWTHORN_ID = 'state_20002'
BRUNSWICK_ID = 'state_20003'


# The badge colours for the fixture's Labor (#dc2626), Liberal (#1e3a8a) and Greens (#22c55e)
LABOR_BADGE = ('#f9d8d8', '#841717')
LIBERAL_BADGE = ('#d7dcea', '#122353')
GREENS_BADGE = ('#d7f5e2', '#147638')
NEUTRAL_BADGE = (NEUTRAL_BADGE_BACKGROUND, NEUTRAL_BADGE_TEXT)


def margin_row(margin_source, holder=None, opponent=None, margin_percent=None, holder_affiliation_id=None):
    """One election_margins row with the fields margin_cell reads."""
    return {
        'unique_electorate_id': KEW_ID,
        'margin_source': margin_source,
        'holder_party_name': holder,
        'holder_affiliation_id': holder_affiliation_id,
        'opponent_party_name': opponent,
        'margin_percent': margin_percent,
    }


def badge(cell):
    """A margin cell as (text, background, text colour)."""
    return (cell.text, cell.background, cell.text_colour)


# The rows written to the cache fixture: Kew twice (the later write wins) and Brunswick once
MARGIN_PARQUET_SQL = """
COPY (
    SELECT * FROM (VALUES
        ('state_20001', 'Kew', 'VIC', 'VIC', 'result', 'Labor', 'aff_labor', 'Liberal', 9.9::DOUBLE,
         TIMESTAMPTZ '2026-10-01 00:00:00+00'),
        ('state_20001', 'Kew', 'VIC', 'VIC', 'pendulum', 'Liberal', 'aff_lib_old', 'Labor', 0.4::DOUBLE,
         TIMESTAMPTZ '2026-10-07 00:00:00+00'),
        ('state_20003', 'Brunswick', 'VIC', 'VIC', 'pendulum', 'Greens', 'aff_greens', 'Labor', 7.3::DOUBLE,
         TIMESTAMPTZ '2026-10-07 00:00:00+00')
    ) AS margins(
        unique_electorate_id, electorate_name, jurisdiction, state, margin_source,
        holder_party_name, holder_affiliation_id, opponent_party_name, margin_percent, _cache_written_at
    )
) TO '{target}' (FORMAT parquet)
"""


def write_margin_parquet(directory):
    """Write the margin rows as one parquet fragment under a cache directory."""
    os.makedirs(directory, exist_ok=True)
    target = os.path.join(directory, 'part-0.parquet')
    connection = duckdb.connect(':memory:')
    connection.execute(MARGIN_PARQUET_SQL.format(target=target))
    connection.close()


@pytest.fixture
def lookups_with_margins(tmp_path):
    """A copy of the fixture lookups with an election_margins cache at its path."""
    lookups_directory = str(tmp_path / 'lookups')
    shutil.copytree(FIXTURE_LOOKUPS_DIRECTORY, lookups_directory)
    margins_directory = lookup_cache_directory(lookups_directory, 'election_margins')
    write_margin_parquet(margins_directory)
    return lookups_directory


@pytest.fixture
def margins_connection(lookups_with_margins):
    """An open gold connection whose lookups include election margins."""
    source = LocalGoldSource(FIXTURE_GOLD_DIRECTORY, lookups_with_margins)
    connection = open_gold_from(source)
    yield connection
    connection.close()


# ---------------------------------------------------------------- #
# margin_cell
# ---------------------------------------------------------------- #

def test_pendulum_margin_shows_the_holder_on_its_colour(reference):
    """A pendulum row reads holder and margin only, on a badge tinted in the holder's colour."""
    row = margin_row('pendulum', 'Greens', 'Labor', 7.3, holder_affiliation_id='aff_greens')
    assert badge(margin_cell(reference, row)) == ('Greens 7.3%', *GREENS_BADGE)


def test_result_margin_reads_the_same_way(reference):
    """A result row reads the same way as a pendulum row, with no opponent named."""
    row = margin_row('result', 'Labor', 'Greens', 15.9, holder_affiliation_id='aff_labor')
    assert badge(margin_cell(reference, row)) == ('Labor 15.9%', *LABOR_BADGE)


def test_badge_is_a_tint_and_a_shade_of_the_holder_colour(reference):
    """Labor's #dc2626 gives a #f9d8d8 background (82% towards white) and #841717 text (40% towards black)."""
    row = margin_row('result', 'Labor', 'Liberal', 2.0, holder_affiliation_id='aff_labor')
    cell = margin_cell(reference, row)
    assert cell.is_badge is True
    assert cell.background == '#f9d8d8'
    assert cell.text_colour == '#841717'


def test_merged_holder_takes_its_survivor_name_and_colour(reference):
    """A holder recorded under aff_lib_old shows as Liberal, in Liberal's colours."""
    row = margin_row('pendulum', 'Liberal Party (Victorian Division)', 'Labor', 4.0,
                     holder_affiliation_id='aff_lib_old')
    assert badge(margin_cell(reference, row)) == ('Liberal 4.0%', *LIBERAL_BADGE)


def test_holder_without_an_affiliation_gets_a_slate_badge(reference):
    """No holder_affiliation_id: the party name from the cache, on the neutral slate badge."""
    row = margin_row('result', 'Independent', 'Liberal', 3.2)
    assert badge(margin_cell(reference, row)) == ('Independent 3.2%', *NEUTRAL_BADGE)


def test_holder_with_an_unknown_affiliation_gets_a_slate_badge(reference):
    """An id the reference data does not hold: the party name from the cache, on slate."""
    row = margin_row('result', 'Animal Justice', 'Labor', 5.5, holder_affiliation_id='aff_not_held')
    assert badge(margin_cell(reference, row)) == ('Animal Justice 5.5%', *NEUTRAL_BADGE)


def test_multi_member_seat_reads_multi_member_without_a_badge(reference):
    """A TAS or ACT seat reads multi-member as plain text, with no badge colours."""
    cell = margin_cell(reference, margin_row('multi_member'))
    assert badge(cell) == ('multi-member', None, None)
    assert cell.is_badge is False


def test_none_source_reads_blank(reference):
    """A seat with no pendulum and no result reads blank."""
    assert margin_cell(reference, margin_row('none')) == MarginCell()


def test_seat_missing_from_the_lookup_reads_blank(reference):
    """No row at all reads blank."""
    assert margin_cell(reference, None) == MarginCell()


def test_missing_part_reads_blank(reference):
    """A pendulum or result row lacking the holder or the figure reads blank; the opponent is not needed."""
    assert margin_cell(reference, margin_row('result', None, 'Labor', 2.0)) == MarginCell()
    assert margin_cell(reference, margin_row('result', '', 'Labor', 2.0)) == MarginCell()
    assert margin_cell(reference, margin_row('pendulum', 'Labor', 'Liberal', None)) == MarginCell()
    assert margin_cell(reference, margin_row('pendulum', 'Labor', 'Liberal', float('nan'))) == MarginCell()
    assert margin_cell(reference, margin_row('result', 'Labor', None, 2.0)).text == 'Labor 2.0%'


def test_two_decimals_below_one_point(reference):
    """Below 1 point the margin shows two decimal places."""
    assert margin_cell(reference, margin_row('result', 'Independent', 'Liberal', 0.01)).text == 'Independent 0.01%'
    assert margin_cell(reference, margin_row('result', 'Labor', 'Liberal', 0.5)).text == 'Labor 0.50%'
    assert margin_cell(reference, margin_row('result', 'Labor', 'Liberal', 0.99)).text == 'Labor 0.99%'


def test_one_decimal_from_one_point(reference):
    """From 1 point up the margin shows one decimal place."""
    assert margin_cell(reference, margin_row('result', 'Labor', 'Liberal', 1.0)).text == 'Labor 1.0%'
    assert margin_cell(reference, margin_row('result', 'Labor', 'Liberal', 1.04)).text == 'Labor 1.0%'
    assert margin_cell(reference, margin_row('result', 'Labor', 'Liberal', 12.36)).text == 'Labor 12.4%'


# ---------------------------------------------------------------- #
# Mounting the cache
# ---------------------------------------------------------------- #

def test_election_margins_lives_at_its_path():
    """The cache is keyed on seat and found under elections/margins, not its view name."""
    assert LOOKUP_CACHES['election_margins']['keys'] == ('unique_electorate_id',)
    assert lookup_cache_path('election_margins') == 'elections/margins'
    assert lookup_cache_path('affiliations') == 'affiliations'
    expected_directory = os.path.join('/lookups', 'elections', 'margins')
    assert lookup_cache_directory('/lookups', 'election_margins') == expected_directory


def test_reference_loads_margins_keyed_by_seat(margins_connection):
    """Each seat's newest row is held whole under its unique electorate id."""
    reference = ReferenceData.load(margins_connection)
    margins = reference.seat_margin_lookup()

    assert sorted(margins) == [KEW_ID, BRUNSWICK_ID]
    assert margins[KEW_ID]['margin_source'] == 'pendulum'
    assert margins[KEW_ID]['holder_party_name'] == 'Liberal'
    assert margins[KEW_ID]['margin_percent'] == 0.4
    assert '_cache_written_at' not in margins[KEW_ID]


def test_unpublished_margins_leave_the_lookup_empty(reference):
    """The fixture lookups hold no margins, so the view is not mounted and the lookup is None."""
    assert reference.seat_margins == {}
    assert reference.seat_margin_lookup() is None


def test_empty_margins_directory_is_not_mounted(tmp_path):
    """A margins directory with no parquet in it is skipped, not an error."""
    lookups_directory = str(tmp_path / 'lookups')
    shutil.copytree(FIXTURE_LOOKUPS_DIRECTORY, lookups_directory)
    os.makedirs(lookup_cache_directory(lookups_directory, 'election_margins'))

    connection = open_gold_from(LocalGoldSource(FIXTURE_GOLD_DIRECTORY, lookups_directory))
    reference = ReferenceData.load(connection)
    connection.close()

    assert reference.seat_margin_lookup() is None


# ---------------------------------------------------------------- #
# Downloading the cache
# ---------------------------------------------------------------- #

class FakeBlob:
    """A bucket object that writes a placeholder file when downloaded."""

    def __init__(self, name):
        """Remember the object's name."""
        self.name = name

    def download_to_filename(self, target_path):
        """Write a placeholder where the object would land."""
        with open(target_path, 'w', encoding='utf-8') as target_file:
            target_file.write(self.name)


class FakeBucket:
    """A bucket that lists the objects under a prefix and records each prefix asked for."""

    def __init__(self, object_names, listed_prefixes):
        """Remember the bucket's objects and the shared record of listed prefixes."""
        self.object_names = object_names
        self.listed_prefixes = listed_prefixes

    def list_blobs(self, prefix):
        """Every object whose name starts with the prefix."""
        self.listed_prefixes.append(prefix)
        blobs = []
        for name in self.object_names:
            if name.startswith(prefix):
                blobs.append(FakeBlob(name))
        return blobs


class FakeStorageClient:
    """A storage client over one set of object names, shared by every bucket."""

    def __init__(self, object_names):
        """Remember the objects and start an empty record of listed prefixes."""
        self.object_names = object_names
        self.listed_prefixes = []

    def bucket(self, _bucket_name):
        """A fake bucket over the same objects."""
        return FakeBucket(self.object_names, self.listed_prefixes)


def test_download_reads_margins_from_its_path(tmp_path):
    """The margins cache downloads from caches/elections/margins/ into lookups/elections/margins."""
    margins_object = f'{LOOKUPS_PREFIX}elections/margins/part-0.parquet'
    client = FakeStorageClient([margins_object])
    source = GcsGoldSource(str(tmp_path), storage_client=client)

    directories = source.prepare()

    assert f'{LOOKUPS_PREFIX}elections/margins/' in client.listed_prefixes
    assert f'{LOOKUPS_PREFIX}election_margins/' not in client.listed_prefixes
    downloaded_path = os.path.join(directories.lookups, 'elections', 'margins', 'part-0.parquet')
    assert os.path.isfile(downloaded_path)


# ---------------------------------------------------------------- #
# Name-based seat ids
# ---------------------------------------------------------------- #

# A seat id in the name-based form live gold and the margins cache both use
NAME_BASED_KEW_ID = 'state_VIC_kew'

# One margins row keyed by the name-based id
NAME_BASED_MARGIN_PARQUET_SQL = """
COPY (
    SELECT * FROM (VALUES
        ('state_VIC_kew', 'Kew', 'state', 'VIC', 'pendulum', 'Liberal', 'Labor', 3.2::DOUBLE,
         TIMESTAMPTZ '2026-10-07 00:00:00+00')
    ) AS margins(
        unique_electorate_id, electorate_name, jurisdiction, state, margin_source,
        holder_party_name, opponent_party_name, margin_percent, _cache_written_at
    )
) TO '{target}' (FORMAT parquet)
"""


def test_name_based_seat_id_joins_its_margin(tmp_path):
    """A gold seat with a name-based id finds the margins row keyed by the same id."""
    # The fixture lookups, with a margins cache keyed by the name-based id
    lookups_directory = str(tmp_path / 'lookups')
    shutil.copytree(FIXTURE_LOOKUPS_DIRECTORY, lookups_directory)
    margins_directory = lookup_cache_directory(lookups_directory, 'election_margins')
    os.makedirs(margins_directory, exist_ok=True)
    target = os.path.join(margins_directory, 'part-0.parquet')
    writer = duckdb.connect(':memory:')
    writer.execute(NAME_BASED_MARGIN_PARQUET_SQL.format(target=target))
    writer.close()

    # Load the margins through the same path a briefing uses
    source = LocalGoldSource(FIXTURE_GOLD_DIRECTORY, lookups_directory)
    connection = open_gold_from(source)
    reference = ReferenceData.load(connection)
    connection.close()
    margins = reference.seat_margin_lookup()

    # A hand-made seat row with the name-based id and one spender
    params = Params()
    spender = Spender(key='alp', name='Labor', is_unmapped=False, colour='#e53935',
                      spend={7: 100.0, 28: 400.0})
    seat = Seat(seat_id=NAME_BASED_KEW_ID, name='Kew', totals={7: 100.0, 28: 400.0},
                spenders={'alp': spender})
    largest = {7: 100.0, 28: 400.0}

    # The seat's Margin cell is filled from the row with the matching id
    row = seat_row(1, seat, params, margins, largest, reference)
    assert row['seat_id'] == NAME_BASED_KEW_ID
    assert badge(row['margin']) == ('Liberal 3.2%', *NEUTRAL_BADGE)


# ---------------------------------------------------------------- #
# Top Seats
# ---------------------------------------------------------------- #

def test_top_seats_writes_each_seats_margin(margins_connection):
    """The Margin column shows, filled from the lookup and blank for a seat it lacks."""
    reference = ReferenceData.load(margins_connection)
    result = build_seats(margins_connection, reference)
    rows = rows_by_seat(result)

    assert result.variables['show_margin'] is True
    assert badge(rows['Kew']['margin']) == ('Liberal 0.40%', *LIBERAL_BADGE)
    assert badge(rows['Brunswick']['margin']) == ('Greens 7.3%', *GREENS_BADGE)
    assert rows['Hawthorn']['margin'] == MarginCell()


def test_top_seats_hides_the_column_without_margins(gold_connection, reference):
    """With no margins published the Margin column is hidden and every margin is blank."""
    result = build_seats(gold_connection, reference)
    rows = rows_by_seat(result)

    assert result.variables['show_margin'] is False
    assert rows['Kew']['margin'] == MarginCell()


def test_margin_reaches_the_rendered_email(margins_connection):
    """The Margin heading and each seat's badge, in its tint and shade, appear in the rendered email."""
    _built, output = render_for(margins_connection, {
        'start_date': '2026-08-01',
        'end_date': '2026-11-28',
        'jurisdiction': 'state',
        'state': 'VIC',
    })
    html = output.email_html

    assert 'Margin' in html
    assert 'vs Labor' not in html
    kew_badge = (
        'background-color: #d7dcea; color: #122353; font-size: 11px; line-height: 15px; '
        'font-weight: bold;">Liberal 0.40%</span>'
    )
    assert kew_badge in html
    assert 'color: #147638; font-size: 11px; line-height: 15px; font-weight: bold;">Greens 7.3%</span>' in html


def test_multi_member_renders_as_plain_grey_text(gold_connection, reference):
    """A multi-member seat shows small grey text with no badge in the rendered partial."""
    kew_margin = margin_row('multi_member')
    with_margins = dataclasses.replace(reference, seat_margins={KEW_ID: kew_margin})
    html = render_top_seats(gold_connection, with_margins)

    assert '<span style="font-size: 11px; line-height: 15px; color: #999999;">multi-member</span>' in html
    assert 'border-radius: 4px' not in html


# ---------------------------------------------------------------- #
# Rounding shared with the API
# ---------------------------------------------------------------- #

@pytest.mark.parametrize('margin_percent, expected', [
    (2.25, '2.3'),
    (1.05, '1.1'),
    (7.35, '7.4'),
    (7.34, '7.3'),
    (12.0, '12.0'),
    (0.5, '0.50'),
    (0.01, '0.01'),
])
def test_margins_round_halves_up_like_the_api(margin_percent, expected):
    # The API's formatMarginPercent is tested against the same values
    assert format_margin_percent(margin_percent) == expected
