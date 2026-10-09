"""
The Top Seats section: the seats with the most spend, and who is spending most in each.

The steps run in this order:

  1. Add up apportioned spend per seat and spender in each window, from
     `ad_geo_daily`, restricted to the record's jurisdiction and state.
  2. Key each spender by affiliation (merged affiliations folded into their
     survivor), or by `creator:<creator_id>` when the creator has no affiliation,
     so two unmapped independents are never merged (D20).
  3. Rank seats by total spend in the ranking window and keep the first `limit`.
  4. In each seat, rank spenders by spend in the ranking window, ties broken on
     spender key. Show the leader and the runner-up.
  5. Show the Margin column only when a seat-margin lookup exists (D21), with
     each seat's margin written out by `margin_text`.
"""

import math
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dispatch.data.reference import UNMAPPED_COLOUR, round_half_up
from dispatch.formatting import format_money, safe_share
from dispatch.sections.base import SectionResult


# ---------------------------------------------------------------- #
# The section contract
# ---------------------------------------------------------------- #

TYPE_NAME = 'top_seats'
DESCRIPTION = (
    'The seats with the most apportioned spend in a ranking window, each with its leading '
    'and runner-up spender (by affiliation, or by creator when unmapped) and its total in '
    'every window listed.'
)
RENDERS = 'A ranked table of seats: rank, seat, margin when known, leader, runner-up and a total per window.'
PARTIAL = 'top_seats.html.j2'


class Params(BaseModel):
    """The Top Seats params: how many seats, which windows to total, and which window ranks."""

    model_config = ConfigDict(extra='forbid')

    limit: int = Field(default=10, ge=1)
    windows: list[int] = Field(default_factory=lambda: [7, 28], min_length=1)
    rank_by_window: int = 7

    @model_validator(mode='after')
    def check_windows(self):
        """Every window is at least a day, none repeats, and the ranking window is one of them."""
        for days in self.windows:
            if days < 1:
                raise ValueError(f'windows must be at least 1 day, got {days}')
        if len(set(self.windows)) != len(self.windows):
            raise ValueError('windows must not repeat')
        if self.rank_by_window not in self.windows:
            raise ValueError(f'rank_by_window {self.rank_by_window} must be one of windows {self.windows}')
        return self


# ---------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------- #

# The prefix on a spender key for a creator with no affiliation
CREATOR_KEY_PREFIX = 'creator:'

# What the runner-up column reads when a seat has only one spender
NO_RUNNER_UP = 'none'

# The tag shown beside an unmapped creator's name
UNMAPPED_TAG = 'unmapped'

# Text colours on a coloured tag: dark on light backgrounds, white on dark ones
DARK_TAG_TEXT = '#1a1a1a'
LIGHT_TAG_TEXT = '#ffffff'

# The relative luminance above which a background counts as light
LIGHT_BACKGROUND_LUMINANCE = 0.5

# The weights of red, green and blue in perceived brightness
RED_WEIGHT = 0.299
GREEN_WEIGHT = 0.587
BLUE_WEIGHT = 0.114
CHANNEL_MAXIMUM = 255

# Bar widths are whole percentages of their cell
FULL_WIDTH_PERCENT = 100
MINIMUM_BAR_PERCENT = 1

# The margin sources in the election_margins cache that carry a two-party margin
MARGIN_SOURCES_WITH_FIGURES = ('pendulum', 'result')

# The margin source for TAS and ACT seats, which elect several members each
MARGIN_SOURCE_MULTI_MEMBER = 'multi_member'

# What the Margin column reads for a multi-member seat
MULTI_MEMBER_TEXT = 'multi-member'

# A margin below this many points is shown to two decimal places, otherwise to one
TWO_DECIMAL_MARGIN_LIMIT = 1

# Units for rounding a margin in whole hundredths of a point, halves rounding up
HUNDREDTHS_PER_POINT = 100
HUNDREDTHS_PER_TENTH = 10
HALF_A_TENTH_IN_HUNDREDTHS = 5
TENTHS_PER_POINT = 10


# ---------------------------------------------------------------- #
# Results
# ---------------------------------------------------------------- #

@dataclass
class Spender:
    """One spender in one seat: key, display name, whether unmapped, colour and spend per window."""
    key: str
    name: str
    is_unmapped: bool
    colour: str
    spend: dict = field(default_factory=dict)


@dataclass
class Seat:
    """One seat: its id, name, total spend per window and its spenders by key."""
    seat_id: str
    name: str
    totals: dict = field(default_factory=dict)
    spenders: dict = field(default_factory=dict)


# ---------------------------------------------------------------- #
# Step 1: spend per seat and spender
# ---------------------------------------------------------------- #

def seat_spender_rows(context, window):
    """Spend in one window per seat, affiliation and creator."""
    return context.query(
        f'SELECT scoped.unique_electorate_id AS seat_id,\n'
        f'       scoped.electorate_name AS seat_name,\n'
        f'       scoped.creator_affiliation_id AS affiliation_id,\n'
        f'       scoped.creator_id AS creator_id,\n'
        f'       scoped.creator_name AS creator_name,\n'
        f'       sum(scoped.spend) AS spend\n'
        f'FROM ({context.seat_spend_sql()}) AS scoped\n'
        f'WHERE scoped.date BETWEEN $window_start AND $window_end\n'
        f'GROUP BY 1, 2, 3, 4, 5',
        {'window_start': window.start, 'window_end': window.end},
    )


# ---------------------------------------------------------------- #
# Step 2: spender keys
# ---------------------------------------------------------------- #

def spender_for_row(reference, row):
    """The spender a row belongs to: its affiliation after merges, or its own creator when unmapped."""
    affiliation_id = reference.resolve_affiliation_id(row['affiliation_id'])

    # A creator with no affiliation is a spender of its own
    if affiliation_id is None:
        creator_id = row['creator_id']
        return Spender(
            key=f'{CREATOR_KEY_PREFIX}{creator_id}',
            name=reference.creator_name(creator_id, fallback=row['creator_name']),
            is_unmapped=True,
            colour=UNMAPPED_COLOUR,
        )

    return Spender(
        key=affiliation_id,
        name=reference.affiliation_name(affiliation_id),
        is_unmapped=False,
        colour=reference.affiliation_colour(affiliation_id),
    )


def gather_seats(reference, rows_by_window):
    """Add every window's rows into seats and their spenders, keyed by seat id and spender key."""
    seats = {}
    for days, rows in rows_by_window.items():
        for row in rows:
            seat_id = row['seat_id']
            amount = float(row['spend'])

            # The seat, created on first sight with a zero for every window
            if seat_id not in seats:
                seats[seat_id] = Seat(seat_id=seat_id, name=row['seat_name'])
            seat = seats[seat_id]
            seat.totals[days] = seat.totals.get(days, 0.0) + amount

            # The spender within the seat, created on first sight
            spender = spender_for_row(reference, row)
            if spender.key not in seat.spenders:
                seat.spenders[spender.key] = spender
            existing = seat.spenders[spender.key]
            existing.spend[days] = existing.spend.get(days, 0.0) + amount
    return seats


# ---------------------------------------------------------------- #
# Steps 3 and 4: ranking
# ---------------------------------------------------------------- #

def ranked_seats(seats, rank_window, limit):
    """Seats with spend in the ranking window, most first, ties by name then id, cut to the limit."""
    candidates = []
    for seat in seats.values():
        ranking_total = seat.totals.get(rank_window, 0.0)
        if ranking_total <= 0:
            continue
        candidates.append((-ranking_total, seat.name, seat.seat_id, seat))
    candidates.sort(key=lambda candidate: candidate[:3])

    ranked = []
    for candidate in candidates[:limit]:
        ranked.append(candidate[3])
    return ranked


def ranked_spenders(seat, rank_window):
    """A seat's spenders with spend in the ranking window, most first, ties by spender key."""
    candidates = []
    for spender in seat.spenders.values():
        ranking_spend = spender.spend.get(rank_window, 0.0)
        if ranking_spend <= 0:
            continue
        candidates.append((-ranking_spend, spender.key, spender))
    candidates.sort(key=lambda candidate: candidate[:2])

    ranked = []
    for candidate in candidates:
        ranked.append(candidate[2])
    return ranked


# ---------------------------------------------------------------- #
# Display helpers
# ---------------------------------------------------------------- #

def tag_text_colour(background):
    """Dark text on a light tag, white text on a dark one."""
    digits = background.replace('#', '')
    red = int(digits[0:2], 16)
    green = int(digits[2:4], 16)
    blue = int(digits[4:6], 16)
    brightness = (RED_WEIGHT * red + GREEN_WEIGHT * green + BLUE_WEIGHT * blue) / CHANNEL_MAXIMUM
    if brightness > LIGHT_BACKGROUND_LUMINANCE:
        return DARK_TAG_TEXT
    return LIGHT_TAG_TEXT


def spender_view(spender, rank_window):
    """What the partial needs for one spender cell, or None for an empty runner-up."""
    if spender is None:
        return None
    return {
        'key': spender.key,
        'name': spender.name,
        'is_unmapped': spender.is_unmapped,
        'colour': spender.colour,
        'text_colour': tag_text_colour(spender.colour),
        'spend': spender.spend.get(rank_window, 0.0),
    }


def largest_totals(seats, windows):
    """The largest seat total in each window among the seats shown, to scale the bars."""
    largest = {}
    for days in windows:
        largest[days] = 0.0
        for seat in seats:
            seat_total = seat.totals.get(days, 0.0)
            if seat_total > largest[days]:
                largest[days] = seat_total
    return largest


def bar_width(amount, largest):
    """A bar's width in whole percent of the largest amount, never less than one when there is spend."""
    if amount <= 0:
        return 0
    width = round_half_up(safe_share(amount, largest) * FULL_WIDTH_PERCENT)
    if width < MINIMUM_BAR_PERCENT:
        width = MINIMUM_BAR_PERCENT
    return width


def has_margin_value(value):
    """Whether a margin field holds something to show: not None, not blank, not NaN."""
    # A missing value has nothing to show
    if value is None:
        return False

    # Text counts only when it is more than spaces
    if isinstance(value, str):
        return value.strip() != ''

    # A number counts unless it is NaN, which is how a missing number arrives from parquet
    if isinstance(value, float):
        return not math.isnan(value)

    # Anything else, such as a whole number, is a value
    return True


def format_margin_percent(margin_percent):
    """
    A margin in points: two decimal places below 1, otherwise one, with halves rounded up.

    Works in whole hundredths so the result matches the API's `formatMarginPercent`
    exactly: 2.25 shows as 2.3 in both, never 2.2 in one and 2.3 in the other.
    """
    margin_number = float(margin_percent)

    # Margins are stored to two decimals, so this is a whole number of hundredths
    hundredths = int(round(margin_number * HUNDREDTHS_PER_POINT))

    # A margin under one point keeps two decimals, so a very close seat is not shown as 0.0
    is_close_margin = margin_number < TWO_DECIMAL_MARGIN_LIMIT
    if is_close_margin:
        return f'{hundredths / HUNDREDTHS_PER_POINT:.2f}'

    # Any wider margin shows one decimal, a half rounding up
    tenths = (hundredths + HALF_A_TENTH_IN_HUNDREDTHS) // HUNDREDTHS_PER_TENTH
    return f'{tenths / TENTHS_PER_POINT:.1f}'


def margin_text(row):
    """What the Margin column reads for one seat's election_margins row, for example "Labor vs Greens 1.9%"."""
    # A seat the lookup does not hold reads blank
    if row is None:
        return ''

    # A TAS or ACT seat has no single two-party margin
    margin_source = row.get('margin_source')
    if margin_source == MARGIN_SOURCE_MULTI_MEMBER:
        return MULTI_MEMBER_TEXT

    # Only a pendulum or a result carries a margin; none and anything else read blank
    if margin_source not in MARGIN_SOURCES_WITH_FIGURES:
        return ''

    # The holder, the opponent and the margin must all be present
    holder = row.get('holder_party_name')
    opponent = row.get('opponent_party_name')
    margin_percent = row.get('margin_percent')
    for value in (holder, opponent, margin_percent):
        if not has_margin_value(value):
            return ''

    # Name the pair, holder first, then the margin as a percentage
    formatted = format_margin_percent(margin_percent)
    return f'{holder} vs {opponent} {formatted}%'


def seat_row(rank, seat, params, margins, largest):
    """One table row: rank, seat, margin, leader, runner-up and a total with a bar per window."""
    spenders = ranked_spenders(seat, params.rank_by_window)
    leader = spenders[0]
    runner_up = None
    if len(spenders) > 1:
        runner_up = spenders[1]

    # The margin when the lookup has this seat, blank otherwise
    margin = ''
    if margins is not None:
        margin_row = margins.get(seat.seat_id)
        margin = margin_text(margin_row)

    # One total per window, with a bar in the leader's colour
    totals = []
    for days in params.windows:
        amount = seat.totals.get(days, 0.0)
        totals.append({
            'days': days,
            'amount': amount,
            'width': bar_width(amount, largest[days]),
            'is_ranking_window': days == params.rank_by_window,
        })

    return {
        'rank': rank,
        'seat_id': seat.seat_id,
        'seat': seat.name,
        'margin': margin,
        'leader': spender_view(leader, params.rank_by_window),
        'runner_up': spender_view(runner_up, params.rank_by_window),
        'bar_colour': leader.colour,
        'totals': totals,
    }


def summary_line(row, rank_window):
    """One plain-text line for a seat: rank, name, ranking total, leader and runner-up."""
    ranking_total = 0.0
    for total in row['totals']:
        if total['days'] == rank_window:
            ranking_total = total['amount']

    leader = row['leader']
    line = (
        f'{row["rank"]}. {row["seat"]}: {format_money(ranking_total)}. '
        f'Leader {leader["name"]} {format_money(leader["spend"])}'
    )
    runner_up = row['runner_up']
    if runner_up is None:
        return f'{line}, runner-up {NO_RUNNER_UP}.'
    return f'{line}, runner-up {runner_up["name"]} {format_money(runner_up["spend"])}.'


# ---------------------------------------------------------------- #
# The section
# ---------------------------------------------------------------- #

def build(context, params):
    """Build the Top Seats table: seats ranked by spend, each with its leader and runner-up."""
    # Spend per seat and spender in every window
    rows_by_window = {}
    for days in params.windows:
        window = context.window(days)
        rows_by_window[days] = seat_spender_rows(context, window)
    seats = gather_seats(context.reference, rows_by_window)

    # The seats shown, and the scale for their bars
    shown_seats = ranked_seats(seats, params.rank_by_window, params.limit)
    largest = largest_totals(shown_seats, params.windows)

    # The margin column appears only when a seat lookup exists
    margins = context.reference.seat_margin_lookup()
    show_margin = margins is not None

    rows = []
    for index, seat in enumerate(shown_seats):
        rows.append(seat_row(index + 1, seat, params, margins, largest))

    # One column heading per window
    window_columns = []
    for days in params.windows:
        window_columns.append({'days': days, 'label': f'{days}-day spend'})

    ranking_window = context.window(params.rank_by_window)
    ranking_note = (
        f'Seats ranked by {params.rank_by_window}-day spend. Leader and runner-up are the '
        f'biggest spenders in each seat over the same {params.rank_by_window} days, by affiliation, '
        f'or by creator where the creator has no affiliation.'
    )

    variables = {
        'heading': f'Top {params.limit} seats by spend',
        'show_margin': show_margin,
        'window_columns': window_columns,
        'rows': rows,
        'no_runner_up': NO_RUNNER_UP,
        'unmapped_tag': UNMAPPED_TAG,
        'window_sentence': ranking_window.sentence,
    }

    summary_lines = [f'Top seats by {params.rank_by_window}-day spend:']
    for row in rows:
        summary_lines.append(summary_line(row, params.rank_by_window))

    return SectionResult(
        variables=variables,
        images=[],
        notes=[ranking_note],
        summary_lines=summary_lines,
    )
