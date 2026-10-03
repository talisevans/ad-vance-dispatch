"""
A small section type that exists only for tests.

It adds up statewide spend in a window through the context's scoped
subquery, draws one tiny chart with the shared chart style, and returns a
note and a plain-text line, so the whole build, render and send path can be
exercised before the real section types exist.
"""

from pydantic import BaseModel, ConfigDict

from dispatch.charts.style import HALF_CHART_WIDTH, chart_image, new_figure, style_axes
from dispatch.formatting import format_money
from dispatch.sections.base import SectionResult


# ---------------------------------------------------------------- #
# The section contract
# ---------------------------------------------------------------- #

TYPE_NAME = 'probe'
DESCRIPTION = 'Test-only section: statewide spend in a window.'
RENDERS = 'One total and one tiny bar chart.'
PARTIAL = 'probe.html.j2'

# The probe chart's display height in pixels
CHART_HEIGHT = 120


class Params(BaseModel):
    """The probe's params: how many days its window covers, and whether it should fail."""

    model_config = ConfigDict(extra='forbid')

    window_days: int = 7
    fail: bool = False


# ---------------------------------------------------------------- #
# Building
# ---------------------------------------------------------------- #

def build(context, params):
    """Add up statewide spend in the window and draw it."""
    if params.fail:
        raise RuntimeError('probe section was told to fail')

    window = context.window(params.window_days)

    # Statewide spend in the window, with the template's and section's filters applied
    rows = context.query(
        f'SELECT coalesce(sum(spend), 0) AS total FROM ({context.statewide_spend_sql()}) AS scoped '
        f'WHERE scoped.date BETWEEN $window_start AND $window_end',
        {'window_start': window.start, 'window_end': window.end},
    )
    total = float(rows[0]['total'])

    # One bar for the total
    figure, axes = new_figure(HALF_CHART_WIDTH, CHART_HEIGHT)
    style_axes(axes)
    axes.bar(['total'], [total], color='#002147')
    image = chart_image('bar', figure, HALF_CHART_WIDTH, CHART_HEIGHT, f'Total {format_money(total)}')

    return SectionResult(
        variables={'total': total, 'window_sentence': window.sentence},
        images=[image],
        notes=['Probe note.'],
        summary_lines=[f'Probe total: {format_money(total)}'],
    )
