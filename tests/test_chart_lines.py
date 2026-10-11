"""
The cumulative line chart's end labels: which lines carry one, how long names
are cut short, how close labels are pushed apart, and that every label fits
inside the figure.
"""

import datetime

from dispatch.charts.lines import (
    ELLIPSIS,
    END_LABEL_MAXIMUM_CHARACTERS,
    LineSeries,
    draw_cumulative_figure,
    spread_positions,
    truncate_label,
)
from dispatch.charts.style import BASE_DPI, HALF_CHART_WIDTH


# ---------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------- #

# Ten weekly points from the start of August
WEEK_DATES = []
for week_number in range(10):
    WEEK_DATES.append(datetime.date(2026, 8, 2) + datetime.timedelta(days=7 * week_number))


def straight_line(final_value):
    """Ten cumulative values rising evenly from zero to the final value."""
    values = []
    for week_number in range(10):
        values.append(final_value * week_number / 9)
    return values


def drawn_labels(series_list):
    """Draw a half-width chart and return its figure and its end labels, in drawing order."""
    figure, axes = draw_cumulative_figure(WEEK_DATES, series_list, HALF_CHART_WIDTH)
    figure.canvas.draw()
    return figure, list(axes.texts)


def label_boxes(figure, labels):
    """Each label's box on the drawn figure, in display pixels."""
    renderer = figure.canvas.get_renderer()
    boxes = []
    for label in labels:
        boxes.append(label.get_window_extent(renderer))
    return boxes


# ---------------------------------------------------------------- #
# Truncation
# ---------------------------------------------------------------- #

def test_short_names_are_kept_whole():
    """A name at or under the maximum is unchanged."""
    assert truncate_label('Labor') == 'Labor'
    exactly_maximum = 'x' * END_LABEL_MAXIMUM_CHARACTERS
    assert truncate_label(exactly_maximum) == exactly_maximum


def test_long_names_end_in_an_ellipsis():
    """'Community Independents' (22 characters) is cut to 13 characters plus an ellipsis."""
    truncated = truncate_label('Community Independents')
    assert truncated == 'Community Ind' + ELLIPSIS
    assert len(truncated) == END_LABEL_MAXIMUM_CHARACTERS


def test_trailing_space_is_dropped_before_the_ellipsis():
    """A cut that lands just after a space does not leave the space before the ellipsis."""
    assert truncate_label('Liberal National Party', 9) == 'Liberal' + ELLIPSIS


# ---------------------------------------------------------------- #
# Spreading close labels
# ---------------------------------------------------------------- #

def test_labels_far_apart_stay_put():
    """Labels already a full gap apart do not move."""
    assert spread_positions([0.2, 0.8], 0.1) == [0.2, 0.8]


def test_close_labels_move_apart_evenly():
    """0.50 and 0.52 with a 0.10 gap move to 0.46 and 0.56, keeping their middle at 0.51."""
    spread = spread_positions([0.52, 0.50], 0.1)
    assert round(spread[0], 6) == 0.56
    assert round(spread[1], 6) == 0.46


def test_labels_at_the_top_stay_inside_the_plot():
    """Two labels at 0.98 and 0.97 are pushed apart and then down, so the top one sits at 1."""
    spread = spread_positions([0.98, 0.97], 0.1)
    assert round(spread[0], 6) == 1.0
    assert round(spread[1], 6) == 0.9


# ---------------------------------------------------------------- #
# Labels on the chart
# ---------------------------------------------------------------- #

def test_only_labelled_series_get_a_label_in_their_colour():
    """Labor and Liberal carry end labels in their own colours; the third line has none."""
    series_list = [
        LineSeries('Labor', '#dc2626', straight_line(8370), end_label='Labor'),
        LineSeries('Liberal', '#1e3a8a', straight_line(5580), end_label='Liberal'),
        LineSeries('Greens', '#22c55e', straight_line(850)),
    ]
    _figure, labels = drawn_labels(series_list)

    label_texts = []
    for label in labels:
        label_texts.append((label.get_text(), label.get_color()))
    assert label_texts == [('Labor', '#dc2626'), ('Liberal', '#1e3a8a')]


def test_long_label_is_truncated_on_the_chart():
    """A long name is drawn cut short with an ellipsis."""
    series_list = [
        LineSeries('Community Independents', '#f59e0b', straight_line(4000), end_label='Community Independents'),
    ]
    _figure, labels = drawn_labels(series_list)
    assert labels[0].get_text() == 'Community Ind' + ELLIPSIS


def test_labels_sit_right_of_the_last_point_and_inside_the_figure():
    """Each label starts right of its line's last point and ends inside the figure's right edge."""
    series_list = [
        LineSeries('Labor', '#dc2626', straight_line(8370), end_label='Labor'),
        LineSeries('Community Independents', '#f59e0b', straight_line(4000), end_label='Community Independents'),
    ]
    figure, labels = drawn_labels(series_list)
    axes = figure.axes[0]
    figure_width = figure.get_figwidth() * BASE_DPI

    # Where the last point sits across the figure, in display pixels
    last_point_x = axes.transData.transform((len(WEEK_DATES) - 1, 0))[0]

    for box in label_boxes(figure, labels):
        assert box.x0 > last_point_x
        assert box.x1 <= figure_width


def test_close_end_points_get_labels_that_do_not_overlap():
    """Left ends at $5,000 and Right at $4,950, nearly the same height; their labels do not overlap."""
    series_list = [
        LineSeries('Left', '#b3001b', straight_line(5000), end_label='Left'),
        LineSeries('Right', '#003cb3', straight_line(4950), end_label='Right'),
    ]
    figure, labels = drawn_labels(series_list)
    left_box, right_box = label_boxes(figure, labels)

    # The higher value's label sits wholly above the lower one's
    assert left_box.y0 >= right_box.y1


def test_no_labels_without_spend():
    """A chart with nothing to draw has only its empty message, no end labels."""
    series_list = [LineSeries('Labor', '#dc2626', [0.0] * 10, end_label='Labor')]
    _figure, labels = drawn_labels(series_list)

    label_texts = []
    for label in labels:
        label_texts.append(label.get_text())
    assert label_texts == ['No spend in this period']
