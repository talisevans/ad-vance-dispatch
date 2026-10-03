"""
The hand-checkable totals in tests/fixtures/README.md, asserted through the
SectionContext scope subqueries a section would use. If a fixture changes,
these tests and the README change together.
"""

import datetime

import pytest

from dispatch.data.as_of import compute_data_dates
from dispatch.filters.compile import compile_filters
from dispatch.models.template import FilterSet
from dispatch.sections.base import SectionContext


# ---------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------- #

WINDOW_7_START = datetime.date(2026, 9, 25)
WINDOW_28_START = datetime.date(2026, 9, 4)
WINDOW_END = datetime.date(2026, 10, 1)
CUMULATIVE_START = datetime.date(2026, 8, 1)

# The Weekly Campaign Brief's global filter
NO_GOVERNMENT = FilterSet(exclude={'classification': ['government']})


def make_context(connection, reference, jurisdiction, state, filter_sets):
    """A SectionContext over the fixtures for one scope and filter."""
    compiled = compile_filters(filter_sets, reference.affiliation_group)
    dates = compute_data_dates(connection, CUMULATIVE_START, datetime.date(2026, 11, 28))
    return SectionContext(
        connection=connection,
        record=None,
        template=None,
        section=None,
        property_values={},
        jurisdiction=jurisdiction,
        state=state,
        dates=dates,
        reference=reference,
        filter_sql=compiled.sql,
        filter_parameters=compiled.parameters,
    )


def grouped_statewide(context, group_sql, start):
    """Statewide spend from `start` to the window end, grouped by one expression."""
    rows = context.query(
        f'SELECT {group_sql} AS bucket, sum(spend) AS total '
        f'FROM ({context.statewide_spend_sql()}) AS scoped '
        f'WHERE scoped.date BETWEEN $start AND $end GROUP BY 1',
        {'start': start, 'end': WINDOW_END},
    )
    totals = {}
    for row in rows:
        totals[row['bucket']] = row['total']
    return totals


def statewide_total(context, start):
    """Statewide spend from `start` to the window end."""
    rows = context.query(
        f'SELECT coalesce(sum(spend), 0) AS total FROM ({context.statewide_spend_sql()}) AS scoped '
        f'WHERE scoped.date BETWEEN $start AND $end',
        {'start': start, 'end': WINDOW_END},
    )
    return rows[0]['total']


# ---------------------------------------------------------------- #
# Victorian state, statewide
# ---------------------------------------------------------------- #

def test_victorian_seven_day_totals(gold_connection, reference):
    """VIC state, 7 days: $5,565 in all, $4,165 without government."""
    everything = make_context(gold_connection, reference, 'state', 'VIC', [])
    no_government = make_context(gold_connection, reference, 'state', 'VIC', [NO_GOVERNMENT])
    assert statewide_total(everything, WINDOW_7_START) == pytest.approx(5565)
    assert statewide_total(no_government, WINDOW_7_START) == pytest.approx(4165)


def test_victorian_seven_day_bias(gold_connection, reference):
    """VIC state, 7 days, no government: left 1,470, centrist 1,050, unmapped 665, right 980."""
    context = make_context(gold_connection, reference, 'state', 'VIC', [NO_GOVERNMENT])
    totals = grouped_statewide(context, "coalesce(creator_affiliation_bias, 'unmapped')", WINDOW_7_START)
    assert totals == pytest.approx({'left': 1470, 'centrist': 1050, 'unmapped': 665, 'right': 980})


def test_victorian_twenty_eight_day_bias(gold_connection, reference):
    """VIC state, 28 days, no government: left 5,330, centrist 1,800, unmapped 1,040, right 3,920."""
    context = make_context(gold_connection, reference, 'state', 'VIC', [NO_GOVERNMENT])
    totals = grouped_statewide(context, "coalesce(creator_affiliation_bias, 'unmapped')", WINDOW_28_START)
    assert totals == pytest.approx({'left': 5330, 'centrist': 1800, 'unmapped': 1040, 'right': 3920})


def test_victorian_cumulative_by_affiliation(gold_connection, reference):
    """VIC state, 1 August to 1 October, no government, by affiliation id as gold holds it."""
    context = make_context(gold_connection, reference, 'state', 'VIC', [NO_GOVERNMENT])
    totals = grouped_statewide(context, "coalesce(creator_affiliation_id, '(none)')", CUMULATIVE_START)
    assert totals == pytest.approx({
        'aff_labor': 8370,
        'aff_liberal': 4960,
        'aff_climate_200': 1800,
        'aff_ipa': 1240,
        '(none)': 1040,
        'aff_greens': 850,
        'aff_lib_old': 620,
    })


def test_new_south_wales_state_totals(gold_connection, reference):
    """NSW state, no government: 7 days $1,225, 28 days $4,900."""
    context = make_context(gold_connection, reference, 'state', 'NSW', [NO_GOVERNMENT])
    assert statewide_total(context, WINDOW_7_START) == pytest.approx(1225)
    assert statewide_total(context, WINDOW_28_START) == pytest.approx(4900)


def test_federal_national_and_victorian_totals(gold_connection, reference):
    """Federal, 7 days: national $6,860 in all; the Victorian share is $3,290."""
    national = make_context(gold_connection, reference, 'federal', None, [])
    victoria = make_context(gold_connection, reference, 'federal', 'VIC', [])
    assert statewide_total(national, WINDOW_7_START) == pytest.approx(6860)
    assert statewide_total(victoria, WINDOW_7_START) == pytest.approx(3290)


# ---------------------------------------------------------------- #
# Victorian state, seats
# ---------------------------------------------------------------- #

def test_victorian_seat_spenders(gold_connection, reference):
    """VIC seats, 7 days, political participants: Kew, Brunswick (a tie) and Hawthorn."""
    participants = FilterSet(include={'classification': ['political participant']})
    context = make_context(gold_connection, reference, 'state', 'VIC', [NO_GOVERNMENT, participants])
    rows = context.query(
        f"SELECT electorate_name, coalesce(creator_affiliation_id, 'creator:' || creator_id) AS spender, "
        f'sum(spend) AS total FROM ({context.seat_spend_sql()}) AS scoped '
        f'WHERE scoped.date BETWEEN $start AND $end GROUP BY 1, 2',
        {'start': WINDOW_7_START, 'end': WINDOW_END},
    )
    totals = {}
    for row in rows:
        totals[(row['electorate_name'], row['spender'])] = row['total']

    assert totals == pytest.approx({
        ('Kew', 'aff_climate_200'): 1050,
        ('Kew', 'aff_labor'): 560,
        ('Kew', 'aff_liberal'): 280,
        ('Kew', 'aff_lib_old'): 140,
        ('Kew', 'creator:c_jane_smith'): 210,
        ('Kew', 'creator:c_bob_lee'): 210,
        ('Brunswick', 'aff_greens'): 350,
        ('Brunswick', 'aff_labor'): 350,
        ('Hawthorn', 'aff_liberal'): 280,
        ('Hawthorn', 'aff_labor'): 210,
    })


def test_seat_scope_stays_in_jurisdiction(gold_connection, reference):
    """A VIC state record never sees federal seats such as Kooyong."""
    context = make_context(gold_connection, reference, 'state', 'VIC', [])
    rows = context.query(f'SELECT DISTINCT electorate_name FROM ({context.seat_spend_sql()}) AS scoped')
    names = set()
    for row in rows:
        names.add(row['electorate_name'])
    assert names == {'Kew', 'Hawthorn', 'Brunswick'}


def test_query_refuses_a_missing_parameter(gold_connection, reference):
    """A query naming a parameter nobody supplies fails clearly."""
    context = make_context(gold_connection, reference, 'state', 'VIC', [])
    with pytest.raises(KeyError):
        context.query('SELECT $nobody_supplies_this AS value')
