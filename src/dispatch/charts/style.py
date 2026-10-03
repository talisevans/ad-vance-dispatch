"""
Shared chart style: fonts, sizes, colours, 2x density and PNG output.

Every chart in a Dispatch is a PNG attached inline (decision D1), drawn with
matplotlib's Agg backend so no display is needed. Charts are drawn at twice
their display width (580px for a 290px chart) and saved on a white
background, because some Outlook dark modes draw transparent PNGs on black.

A chart module uses these helpers in four steps:

    figure, axes = new_figure(display_width=290, display_height=200)
    style_axes(axes)
    ... draw ...
    image = chart_image('gauge', figure, 290, 200, alt='Left $12,345, Right $6,789')
"""

import io

import matplotlib

# Select the display-free backend before pyplot is imported anywhere
matplotlib.use('Agg')

import matplotlib.pyplot as pyplot  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from dispatch.formatting import format_money_short  # noqa: E402
from dispatch.sections.base import ChartImage  # noqa: E402


# ---------------------------------------------------------------- #
# Density and size
# ---------------------------------------------------------------- #

# PNGs hold this many pixels per displayed pixel
DENSITY = 2

# Pixels per inch at display size. A figure of W display pixels is W / BASE_DPI inches wide
BASE_DPI = 100

# The saved resolution: twice the display resolution
SAVE_DPI = BASE_DPI * DENSITY

# The width the email body allows, and the width of one column in a two-column row
EMAIL_WIDTH = 640
FULL_CHART_WIDTH = 580
HALF_CHART_WIDTH = 290


# ---------------------------------------------------------------- #
# Fonts
# ---------------------------------------------------------------- #

# Arial first, then the metric-compatible Liberation Sans installed in the image
FONT_FAMILY = ['Arial', 'Liberation Sans', 'DejaVu Sans']

# Font sizes in points at display size
TITLE_FONT_SIZE = 10
LABEL_FONT_SIZE = 8.5
TICK_FONT_SIZE = 8
SMALL_FONT_SIZE = 7.5


# ---------------------------------------------------------------- #
# Colours
# ---------------------------------------------------------------- #

# The brief's navy, used for rules and headings
NAVY = '#002147'

# Chart surface, ink and rules, matching the dashboard's chrome
SURFACE = '#ffffff'
INK = '#0f172a'
INK_SECONDARY = '#475569'
INK_MUTED = '#64748b'
GRIDLINE = '#e2e8f0'
AXIS = '#cbd5e1'

# Line widths in points
SERIES_LINE_WIDTH = 1.8
GRID_LINE_WIDTH = 0.6


def apply_base_style():
    """Set the fonts and colours every chart starts from."""
    matplotlib.rcParams['font.family'] = 'sans-serif'
    matplotlib.rcParams['font.sans-serif'] = FONT_FAMILY
    matplotlib.rcParams['font.size'] = LABEL_FONT_SIZE
    matplotlib.rcParams['text.color'] = INK
    matplotlib.rcParams['axes.edgecolor'] = AXIS
    matplotlib.rcParams['axes.labelcolor'] = INK_SECONDARY
    matplotlib.rcParams['xtick.color'] = INK_MUTED
    matplotlib.rcParams['ytick.color'] = INK_MUTED
    matplotlib.rcParams['xtick.labelsize'] = TICK_FONT_SIZE
    matplotlib.rcParams['ytick.labelsize'] = TICK_FONT_SIZE
    matplotlib.rcParams['figure.facecolor'] = SURFACE
    matplotlib.rcParams['axes.facecolor'] = SURFACE
    matplotlib.rcParams['savefig.facecolor'] = SURFACE


# Apply the base style once, when the module is first imported
apply_base_style()


# ---------------------------------------------------------------- #
# Figures
# ---------------------------------------------------------------- #

def new_figure(display_width, display_height):
    """A figure and axes sized in display pixels; the saved PNG is twice that size."""
    width_inches = display_width / BASE_DPI
    height_inches = display_height / BASE_DPI
    figure, axes = pyplot.subplots(figsize=(width_inches, height_inches), dpi=BASE_DPI)
    return figure, axes


def style_axes(axes):
    """Quiet the axes: no top or right spine, light horizontal gridlines behind the data."""
    axes.spines['top'].set_visible(False)
    axes.spines['right'].set_visible(False)
    axes.spines['left'].set_color(AXIS)
    axes.spines['bottom'].set_color(AXIS)

    # Horizontal gridlines only, drawn under the series
    axes.set_axisbelow(True)
    axes.grid(axis='y', color=GRIDLINE, linewidth=GRID_LINE_WIDTH)
    axes.grid(axis='x', visible=False)
    axes.tick_params(length=0)


def money_axis(axes):
    """Label the y axis in short money, as in "$45k"."""
    formatter = FuncFormatter(money_tick)
    axes.yaxis.set_major_formatter(formatter)


def money_tick(value, _position):
    """One y-axis tick label in short money."""
    return format_money_short(value)


def figure_to_png(figure):
    """Save a figure as PNG bytes at twice display density on white, and close it."""
    buffer = io.BytesIO()
    figure.savefig(
        buffer,
        format='png',
        dpi=SAVE_DPI,
        facecolor=SURFACE,
        transparent=False,
    )
    pyplot.close(figure)
    return buffer.getvalue()


def chart_image(name, figure, display_width, display_height, alt):
    """Save a figure and wrap it as a ChartImage ready for a SectionResult."""
    png = figure_to_png(figure)
    return ChartImage(
        name=name,
        png=png,
        display_width=display_width,
        display_height=display_height,
        alt=alt,
    )
