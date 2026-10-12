"""
Top Seats figures against the hand-checked fixture totals in tests/fixtures/README.md.
"""

import dataclasses

import pytest
from pydantic import ValidationError

from dispatch.models.template import FilterSet
from dispatch.sections.top_seats import top_seats
from dispatch.sections.top_seats.top_seats import MarginCell
from tests.support.partial_render import render_partial
from tests.support.section_context import (
    NO_GOVERNMENT,
    POLITICAL_PARTICIPANTS,
    build_section,
    make_section_context,
)


# ---------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------- #

def build_seats(gold_connection, reference, extra_filter=None, params=None):
    """Build Top Seats for the VIC state record with the Weekly Campaign Brief's filters."""
    filter_sets = [NO_GOVERNMENT, POLITICAL_PARTICIPANTS]
    if extra_filter is not None:
        filter_sets.append(extra_filter)
    context = make_section_context(gold_connection, reference, filter_sets=filter_sets)
    return build_section(top_seats, context, params)


def render_top_seats(gold_connection, reference):
    """Build Top Seats for the VIC state record and render its partial on its own."""
    result = build_seats(gold_connection, reference)
    return render_partial(top_seats, result)


def rows_by_seat(result):
    """The table rows keyed by seat name."""
    rows = {}
    for row in result.variables['rows']:
        rows[row['seat']] = row
    return rows


def spender_figure(spender):
    """A spender cell as (key, name, spend), or None for an empty runner-up."""
    if spender is None:
        return None
    return (spender['key'], spender['name'], spender['spend'])


def totals_by_window(row):
    """A row's totals keyed by window length."""
    totals = {}
    for total in row['totals']:
        totals[total['days']] = total['amount']
    return totals


# ---------------------------------------------------------------- #
# Seat ranking
# ---------------------------------------------------------------- #

def test_seats_rank_by_seven_day_spend(gold_connection, reference):
    """Kew $2,450, Brunswick $700, Hawthorn $490 over 7 days; $6,140, $2,250 and $1,960 over 28."""
    result = build_seats(gold_connection, reference)

    order = []
    for row in result.variables['rows']:
        order.append((row['rank'], row['seat'], totals_by_window(row)))
    assert order == [
        (1, 'Kew', {7: 2450.0, 28: 6140.0}),
        (2, 'Brunswick', {7: 700.0, 28: 2250.0}),
        (3, 'Hawthorn', {7: 490.0, 28: 1960.0}),
    ]


def test_limit_cuts_the_table(gold_connection, reference):
    """With limit 2 only Kew and Brunswick show, and the heading says so."""
    result = build_seats(gold_connection, reference, params={'limit': 2})

    seats = []
    for row in result.variables['rows']:
        seats.append(row['seat'])
    assert seats == ['Kew', 'Brunswick']
    assert result.variables['heading'] == 'Top 2 seats by spend'


# ---------------------------------------------------------------- #
# Leader and runner-up
# ---------------------------------------------------------------- #

def test_kew_leader_and_runner_up(gold_connection, reference):
    """Kew: Teals (Climate 200 merged in) lead with $1,050, Labor runs second with $560."""
    kew = rows_by_seat(build_seats(gold_connection, reference))['Kew']

    assert spender_figure(kew['leader']) == ('aff_community_independents', 'Teals', 1050.0)
    assert spender_figure(kew['runner_up']) == ('aff_labor', 'Labor', 560.0)


def test_tie_breaks_on_spender_key(gold_connection, reference):
    """Brunswick: Greens and Labor both spend $350; aff_greens sorts first, so Greens leads."""
    brunswick = rows_by_seat(build_seats(gold_connection, reference))['Brunswick']

    assert spender_figure(brunswick['leader']) == ('aff_greens', 'Greens', 350.0)
    assert spender_figure(brunswick['runner_up']) == ('aff_labor', 'Labor', 350.0)


def test_tie_order_is_stable_across_builds(gold_connection, reference):
    """Building twice gives the same Brunswick leader every time."""
    first = rows_by_seat(build_seats(gold_connection, reference))['Brunswick']
    second = rows_by_seat(build_seats(gold_connection, reference))['Brunswick']
    assert first['leader']['key'] == second['leader']['key'] == 'aff_greens'


def test_merged_affiliation_folds_into_its_survivor(gold_connection, reference):
    """Kew Liberal: $280 (aff_liberal) + $140 (aff_lib_old) = $420 over 7 days, $1,680 over 28."""
    liberal_only = FilterSet(include={'affiliation_id': ['aff_liberal']})
    result = build_seats(gold_connection, reference, extra_filter=liberal_only)
    kew = rows_by_seat(result)['Kew']

    assert spender_figure(kew['leader']) == ('aff_liberal', 'Liberal', 420.0)
    assert kew['runner_up'] is None
    assert totals_by_window(kew) == {7: 420.0, 28: 1680.0}
    assert 'runner-up none' in result.summary_lines[1]


def test_unmapped_independents_are_not_merged(gold_connection, reference):
    """
    Jane Smith and Bob Lee have no affiliation. They stay two spenders at $210
    each, keyed by creator, tied and ordered creator:c_bob_lee first.
    """
    independents = FilterSet(include={'creator_id': ['c_jane_smith', 'c_bob_lee']})
    result = build_seats(gold_connection, reference, extra_filter=independents)
    kew = rows_by_seat(result)['Kew']

    assert spender_figure(kew['leader']) == ('creator:c_bob_lee', 'Bob Lee Independent', 210.0)
    assert spender_figure(kew['runner_up']) == ('creator:c_jane_smith', 'Jane Smith for Kew', 210.0)
    assert kew['leader']['is_unmapped'] is True
    assert kew['runner_up']['is_unmapped'] is True
    assert totals_by_window(kew)[7] == 420.0


# ---------------------------------------------------------------- #
# Margin column
# ---------------------------------------------------------------- #

def test_margin_column_hidden_without_a_seat_lookup(gold_connection, reference):
    """No seat lookup is published, so the Margin column does not show."""
    result = build_seats(gold_connection, reference)
    assert reference.seat_margin_lookup() is None
    assert result.variables['show_margin'] is False


def kew_margin_reference(reference):
    """The fixture reference data with one Liberal-held margin for Kew, held under the merged aff_lib_old."""
    kew_margin = {
        'unique_electorate_id': 'state_20001',
        'margin_source': 'result',
        'holder_party_name': 'Liberal Party (Victorian Division)',
        'holder_affiliation_id': 'aff_lib_old',
        'opponent_party_name': 'Labor',
        'margin_percent': 4.0,
    }
    return dataclasses.replace(reference, seat_margins={'state_20001': kew_margin})


def test_margin_column_shows_when_a_seat_lookup_exists(gold_connection, reference):
    """Once a lookup supplies margins, the column shows a holder badge, blank for seats it lacks."""
    result = build_seats(gold_connection, kew_margin_reference(reference))
    rows = rows_by_seat(result)

    assert result.variables['show_margin'] is True
    assert rows['Kew']['margin'] == MarginCell(text='Liberal 4.0%', background='#d7dcea', text_colour='#122353')
    assert rows['Hawthorn']['margin'] == MarginCell()


def test_margin_badge_renders_in_the_partial(gold_connection, reference):
    """Kew's cell is one badge with solid hex colours and no opponent; Hawthorn's cell is empty."""
    html = render_top_seats(gold_connection, kew_margin_reference(reference))

    expected_badge = (
        '<span style="display: inline-block; padding: 2px 8px; border-radius: 4px; '
        'background-color: #d7dcea; color: #122353; font-size: 11px; line-height: 15px; '
        'font-weight: bold;">Liberal 4.0%</span>'
    )
    assert expected_badge in html
    assert html.count('border-radius: 4px') == 1
    assert 'vs Labor' not in html
    assert 'rgba' not in html


def test_phone_layout_hides_the_runner_up_and_other_windows(gold_connection, reference):
    """On a phone only the 7-day column and the leader show; the runner-up and 28-day columns hide."""
    html = render_top_seats(gold_connection, kew_margin_reference(reference))

    # Headings: the ranking window stays, the runner-up and the 28-day window hide
    assert '<td class="mobile-cell" align="right" bgcolor="#002147" style="' in html
    assert 'class="hide-mobile" align="left" bgcolor="#002147"' in html
    assert html.count('class="hide-mobile" align="right" bgcolor="#002147"') == 1

    # Each of the three seat rows hides one runner-up cell and one 28-day total
    assert html.count('class="hide-mobile" valign="top"') == 6

    # The margin cell may wrap on a phone
    assert 'class="mobile-cell mobile-wrap"' in html


# ---------------------------------------------------------------- #
# Params and plain text
# ---------------------------------------------------------------- #

def test_ranking_window_must_be_listed():
    """rank_by_window must be one of the windows."""
    with pytest.raises(ValidationError):
        top_seats.Params.model_validate({'windows': [7, 28], 'rank_by_window': 14})


def test_summary_lines(gold_connection, reference):
    """The plain-text part lists each seat with its leader and runner-up."""
    result = build_seats(gold_connection, reference)
    assert result.summary_lines == [
        'Top seats by 7-day spend:',
        '1. Kew: $2,450. Leader Teals $1,050, runner-up Labor $560.',
        '2. Brunswick: $700. Leader Greens $350, runner-up Labor $350.',
        '3. Hawthorn: $490. Leader Liberal $280, runner-up Labor $210.',
    ]


def test_federal_record_uses_federal_seats(gold_connection, reference):
    """A federal VIC record ranks Kooyong and Melbourne, never the state seats."""
    context = make_section_context(
        gold_connection,
        reference,
        jurisdiction='federal',
        state='VIC',
        filter_sets=[NO_GOVERNMENT, POLITICAL_PARTICIPANTS],
    )
    result = build_section(top_seats, context, {})

    seats = []
    for row in result.variables['rows']:
        seats.append(row['seat'])
    assert sorted(seats) == ['Kooyong', 'Melbourne']
