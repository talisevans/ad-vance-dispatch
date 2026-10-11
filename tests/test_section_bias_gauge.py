"""
Bias gauge figures against the hand-checked fixture totals in tests/fixtures/README.md.
"""

import struct

from dispatch.charts.gauge import GAUGE_DISPLAY_HEIGHT, GAUGE_DISPLAY_WIDTH
from dispatch.charts.style import DENSITY
from dispatch.data.reference import UNMAPPED_COLOUR
from dispatch.sections.bias_gauge import bias_gauge
from dispatch.sections.bias_gauge.bias_gauge import legend_grid
from tests.support.partial_render import render_partial
from tests.support.section_context import build_section, make_section_context


# ---------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------- #

def legend_amounts(result):
    """The legend as (bias label, amount) pairs, left to right."""
    pairs = []
    for row in result.variables['legend']:
        pairs.append((row['label'], row['amount']))
    return pairs


def headline_amounts(result):
    """The three headline totals by label."""
    amounts = {}
    for headline in result.variables['headlines']:
        amounts[headline['label']] = headline['amount']
    return amounts


def png_size(png):
    """The pixel width and height recorded in a PNG's header."""
    width, height = struct.unpack('>II', png[16:24])
    return width, height


# ---------------------------------------------------------------- #
# Victorian state record
# ---------------------------------------------------------------- #

def test_victorian_seven_day_split(gold_connection, reference):
    """
    VIC 7 days: left $1,470, centrist $1,050, unmapped $665, right $980, laid out
    left to right. Extreme left and extreme right have no spend, so the legend leaves them out.
    """
    context = make_section_context(gold_connection, reference)
    result = build_section(bias_gauge, context, {'window_days': 7})

    assert legend_amounts(result) == [
        ('left', 1470.0),
        ('centrist', 1050.0),
        ('unmapped', 665.0),
        ('right', 980.0),
    ]
    assert result.variables['total'] == 4165.0


def test_headline_totals(gold_connection, reference):
    """Left $1,470, Centre and unmapped $1,715 ($1,050 + $665), Right $980."""
    context = make_section_context(gold_connection, reference)
    result = build_section(bias_gauge, context, {'window_days': 7})

    assert headline_amounts(result) == {
        'Left': 1470.0,
        'Centre and unmapped': 1715.0,
        'Right': 980.0,
    }
    assert result.summary_lines == [
        'Statewide spend, 7 days: Left $1,470, Centre and unmapped $1,715, Right $980, total $4,165.',
    ]


def test_unmapped_sits_after_centrist_in_grey(gold_connection, reference):
    """Unmapped is placed at position 0, straight after centrist, in the neutral grey."""
    context = make_section_context(gold_connection, reference)
    result = build_section(bias_gauge, context, {'window_days': 7})

    labels = []
    for row in result.variables['legend']:
        labels.append(row['label'])
    centrist_index = labels.index('centrist')
    assert labels[centrist_index + 1] == 'unmapped'

    unmapped_row = result.variables['legend'][centrist_index + 1]
    assert unmapped_row['colour'] == UNMAPPED_COLOUR
    assert unmapped_row['name'] == 'Unmapped'


def test_government_is_dropped_even_without_the_template_filter(gold_connection, reference):
    """
    With no template filter at all, government ($1,400 over 7 days, null bias in gold)
    still stays out: unmapped remains $665, not $2,065.
    """
    context = make_section_context(gold_connection, reference, filter_sets=())
    result = build_section(bias_gauge, context, {'window_days': 7})

    amounts = dict(legend_amounts(result))
    assert amounts['unmapped'] == 665.0
    assert result.variables['total'] == 4165.0

    # The footer says so, since the template does not, and nothing is said under the chart
    assert result.scope_notes == ['Bias figures exclude government advertising.']
    assert result.notes == []


def test_no_footer_line_when_the_template_already_excludes_government(gold_connection, reference):
    """The Weekly Campaign Brief excludes government globally, so the gauge adds no footer line."""
    context = make_section_context(gold_connection, reference)
    result = build_section(bias_gauge, context, {'window_days': 7})
    assert result.scope_notes == []
    assert result.notes == []


def test_twenty_eight_day_split(gold_connection, reference):
    """VIC 28 days: left $5,330, centrist $1,800, unmapped $1,040, right $3,920."""
    context = make_section_context(gold_connection, reference)
    result = build_section(bias_gauge, context, {'window_days': 28})

    amounts = dict(legend_amounts(result))
    assert amounts['left'] == 5330.0
    assert amounts['centrist'] == 1800.0
    assert amounts['unmapped'] == 1040.0
    assert amounts['right'] == 3920.0
    assert result.variables['total'] == 12090.0
    assert result.variables['window_sentence'] == (
        'Figures reflect the 28-day window 4 September to 1 October 2026'
    )


# ---------------------------------------------------------------- #
# Federal records
# ---------------------------------------------------------------- #

def test_national_federal_gauge(gold_connection, reference):
    """Federal, no state, 7 days: $6,860 in all less $3,500 government is $3,360."""
    context = make_section_context(gold_connection, reference, jurisdiction='federal', state=None)
    result = build_section(bias_gauge, context, {'window_days': 7})

    assert headline_amounts(result) == {
        'Left': 2380.0,
        'Centre and unmapped': 140.0,
        'Right': 840.0,
    }
    assert result.variables['heading'] == 'National spend'


# ---------------------------------------------------------------- #
# The chart and the slot layout
# ---------------------------------------------------------------- #

def test_gauge_png_is_double_density_with_figures_in_alt(gold_connection, reference):
    """One gauge PNG at twice its display size, with the headline figures in its alt text."""
    context = make_section_context(gold_connection, reference)
    result = build_section(bias_gauge, context, {'window_days': 7})

    assert len(result.images) == 1
    gauge = result.images[0]
    assert gauge.name == 'gauge'
    assert png_size(gauge.png) == (GAUGE_DISPLAY_WIDTH * DENSITY, GAUGE_DISPLAY_HEIGHT * DENSITY)
    assert gauge.alt == (
        'Spend by bias over 7 days: Left $1,470, Centre and unmapped $1,715, Right $980, total $4,165.'
    )


def test_undefined_bias_follows_unmapped(reference):
    """A bias gold holds but the definitions lack is kept, straight after unmapped, at position 0."""
    spends = bias_gauge.slot_spends(reference, {'left': 10.0, 'mystery': 5.0})

    labels = []
    for spend in spends:
        labels.append(spend.label)
    unmapped_index = labels.index('unmapped')
    assert labels[unmapped_index + 1] == 'mystery'
    assert spends[unmapped_index + 1].position == 0.0

    headlines = bias_gauge.headline_totals(spends)
    assert headlines[1]['amount'] == 5.0


# ---------------------------------------------------------------- #
# The legend layout
# ---------------------------------------------------------------- #

def test_legend_grid_wraps_after_three_items():
    """Six items make two rows of three, in the same order."""
    items = ['extreme left', 'left', 'centrist', 'unmapped', 'right', 'extreme right']
    assert legend_grid(items) == [
        ['extreme left', 'left', 'centrist'],
        ['unmapped', 'right', 'extreme right'],
    ]


def test_legend_grid_with_a_short_last_row():
    """Four items make a full row and a row of one; no items make no rows."""
    assert legend_grid(['a', 'b', 'c', 'd']) == [['a', 'b', 'c'], ['d']]
    assert legend_grid([]) == []


def test_legend_renders_left_to_right(gold_connection, reference):
    """
    VIC 7 days renders two centred legend tables, three items then one, each item
    with its swatch, name, spend and share.
    """
    context = make_section_context(gold_connection, reference)
    result = build_section(bias_gauge, context, {'window_days': 7})
    html = render_partial(bias_gauge, result)

    # One centred table per legend row
    assert html.count('align="center" cellpadding="0" cellspacing="0" border="0" style="margin: 0 auto;"') == 2

    # Left's item: swatch, then name over bold spend and grey share
    left_colour = result.variables['legend'][0]['colour']
    assert f'bgcolor="{left_colour}"' in html
    expected_text = (
        'Left<br /><span style="font-weight: bold; color: #1a1a1a;">$1,470</span>&nbsp;&nbsp;'
        '<span style="color: #666666;">35%</span>'
    )
    assert expected_text in html


def test_legend_leaves_out_biases_under_one_percent():
    """Of $1,000, a $9 bias (0.9%) is left out, a $10 bias (1%) stays, and a $0 bias is left out."""
    spends = [
        bias_gauge.BiasSpend(label='left', name='Left', position=-1.0, colour='#ef4444', spend=981.0),
        bias_gauge.BiasSpend(label='hard right', name='Hard right', position=1.5, colour='#0029a3', spend=9.0),
        bias_gauge.BiasSpend(label='unmapped', name='Unmapped', position=0.0, colour='#d1d5db', spend=10.0),
        bias_gauge.BiasSpend(label='extreme right', name='Extreme right', position=2.0, colour='#1e40af', spend=0.0),
    ]
    rows = bias_gauge.legend_rows(spends, 1000.0)

    labels = []
    for row in rows:
        labels.append(row['label'])
    assert labels == ['left', 'unmapped']


def test_small_biases_still_count_in_the_headlines():
    """A bias left out of the legend still adds to its headline group."""
    spends = [
        bias_gauge.BiasSpend(label='left', name='Left', position=-1.0, colour='#ef4444', spend=995.0),
        bias_gauge.BiasSpend(label='hard right', name='Hard right', position=1.5, colour='#0029a3', spend=5.0),
    ]
    headlines = bias_gauge.headline_totals(spends)
    assert headlines[2]['amount'] == 5.0


def test_legend_rows_follow_the_slots(gold_connection, reference):
    """The grid holds the same legend items as the flat list, in the same order."""
    context = make_section_context(gold_connection, reference)
    result = build_section(bias_gauge, context, {'window_days': 7})

    flattened = []
    for legend_row in result.variables['legend_grid']:
        for item in legend_row:
            flattened.append(item['label'])
    expected = []
    for item in result.variables['legend']:
        expected.append(item['label'])
    assert flattened == expected
