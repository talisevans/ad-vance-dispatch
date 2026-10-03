"""
The cumulative spend section: running totals week by week since the record's start date.

The steps run in this order:

  1. Add up spend per day by bias and by affiliation, from `start_date` to the
     window end, with government always dropped (as the bias gauge does).
  2. Split the period into Monday-to-Sunday weeks. Each point on the x axis is
     the last day of a week, or the window end for the final week.
  3. Left column: one cumulative line per bias, in bias colours, unmapped in grey.
  4. Right column: the top N affiliations by total (merged affiliations folded
     into their survivor), then Other (the rest), then Unmapped (no affiliation).
  5. Under each chart, a table of name, swatch and total, highest first (D18).
"""

import datetime
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from dispatch.charts.lines import LineSeries, cumulative_line_chart
from dispatch.data.reference import (
    OTHER_COLOUR,
    OTHER_LABEL,
    UNMAPPED_AFFILIATION_LABEL,
    UNMAPPED_BIAS_LABEL,
    UNMAPPED_COLOUR,
    bias_display_name,
)
from dispatch.formatting import format_date_range, format_long_date, format_money
from dispatch.sections.base import GOVERNMENT_CLASSIFICATION, SectionResult, government_scope_notes


# ---------------------------------------------------------------- #
# The section contract
# ---------------------------------------------------------------- #

TYPE_NAME = 'cumulative_spend'
DESCRIPTION = (
    'Running spend totals week by week from the record\'s start_date to the window end, '
    'in two columns: by bias, and by the top N affiliations with Other and Unmapped. '
    'Government advertising is always excluded.'
)
RENDERS = 'Two cumulative line charts side by side, each with a table of totals under it.'
PARTIAL = 'cumulative_spend.html.j2'


class Params(BaseModel):
    """The cumulative spend params: the step between points and how many affiliations to name."""

    model_config = ConfigDict(extra='forbid')

    interval: Literal['week'] = 'week'
    top_affiliations: int = Field(default=8, ge=1)


# ---------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------- #

# The chart names within the section, and so their Content-ID suffixes
BIAS_IMAGE_NAME = 'biases'
AFFILIATION_IMAGE_NAME = 'affiliations'

# The days in one week, and the weekday a week starts on (Monday is 0)
DAYS_PER_WEEK = 7
WEEK_START_WEEKDAY = 0

# The key unmapped affiliation spend is gathered under while adding up
UNMAPPED_AFFILIATION_KEY = None


# ---------------------------------------------------------------- #
# Results
# ---------------------------------------------------------------- #

@dataclass
class CumulativeLine:
    """One line in a column: its name, colour, cumulative value per week and final total."""
    name: str
    colour: str
    values: list = field(default_factory=list)

    @property
    def total(self):
        """The line's final cumulative value."""
        if not self.values:
            return 0.0
        return self.values[-1]


# ---------------------------------------------------------------- #
# Step 1: daily spend
# ---------------------------------------------------------------- #

def daily_spend_rows(context, period_start, period_end):
    """Spend per day, bias and affiliation id from the start to the end, government dropped."""
    return context.query(
        f'SELECT scoped.date AS date,\n'
        f'       scoped.creator_affiliation_bias AS bias,\n'
        f'       scoped.creator_affiliation_id AS affiliation_id,\n'
        f'       sum(scoped.spend) AS spend\n'
        f'FROM ({context.statewide_spend_sql()}) AS scoped\n'
        f'WHERE scoped.date BETWEEN $period_start AND $period_end\n'
        f'  AND scoped.creator_classification IS DISTINCT FROM $government\n'
        f'GROUP BY 1, 2, 3',
        {
            'period_start': period_start,
            'period_end': period_end,
            'government': GOVERNMENT_CLASSIFICATION,
        },
    )


# ---------------------------------------------------------------- #
# Step 2: weeks
# ---------------------------------------------------------------- #

def week_start_of(day):
    """The Monday that starts the week a day falls in."""
    days_since_start = (day.weekday() - WEEK_START_WEEKDAY) % DAYS_PER_WEEK
    return day - datetime.timedelta(days=days_since_start)


def week_points(period_start, period_end):
    """
    The x axis points: the last day of each week, the final one cut short at the period end.

    Returns a list of (week_start, point_date) pairs, oldest first. Empty when
    the period starts after it ends.
    """
    if period_start > period_end:
        return []

    points = []
    current_week_start = week_start_of(period_start)
    last_week_start = week_start_of(period_end)
    one_week = datetime.timedelta(days=DAYS_PER_WEEK)
    last_day_offset = datetime.timedelta(days=DAYS_PER_WEEK - 1)

    # Step a week at a time, ending each week on Sunday or the period end
    while current_week_start <= last_week_start:
        point_date = current_week_start + last_day_offset
        if point_date > period_end:
            point_date = period_end
        points.append((current_week_start, point_date))
        current_week_start = current_week_start + one_week
    return points


def weekly_sums(rows, key_for_row, points):
    """Add up spend per key per week. Returns a dictionary of key to a list of weekly sums."""
    week_index = {}
    for index, point in enumerate(points):
        week_index[point[0]] = index

    sums = {}
    for row in rows:
        key = key_for_row(row)

        # Each key starts with a zero for every week
        if key not in sums:
            sums[key] = [0.0] * len(points)

        index = week_index[week_start_of(row['date'])]
        sums[key][index] += float(row['spend'])
    return sums


def running_totals(weekly_values):
    """Turn weekly sums into cumulative values."""
    cumulative = []
    running_total = 0.0
    for value in weekly_values:
        running_total += value
        cumulative.append(running_total)
    return cumulative


# ---------------------------------------------------------------- #
# Step 3: the bias column
# ---------------------------------------------------------------- #

def bias_key(row):
    """A row's bias label, with no bias read as unmapped."""
    label = row['bias']
    if label is None:
        return UNMAPPED_BIAS_LABEL
    return label


def bias_lines(reference, rows, points):
    """One cumulative line per bias with spend, in that bias's colour."""
    sums = weekly_sums(rows, bias_key, points)

    lines = []
    for label, weekly_values in sums.items():
        lines.append(CumulativeLine(
            name=bias_display_name(label),
            colour=reference.bias_colour(label),
            values=running_totals(weekly_values),
        ))
    return lines


# ---------------------------------------------------------------- #
# Step 4: the affiliation column
# ---------------------------------------------------------------- #

def add_weekly(target, source):
    """Add one list of weekly sums into another, in place."""
    for index, value in enumerate(source):
        target[index] += value


def affiliation_lines(reference, rows, points, top_count):
    """The top N affiliations by total, then Other for the rest, then Unmapped."""

    # Fold merged affiliations into their survivor; no affiliation is unmapped
    def affiliation_key(row):
        """A row's affiliation id after merges, or the unmapped key."""
        return reference.resolve_affiliation_id(row['affiliation_id'])

    sums = weekly_sums(rows, affiliation_key, points)

    # Take the unmapped spend out of the ranking
    unmapped_weekly = sums.pop(UNMAPPED_AFFILIATION_KEY, None)

    # Rank affiliations by total, highest first, ties by name
    ranked = []
    for affiliation_id, weekly_values in sums.items():
        total = sum(weekly_values)
        name = reference.affiliation_name(affiliation_id)
        ranked.append((-total, name, affiliation_id, weekly_values))
    ranked.sort()

    # The top N each get a line of their own
    lines = []
    for _negative_total, name, affiliation_id, weekly_values in ranked[:top_count]:
        lines.append(CumulativeLine(
            name=name,
            colour=reference.affiliation_colour(affiliation_id),
            values=running_totals(weekly_values),
        ))

    # Everything past the top N is gathered into Other
    remaining = ranked[top_count:]
    if remaining:
        other_weekly = [0.0] * len(points)
        for _negative_total, _name, _affiliation_id, weekly_values in remaining:
            add_weekly(other_weekly, weekly_values)
        lines.append(CumulativeLine(
            name=OTHER_LABEL,
            colour=OTHER_COLOUR,
            values=running_totals(other_weekly),
        ))

    # Spend with no affiliation is its own line
    if unmapped_weekly is not None:
        lines.append(CumulativeLine(
            name=UNMAPPED_AFFILIATION_LABEL,
            colour=UNMAPPED_COLOUR,
            values=running_totals(unmapped_weekly),
        ))
    return lines


# ---------------------------------------------------------------- #
# Step 5: charts and tables
# ---------------------------------------------------------------- #

def highest_first(lines):
    """The lines ordered by final total, highest first, ties by name."""
    ordered = list(lines)
    ordered.sort(key=lambda line: (-line.total, line.name))
    return ordered


def table_rows(lines):
    """One table row per line: name, swatch colour and total, highest first."""
    rows = []
    for line in highest_first(lines):
        rows.append({'name': line.name, 'colour': line.colour, 'total': line.total})
    return rows


def totals_sentence(lines):
    """The lines' totals in words, highest first, as in "Labor $8,370, Liberal $5,580"."""
    parts = []
    for line in highest_first(lines):
        parts.append(f'{line.name} {format_money(line.total)}')
    if not parts:
        return 'no spend'
    return ', '.join(parts)


def draw_column(image_name, title, lines, dates, period_text):
    """Draw one column's cumulative chart, with alt text naming every total."""
    series_list = []
    for line in lines:
        series_list.append(LineSeries(label=line.name, colour=line.colour, values=line.values))

    alt = f'Cumulative spend {title.lower()}, {period_text}: {totals_sentence(lines)}.'
    return cumulative_line_chart(image_name, dates, series_list, alt)


# ---------------------------------------------------------------- #
# The section
# ---------------------------------------------------------------- #

def build(context, params):
    """Build the cumulative spend section: two weekly cumulative charts with totals tables."""
    period_start = context.start_date
    period_end = context.window_end

    # Daily spend over the period, split into weeks
    rows = daily_spend_rows(context, period_start, period_end)
    points = week_points(period_start, period_end)
    dates = []
    for _week_start, point_date in points:
        dates.append(point_date)

    # The two columns' lines
    left_lines = bias_lines(context.reference, rows, points)
    right_lines = affiliation_lines(context.reference, rows, points, params.top_affiliations)

    # The period in words, for the alt text and the note
    if period_start <= period_end:
        period_text = format_date_range(period_start, period_end)
    else:
        period_text = f'from {format_long_date(period_start)}'

    # Draw both charts
    bias_title = 'By bias'
    affiliation_title = 'By affiliation'
    bias_chart = draw_column(BIAS_IMAGE_NAME, bias_title, left_lines, dates, period_text)
    affiliation_chart = draw_column(AFFILIATION_IMAGE_NAME, affiliation_title, right_lines, dates, period_text)

    # The grand total is the same in both columns
    grand_total = 0.0
    for line in left_lines:
        grand_total += line.total

    columns = [
        {'title': bias_title, 'image_name': BIAS_IMAGE_NAME, 'rows': table_rows(left_lines)},
        {'title': affiliation_title, 'image_name': AFFILIATION_IMAGE_NAME, 'rows': table_rows(right_lines)},
    ]
    period_note = f'Cumulative spend since {format_long_date(period_start)}, plotted weekly to {format_long_date(period_end)}.'
    variables = {
        'heading': 'Cumulative spend',
        'columns': columns,
        'grand_total': grand_total,
        'period_text': period_text,
    }
    summary_lines = [
        f'Cumulative spend since {format_long_date(period_start)}: {format_money(grand_total)}.',
        f'By affiliation: {totals_sentence(right_lines)}.',
    ]
    return SectionResult(
        variables=variables,
        images=[bias_chart, affiliation_chart],
        notes=[period_note],
        summary_lines=summary_lines,
        scope_notes=government_scope_notes(context, 'Cumulative spend figures'),
    )
