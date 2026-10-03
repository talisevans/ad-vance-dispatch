"""
The bias gauge section: spend in a window split by the bias of each creator's affiliation.

The steps run in this order:

  1. Add up spend in the window by bias, with government always dropped (D17).
  2. Lay the biases out left to right by position, unmapped straight after centrist.
  3. Total the three headline groups: Left (position below 0), Centre and
     unmapped (position 0), Right (position above 0), and the grand total.
  4. Draw the half doughnut.
  5. Return the legend rows, the headline totals, the note and the plain-text line.
"""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from dispatch.charts.gauge import GaugeSegment, half_doughnut_chart
from dispatch.data.reference import (
    UNMAPPED_BIAS_LABEL,
    UNMAPPED_COLOUR,
    UNMAPPED_POSITION,
    bias_display_name,
)
from dispatch.formatting import format_money, safe_share
from dispatch.sections.base import GOVERNMENT_CLASSIFICATION, SectionResult, government_scope_notes


# ---------------------------------------------------------------- #
# The section contract
# ---------------------------------------------------------------- #

TYPE_NAME = 'bias_gauge'
DESCRIPTION = (
    'Spend in a recent window split by the political bias of each creator\'s affiliation, '
    'with Left, Centre and unmapped, and Right totals. Government advertising is always excluded.'
)
RENDERS = 'A half doughnut of spend by bias, three headline totals and a legend table.'
PARTIAL = 'bias_gauge.html.j2'


class Params(BaseModel):
    """The bias gauge's params: how many days the window covers."""

    model_config = ConfigDict(extra='forbid')

    window_days: int = Field(default=7, ge=1)


# ---------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------- #

# The chart's name within the section, and so its Content-ID suffix
GAUGE_IMAGE_NAME = 'gauge'

# The three headline groups, and the colour each headline figure is written in
LEFT_LABEL = 'Left'
CENTRE_LABEL = 'Centre and unmapped'
RIGHT_LABEL = 'Right'
LEFT_HEADLINE_COLOUR = '#b3001b'
CENTRE_HEADLINE_COLOUR = '#555555'
RIGHT_HEADLINE_COLOUR = '#003cb3'


# ---------------------------------------------------------------- #
# Results
# ---------------------------------------------------------------- #

@dataclass
class BiasSpend:
    """Spend for one bias slot: its label as gold holds it, display name, position, colour and amount."""
    label: str
    name: str
    position: float
    colour: str
    spend: float


# ---------------------------------------------------------------- #
# Step 1: spend by bias
# ---------------------------------------------------------------- #

def spend_by_bias(context, window):
    """Spend in the window by bias label, government dropped. Null bias is keyed as unmapped."""
    rows = context.query(
        f'SELECT scoped.creator_affiliation_bias AS bias, sum(scoped.spend) AS spend\n'
        f'FROM ({context.statewide_spend_sql()}) AS scoped\n'
        f'WHERE scoped.date BETWEEN $window_start AND $window_end\n'
        f'  AND scoped.creator_classification IS DISTINCT FROM $government\n'
        f'GROUP BY 1',
        {
            'window_start': window.start,
            'window_end': window.end,
            'government': GOVERNMENT_CLASSIFICATION,
        },
    )

    totals = {}
    for row in rows:
        # Spend with no bias is unmapped
        label = row['bias']
        if label is None:
            label = UNMAPPED_BIAS_LABEL
        totals[label] = float(row['spend'])
    return totals


# ---------------------------------------------------------------- #
# Step 2: slots left to right
# ---------------------------------------------------------------- #

def slot_spends(reference, totals):
    """
    One BiasSpend per bias slot, left to right, unmapped straight after centrist.

    A bias that gold holds but the definitions do not is placed straight after
    unmapped, in the unmapped grey, so its spend is never lost.
    """
    spends = []
    placed_labels = []

    # Every defined bias and the unmapped slot, in position order
    for slot in reference.bias_slots():
        spends.append(BiasSpend(
            label=slot.label,
            name=bias_display_name(slot.label),
            position=slot.position,
            colour=slot.colour,
            spend=totals.get(slot.label, 0.0),
        ))
        placed_labels.append(slot.label)

    # Find where unmapped sits, so undefined biases can follow it
    insert_at = len(spends)
    for index, spend in enumerate(spends):
        if spend.label == UNMAPPED_BIAS_LABEL:
            insert_at = index + 1

    # Place any bias the definitions do not know
    for label in sorted(totals):
        if label in placed_labels:
            continue
        spends.insert(insert_at, BiasSpend(
            label=label,
            name=bias_display_name(label),
            position=UNMAPPED_POSITION,
            colour=UNMAPPED_COLOUR,
            spend=totals[label],
        ))
        insert_at += 1
    return spends


# ---------------------------------------------------------------- #
# Step 3: headline totals
# ---------------------------------------------------------------- #

def headline_totals(spends):
    """Total spend Left (below 0), Centre and unmapped (at 0) and Right (above 0)."""
    left_total = 0.0
    centre_total = 0.0
    right_total = 0.0

    # Each slot adds to one group by the sign of its position
    for spend in spends:
        if spend.position < 0:
            left_total += spend.spend
        elif spend.position > 0:
            right_total += spend.spend
        else:
            centre_total += spend.spend

    return [
        {'label': LEFT_LABEL, 'amount': left_total, 'colour': LEFT_HEADLINE_COLOUR, 'align': 'left'},
        {'label': CENTRE_LABEL, 'amount': centre_total, 'colour': CENTRE_HEADLINE_COLOUR, 'align': 'center'},
        {'label': RIGHT_LABEL, 'amount': right_total, 'colour': RIGHT_HEADLINE_COLOUR, 'align': 'right'},
    ]


def headline_sentence(headlines, total):
    """The headline figures in words, as in "Left $1,470, Centre and unmapped $1,715, Right $980, total $4,165"."""
    parts = []
    for headline in headlines:
        parts.append(f'{headline["label"]} {format_money(headline["amount"])}')
    parts.append(f'total {format_money(total)}')
    return ', '.join(parts)


# ---------------------------------------------------------------- #
# Step 4: the chart
# ---------------------------------------------------------------- #

def draw_gauge(spends, total, window_days, sentence):
    """Draw the half doughnut with one segment per slot, left to right."""
    segments = []
    for spend in spends:
        segments.append(GaugeSegment(label=spend.name, value=spend.spend, colour=spend.colour))

    caption = f'Total spend ({window_days} days)'
    alt = f'Spend by bias over {window_days} days: {sentence}.'
    return half_doughnut_chart(GAUGE_IMAGE_NAME, segments, total, caption, alt)


# ---------------------------------------------------------------- #
# Step 5: the section
# ---------------------------------------------------------------- #

def section_heading(context):
    """The heading: statewide when the record has a state, national otherwise."""
    if context.state is None:
        return 'National spend'
    return 'Statewide spend'


def legend_rows(spends, total):
    """One legend row per slot: swatch colour, display name, spend and share of the total."""
    rows = []
    for spend in spends:
        rows.append({
            'label': spend.label,
            'name': spend.name,
            'colour': spend.colour,
            'amount': spend.spend,
            'share': safe_share(spend.spend, total),
        })
    return rows


def build(context, params):
    """Build the bias gauge: spend by bias in the window, as a half doughnut with totals and a legend."""
    window = context.window(params.window_days)

    # Spend by bias, laid out left to right
    totals = spend_by_bias(context, window)
    spends = slot_spends(context.reference, totals)

    # The grand total and the three headline groups
    total = 0.0
    for spend in spends:
        total += spend.spend
    headlines = headline_totals(spends)
    sentence = headline_sentence(headlines, total)

    gauge = draw_gauge(spends, total, params.window_days, sentence)

    variables = {
        'heading': section_heading(context),
        'window_days': params.window_days,
        'window_sentence': window.sentence,
        'headlines': headlines,
        'total': total,
        'legend': legend_rows(spends, total),
    }
    summary = f'{section_heading(context)}, {params.window_days} days: {sentence}.'
    return SectionResult(
        variables=variables,
        images=[gauge],
        summary_lines=[summary],
        scope_notes=government_scope_notes(context, 'Bias figures'),
    )
