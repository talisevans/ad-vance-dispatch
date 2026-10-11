"""
The cumulative line chart: one line per series, rising week by week.

The cumulative spend section draws two of these side by side (biases on the
left, affiliations on the right), each 290px wide. A series with an end label
has its name written just right of its last point, in its own colour. The
plot area narrows to fit the widest label, and labels that would collide are
pushed apart vertically. The section still puts a table of every name and
total under each chart (decision D18), so only a few lines carry labels.

The chart is a PNG at twice its display size, on white (see `charts/style.py`).
"""

from dataclasses import dataclass, field

from dispatch.charts.style import (
    BASE_DPI,
    HALF_CHART_WIDTH,
    INK_MUTED,
    POINTS_PER_INCH,
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

# The longest end label in characters; a longer name is cut short and ends in an ellipsis
END_LABEL_MAXIMUM_CHARACTERS = 14

# The character a cut-short end label ends in
ELLIPSIS = '\u2026'

# The gap between a line's last point and its end label, in points
END_LABEL_OFFSET_POINTS = 5

# The space kept clear between an end label and the figure's right edge, in display pixels
END_LABEL_EDGE_PADDING = 3

# The smallest vertical gap between two end labels' centres, as extra pixels over a label's height
END_LABEL_GAP_PADDING = 1


# ---------------------------------------------------------------- #
# Inputs
# ---------------------------------------------------------------- #

@dataclass
class LineSeries:
    """
    One line: its label, its colour and one cumulative value per point on the x axis.

    `end_label` is the text written beside the line's last point, or None for no label.
    """
    label: str
    colour: str
    values: list = field(default_factory=list)
    end_label: str | None = None


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


# ---------------------------------------------------------------- #
# End labels
# ---------------------------------------------------------------- #

def truncate_label(text, maximum_characters=END_LABEL_MAXIMUM_CHARACTERS):
    """Cut a label to the maximum length, ending it in an ellipsis when it was cut."""
    fits = len(text) <= maximum_characters
    if fits:
        return text

    # Keep one character fewer than the maximum, so the ellipsis fits inside it
    kept_text = text[:maximum_characters - 1].rstrip()
    return kept_text + ELLIPSIS


def spread_positions(positions, minimum_gap):
    """
    Push label heights apart so neighbours are at least `minimum_gap` apart.

    `positions` are heights as a fraction of the plot (0 at the bottom, 1 at the
    top). Returns the new heights in the same order as given. A pair that is
    too close moves apart evenly about its middle; the result is then kept
    inside the plot.
    """
    # Work through the labels from the lowest up
    order = sorted(range(len(positions)), key=lambda index: positions[index])
    spread = list(positions)

    # Each label sits at least one gap above the one below it
    for order_index in range(1, len(order)):
        below_index = order[order_index - 1]
        current_index = order[order_index]
        lowest_allowed = spread[below_index] + minimum_gap
        if spread[current_index] < lowest_allowed:
            overlap = lowest_allowed - spread[current_index]
            spread[below_index] -= overlap / 2
            spread[current_index] += overlap / 2

    # Keep the lowest label off the bottom, moving the whole stack up together
    if order:
        lowest_index = order[0]
        below_bottom = 0.0 - spread[lowest_index]
        if below_bottom > 0:
            for index in range(len(spread)):
                spread[index] += below_bottom

    # Keep the highest label off the top, moving the whole stack down together
    if order:
        highest_index = order[-1]
        above_top = spread[highest_index] - 1.0
        if above_top > 0:
            for index in range(len(spread)):
                spread[index] -= above_top

    return spread


def place_end_labels(axes, series_list):
    """Write each labelled series' name right of its last point, and return the label texts."""
    labelled = []
    for series in series_list:
        if series.end_label is None:
            continue
        if not series.values:
            continue
        labelled.append(series)

    if not labelled:
        return []

    # Each label's height as a fraction of the plot, from its last value
    bottom, top = axes.get_ylim()
    value_range = top - bottom
    heights = []
    for series in labelled:
        last_value = series.values[-1]
        heights.append((last_value - bottom) / value_range)

    # Write each label at its line's height, just right of the last point
    labels = []
    for series, height in zip(labelled, heights):
        last_position = len(series.values) - 1
        label = axes.annotate(
            truncate_label(series.end_label),
            xy=(last_position, height),
            xycoords=('data', 'axes fraction'),
            xytext=(END_LABEL_OFFSET_POINTS, 0),
            textcoords='offset points',
            ha='left',
            va='center',
            fontsize=SMALL_FONT_SIZE,
            fontweight='bold',
            color=series.colour,
            annotation_clip=False,
        )
        labels.append(label)

    # Measure a label's height on the drawn figure, to set the smallest gap between labels
    renderer = axes.figure.canvas.get_renderer()
    tallest_label = 0.0
    for label in labels:
        label_height = label.get_window_extent(renderer).height
        if label_height > tallest_label:
            tallest_label = label_height
    plot_height = axes.get_window_extent(renderer).height
    minimum_gap = (tallest_label + END_LABEL_GAP_PADDING) / plot_height

    # Move labels that would collide apart
    spread_heights = spread_positions(heights, minimum_gap)
    for label, series, height in zip(labels, labelled, spread_heights):
        last_position = len(series.values) - 1
        label.xy = (last_position, height)
    return labels


def widest_label_width(figure, labels):
    """The width of the widest label in display pixels."""
    renderer = figure.canvas.get_renderer()
    widest = 0.0
    for label in labels:
        label_width = label.get_window_extent(renderer).width
        if label_width > widest:
            widest = label_width
    return widest


def fit_labels_on_the_right(figure, labels, point_count):
    """Narrow the plot area so the widest end label ends just inside the figure's right edge."""
    if not labels:
        return

    # The figure's width and the room the labels need, in display pixels
    figure_width = figure.get_figwidth() * BASE_DPI
    offset_pixels = END_LABEL_OFFSET_POINTS * BASE_DPI / POINTS_PER_INCH
    label_room = offset_pixels + widest_label_width(figure, labels) + END_LABEL_EDGE_PADDING

    # How far across the plot the last point sits, given the padding either side
    last_position = point_count - 1
    x_range = last_position + 2 * X_PADDING
    last_point_share = (last_position + X_PADDING) / x_range

    # The plot width that puts the last point exactly one label's room from the edge
    left_pixels = PLOT_LEFT * figure_width
    plot_width = (figure_width - label_room - left_pixels) / last_point_share
    right = (left_pixels + plot_width) / figure_width

    # Never widen the plot past its usual right edge
    if right > PLOT_RIGHT:
        right = PLOT_RIGHT
    figure.subplots_adjust(right=right)


# ---------------------------------------------------------------- #
# The chart
# ---------------------------------------------------------------- #

def draw_cumulative_figure(dates, series_list, display_width=HALF_CHART_WIDTH):
    """
    Draw cumulative lines over a run of dates and return the matplotlib figure and axes.

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

    # Name the labelled lines at their ends, with room on the right for the names
    if has_spend and dates:
        labels = place_end_labels(axes, series_list)
        fit_labels_on_the_right(figure, labels, len(dates))

    return figure, axes


def cumulative_line_chart(name, dates, series_list, alt, display_width=HALF_CHART_WIDTH):
    """Draw cumulative lines over a run of dates and return the chart as a ChartImage."""
    figure, _axes = draw_cumulative_figure(dates, series_list, display_width)
    return chart_image(name, figure, display_width, LINE_CHART_DISPLAY_HEIGHT, alt)
