"""
Bias gauge figures against the hand-checked fixture totals in tests/fixtures/README.md.
"""

import struct

from dispatch.charts.gauge import GAUGE_DISPLAY_HEIGHT, GAUGE_DISPLAY_WIDTH
from dispatch.charts.style import DENSITY
from dispatch.data.reference import UNMAPPED_COLOUR
from dispatch.sections.bias_gauge import bias_gauge
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
    """VIC 7 days: left $1,470, centrist $1,050, unmapped $665, right $980, laid out left to right."""
    context = make_section_context(gold_connection, reference)
    result = build_section(bias_gauge, context, {'window_days': 7})

    assert legend_amounts(result) == [
        ('extreme left', 0.0),
        ('left', 1470.0),
        ('centrist', 1050.0),
        ('unmapped', 665.0),
        ('right', 980.0),
        ('extreme right', 0.0),
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
