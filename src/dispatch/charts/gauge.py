"""
The half doughnut gauge: spend split into segments laid left to right.

The bias gauge section passes one segment per bias slot, already ordered by
position, with unmapped straight after centrist. Segments are drawn from the
left end of the arc (180 degrees) clockwise to the right end (0 degrees), each
taking a share of the half circle equal to its share of the total. The grand
total sits in the middle with a caption under it.

The chart is a PNG at twice its display size, on white (see `charts/style.py`).
"""

from dataclasses import dataclass

from matplotlib.patches import Wedge

from dispatch.charts.style import (
    INK,
    INK_MUTED,
    SMALL_FONT_SIZE,
    SURFACE,
    chart_image,
    new_figure,
)
from dispatch.formatting import format_money


# ---------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------- #

# The gauge's display size in CSS pixels
GAUGE_DISPLAY_WIDTH = 400
GAUGE_DISPLAY_HEIGHT = 210

# The arc runs from the left end to the right end of a half circle, in degrees
ARC_START_DEGREES = 180.0
ARC_SPAN_DEGREES = 180.0

# The outer radius and the ring's thickness, in data units of a 1-radius circle
OUTER_RADIUS = 1.0
RING_WIDTH = 0.38

# The drawing area in data units: a little wider than the circle, starting just under its base.
# Its height follows from the figure's shape, so one unit is the same length across and up
AXIS_HALF_WIDTH = 1.05
AXIS_BOTTOM = -0.04

# The colour of the ring when there is no spend at all
EMPTY_RING_COLOUR = '#eeeeee'

# The thin white line between segments
SEGMENT_EDGE_WIDTH = 1.0

# Where the total and its caption sit inside the ring, in data units
TOTAL_TEXT_HEIGHT = 0.22
CAPTION_TEXT_HEIGHT = 0.06

# The font size of the total in the middle, in points
TOTAL_FONT_SIZE = 17


# ---------------------------------------------------------------- #
# Inputs
# ---------------------------------------------------------------- #

@dataclass
class GaugeSegment:
    """One segment of the gauge: its label, its spend and its colour."""
    label: str
    value: float
    colour: str


# ---------------------------------------------------------------- #
# Geometry
# ---------------------------------------------------------------- #

def segment_angles(segments):
    """
    The start and end angle of each segment, left to right, in degrees.

    Returns a list of (segment, theta_start, theta_end) where theta_start is the
    smaller angle, as matplotlib's Wedge expects. Segments with no spend are left out.
    """
    total = 0.0
    for segment in segments:
        total += segment.value

    # Nothing to split when there is no spend
    if total <= 0:
        return []

    angles = []
    current_angle = ARC_START_DEGREES

    # Walk clockwise from the left end, each segment taking its share of the half circle
    for segment in segments:
        if segment.value <= 0:
            continue
        sweep = ARC_SPAN_DEGREES * segment.value / total
        end_angle = current_angle - sweep
        angles.append((segment, end_angle, current_angle))
        current_angle = end_angle
    return angles


# ---------------------------------------------------------------- #
# Drawing
# ---------------------------------------------------------------- #

def draw_ring(axes, segments):
    """Draw each segment as a wedge of the ring, or a grey empty ring when there is no spend."""
    angles = segment_angles(segments)

    # An empty ring keeps the shape when the window has no spend
    if not angles:
        empty_wedge = Wedge(
            (0, 0),
            OUTER_RADIUS,
            0,
            ARC_START_DEGREES,
            width=RING_WIDTH,
            facecolor=EMPTY_RING_COLOUR,
            edgecolor=SURFACE,
        )
        axes.add_patch(empty_wedge)
        return

    # One wedge per segment, separated by thin white edges
    for segment, theta_start, theta_end in angles:
        wedge = Wedge(
            (0, 0),
            OUTER_RADIUS,
            theta_start,
            theta_end,
            width=RING_WIDTH,
            facecolor=segment.colour,
            edgecolor=SURFACE,
            linewidth=SEGMENT_EDGE_WIDTH,
        )
        axes.add_patch(wedge)


def draw_total(axes, total, caption):
    """Write the grand total in the middle of the ring with its caption under it."""
    axes.text(
        0,
        TOTAL_TEXT_HEIGHT,
        format_money(total),
        ha='center',
        va='bottom',
        fontsize=TOTAL_FONT_SIZE,
        fontweight='bold',
        color=INK,
    )
    axes.text(
        0,
        CAPTION_TEXT_HEIGHT,
        caption.upper(),
        ha='center',
        va='bottom',
        fontsize=SMALL_FONT_SIZE,
        color=INK_MUTED,
    )


def half_doughnut_chart(name, segments, total, caption, alt):
    """
    Draw the half doughnut gauge and return it as a ChartImage.

    `segments` are GaugeSegment objects ordered left to right. `total` is the
    figure written in the middle and `caption` the line under it.
    """
    figure, axes = new_figure(GAUGE_DISPLAY_WIDTH, GAUGE_DISPLAY_HEIGHT)

    # Fill the whole figure with no axes, the height in data units matching the figure's shape
    axis_width = 2 * AXIS_HALF_WIDTH
    axis_height = axis_width * GAUGE_DISPLAY_HEIGHT / GAUGE_DISPLAY_WIDTH
    axes.set_position([0, 0, 1, 1])
    axes.set_xlim(-AXIS_HALF_WIDTH, AXIS_HALF_WIDTH)
    axes.set_ylim(AXIS_BOTTOM, AXIS_BOTTOM + axis_height)
    axes.axis('off')

    # Draw the ring, then the total inside it
    draw_ring(axes, segments)
    draw_total(axes, total, caption)

    return chart_image(name, figure, GAUGE_DISPLAY_WIDTH, GAUGE_DISPLAY_HEIGHT, alt)
