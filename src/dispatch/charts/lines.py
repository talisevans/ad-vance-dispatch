"""
The cumulative line chart: one line per series, rising week by week.

The cumulative spend section draws two of these side by side (biases on the
left, affiliations on the right), each 290px wide. Lines carry no end labels;
the section puts a table of names and totals under each chart instead
(decision D18), because labels crowd badly at half width.

The chart is a PNG at twice its display size, on white (see `charts/style.py`).
"""

from dataclasses import dataclass, field

from dispatch.charts.style import (
    HALF_CHART_WIDTH,
    INK_MUTED,
    SERIES_LINE_WIDTH,
    SMALL_FONT_SIZE,
    chart_image,
    money_axis,
    new_figure,
    style_axes,
)
from dispatch.formatting import format_short_date


# ---------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------- #

# The line chart's display height in CSS pixels
LINE_CHART_DISPLAY_HEIGHT = 200

# The most date labels the x axis shows, so they never overlap at half width
MAXIMUM_DATE_LABELS = 4

# The share of the figure the plot area takes, leaving room for tick labels
PLOT_LEFT = 0.17
PLOT_RIGHT = 0.97
PLOT_BOTTOM = 0.15
PLOT_TOP = 0.95

# The size of the dot marking each line's final value, in points
END_MARKER_SIZE = 3.5

# The space left either side of the first and last points, in points along the x axis
X_PADDING = 0.3

# The gap between the x axis and its date labels, in points
DATE_LABEL_PAD = 6

# What the chart says when there is nothing to draw
EMPTY_MESSAGE = 'No spend in this period'


# ---------------------------------------------------------------- #
# Inputs
# ---------------------------------------------------------------- #

@dataclass
class LineSeries:
    """One line: its label, its colour and one cumulative value per point on the x axis."""
    label: str
    colour: str
    values: list = field(default_factory=list)


# ---------------------------------------------------------------- #
# Axis labels
# ---------------------------------------------------------------- #

def date_label_positions(point_count):
    """
    Which points get a date label: the first, the last and evenly spaced ones between.

    Never more than MAXIMUM_DATE_LABELS, so labels stay readable at half width.
    """
    if point_count <= 0:
        return []
    if point_count <= MAXIMUM_DATE_LABELS:
        return list(range(point_count))

    # Spread the labels evenly from the first point to the last
    positions = []
    last_index = point_count - 1
    gaps = MAXIMUM_DATE_LABELS - 1
    for label_number in range(MAXIMUM_DATE_LABELS):
        position = round(label_number * last_index / gaps)
        if position not in positions:
            positions.append(position)
    return positions


def label_x_axis(axes, dates):
    """Put short date labels under a few evenly spaced points."""
    positions = date_label_positions(len(dates))
    labels = []
    for position in positions:
        labels.append(format_short_date(dates[position]))
    axes.set_xticks(positions)
    axes.set_xticklabels(labels)
    axes.tick_params(axis='x', pad=DATE_LABEL_PAD)


# ---------------------------------------------------------------- #
# Drawing
# ---------------------------------------------------------------- #

def draw_empty_message(axes):
    """Write a short message in the middle of an empty chart."""
    axes.text(
        0.5,
        0.5,
        EMPTY_MESSAGE,
        transform=axes.transAxes,
        ha='center',
        va='center',
        fontsize=SMALL_FONT_SIZE,
        color=INK_MUTED,
    )
    axes.set_yticks([])


def draw_series(axes, series_list):
    """Draw each series as a line with a dot on its final value."""
    for series in series_list:
        positions = list(range(len(series.values)))
        axes.plot(
            positions,
            series.values,
            color=series.colour,
            linewidth=SERIES_LINE_WIDTH,
            solid_joinstyle='round',
            solid_capstyle='round',
        )

        # Mark where the line ends
        if positions:
            axes.plot(
                [positions[-1]],
                [series.values[-1]],
                marker='o',
                markersize=END_MARKER_SIZE,
                color=series.colour,
            )


def cumulative_line_chart(name, dates, series_list, alt, display_width=HALF_CHART_WIDTH):
    """
    Draw cumulative lines over a run of dates and return the chart as a ChartImage.

    `dates` are the x axis points, oldest first. Each LineSeries holds one value
    per date. The y axis starts at zero and is labelled in short money.
    """
    figure, axes = new_figure(display_width, LINE_CHART_DISPLAY_HEIGHT)
    figure.subplots_adjust(left=PLOT_LEFT, right=PLOT_RIGHT, bottom=PLOT_BOTTOM, top=PLOT_TOP)
    style_axes(axes)

    # Work out whether any series has spend to draw
    has_spend = False
    for series in series_list:
        for value in series.values:
            if value > 0:
                has_spend = True

    # Draw the lines, or say there is nothing to draw
    if has_spend:
        draw_series(axes, series_list)
        money_axis(axes)
        axes.set_ylim(bottom=0)
    else:
        draw_empty_message(axes)

    label_x_axis(axes, dates)

    # Leave a little room either side of the first and last points
    if dates:
        last_position = len(dates) - 1
        axes.set_xlim(-X_PADDING, last_position + X_PADDING)

    return chart_image(name, figure, display_width, LINE_CHART_DISPLAY_HEIGHT, alt)
