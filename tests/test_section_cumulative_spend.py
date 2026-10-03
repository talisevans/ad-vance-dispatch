"""
Cumulative spend figures against the hand-checked fixture totals in tests/fixtures/README.md.
"""

import datetime
import struct

from dispatch.charts.lines import LINE_CHART_DISPLAY_HEIGHT
from dispatch.charts.style import DENSITY, HALF_CHART_WIDTH
from dispatch.data.reference import OTHER_COLOUR, UNMAPPED_COLOUR
from dispatch.sections.cumulative_spend import cumulative_spend
from tests.support.section_context import build_section, make_section_context


# ---------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------- #

# Spend per Monday-to-Sunday week from 1 August to 1 October 2026, no government
WEEKLY_SPEND = [380, 1330, 1330, 1330, 1330, 1990, 2200, 2725, 3885, 2380]


def column_rows(result, title):
    """One column's table as (name, total) pairs, in the order shown."""
    for column in result.variables['columns']:
        if column['title'] != title:
            continue
        pairs = []
        for row in column['rows']:
            pairs.append((row['name'], row['total']))
        return pairs
    raise AssertionError(f'no column titled {title}')


def column_colours(result, title):
    """One column's swatch colours by row name."""
    for column in result.variables['columns']:
        if column['title'] != title:
            continue
        colours = {}
        for row in column['rows']:
            colours[row['name']] = row['colour']
        return colours
    raise AssertionError(f'no column titled {title}')


def png_size(png):
    """The pixel width and height recorded in a PNG's header."""
    width, height = struct.unpack('>II', png[16:24])
    return width, height


# ---------------------------------------------------------------- #
# The bias column
# ---------------------------------------------------------------- #

def test_bias_column_totals_highest_first(gold_connection, reference):
    """1 August to 1 October: left $9,220, right $6,820, centrist $1,800, unmapped $1,040."""
    context = make_section_context(gold_connection, reference)
    result = build_section(cumulative_spend, context, {})

    assert column_rows(result, 'By bias') == [
        ('Left', 9220.0),
        ('Right', 6820.0),
        ('Centrist', 1800.0),
        ('Unmapped', 1040.0),
    ]
    assert column_colours(result, 'By bias')['Unmapped'] == UNMAPPED_COLOUR
    assert result.variables['grand_total'] == 18880.0


def test_weekly_points_add_up_week_by_week(gold_connection, reference):
    """Ten weekly points from 2 August to 1 October whose bias lines sum to the running weekly total."""
    context = make_section_context(gold_connection, reference)
    rows = cumulative_spend.daily_spend_rows(context, context.start_date, context.window_end)
    points = cumulative_spend.week_points(context.start_date, context.window_end)

    point_dates = []
    for _week_start, point_date in points:
        point_dates.append(point_date)
    assert point_dates[0] == datetime.date(2026, 8, 2)
    assert point_dates[-1] == datetime.date(2026, 10, 1)
    assert len(point_dates) == 10

    # Add the bias lines together at each point
    lines = cumulative_spend.bias_lines(reference, rows, points)
    combined = [0.0] * len(points)
    for line in lines:
        for index, value in enumerate(line.values):
            combined[index] += value

    expected = []
    running_total = 0
    for weekly in WEEKLY_SPEND:
        running_total += weekly
        expected.append(float(running_total))
    assert combined == expected


def test_government_is_dropped_even_without_the_template_filter(gold_connection, reference):
    """With no template filter, government still stays out of both columns."""
    context = make_section_context(gold_connection, reference, filter_sets=())
    result = build_section(cumulative_spend, context, {})

    assert result.variables['grand_total'] == 18880.0
    assert dict(column_rows(result, 'By bias'))['Unmapped'] == 1040.0
    assert 'Government advertising is excluded.' in result.notes


# ---------------------------------------------------------------- #
# The affiliation column
# ---------------------------------------------------------------- #

def test_top_three_with_other_and_unmapped(gold_connection, reference):
    """
    Top 3 with merges resolved: Labor $8,370, Liberal $5,580 (with aff_lib_old),
    Climate 200 $1,800, Other (IPA + Greens) $2,090, Unmapped $1,040. Highest first.
    """
    context = make_section_context(gold_connection, reference)
    result = build_section(cumulative_spend, context, {'top_affiliations': 3})

    assert column_rows(result, 'By affiliation') == [
        ('Labor', 8370.0),
        ('Liberal', 5580.0),
        ('Other', 2090.0),
        ('Climate 200', 1800.0),
        ('Unmapped', 1040.0),
    ]
    colours = column_colours(result, 'By affiliation')
    assert colours['Other'] == OTHER_COLOUR
    assert colours['Unmapped'] == UNMAPPED_COLOUR
    assert colours['Climate 200'] == '#0f766e'


def test_default_top_eight_needs_no_other(gold_connection, reference):
    """Five affiliations fit inside the top 8, so there is no Other row."""
    context = make_section_context(gold_connection, reference)
    result = build_section(cumulative_spend, context, {})

    assert column_rows(result, 'By affiliation') == [
        ('Labor', 8370.0),
        ('Liberal', 5580.0),
        ('Climate 200', 1800.0),
        ('Institute of Public Affairs', 1240.0),
        ('Unmapped', 1040.0),
        ('Greens', 850.0),
    ]


# ---------------------------------------------------------------- #
# Charts and edge cases
# ---------------------------------------------------------------- #

def test_two_half_width_charts(gold_connection, reference):
    """Two PNGs, each shown 290px wide and saved at twice that, with totals in the alt text."""
    context = make_section_context(gold_connection, reference)
    result = build_section(cumulative_spend, context, {'top_affiliations': 3})

    names = []
    for image in result.images:
        names.append(image.name)
        assert image.display_width == HALF_CHART_WIDTH
        assert png_size(image.png) == (HALF_CHART_WIDTH * DENSITY, LINE_CHART_DISPLAY_HEIGHT * DENSITY)
    assert names == ['biases', 'affiliations']
    assert result.images[0].alt == (
        'Cumulative spend by bias, 1 August to 1 October 2026: '
        'Left $9,220, Right $6,820, Centrist $1,800, Unmapped $1,040.'
    )


def test_start_after_window_end_draws_empty_charts(gold_connection, reference):
    """A record whose start_date is after the data ends builds without spend instead of failing."""
    context = make_section_context(gold_connection, reference, start_date=datetime.date(2026, 10, 10))
    result = build_section(cumulative_spend, context, {})

    assert result.variables['grand_total'] == 0.0
    assert column_rows(result, 'By bias') == []
    assert len(result.images) == 2


def test_unknown_interval_is_refused():
    """Only weekly points exist in v1."""
    try:
        cumulative_spend.Params.model_validate({'interval': 'day'})
    except ValueError:
        return
    raise AssertionError('a daily interval was accepted')
