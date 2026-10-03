"""
The messaging and tone section: one card per group of affiliations, showing tone and top issues.

The steps run in this order:

  1. Add up spend in the window by affiliation and tone, and by affiliation and theme.
  2. For each card in `params.cards`, gather the spend of its affiliations,
     with merged affiliations matching their survivor.
  3. Split the card's spend by tone (`approach`): positive, neutral, compare
     and contrast, negative, and Unclassified for no tone. Shares of the card's spend.
  4. Rank the card's themes by spend. Each theme counts in full for every advert
     carrying it, so theme amounts overlap and are never added together (ADR 0003).
  5. Order cards by spend, highest first. A card with no spend is kept, last and greyed.

Tone and theme bars are table cells, not images (D19), so they draw in every client.
"""

from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from dispatch.data.reference import OTHER_COLOUR, UNMAPPED_COLOUR, round_half_up
from dispatch.formatting import format_money, format_percent, safe_share
from dispatch.sections.base import SectionResult


# ---------------------------------------------------------------- #
# The section contract
# ---------------------------------------------------------------- #

TYPE_NAME = 'messaging_tone'
DESCRIPTION = (
    'One card per named group of affiliations (params.cards), each showing spend in a recent '
    'window, its tone split and its top issues by spend. Cards are ordered by spend; a card with '
    'no spend is kept and greyed.'
)
RENDERS = 'A two-column grid of cards, each with a tone bar and issue bars drawn as table cells.'
PARTIAL = 'messaging_tone.html.j2'

# A colour written as #rrggbb
HEX_COLOUR_PATTERN = r'^#[0-9a-fA-F]{6}$'


class Card(BaseModel):
    """One card: its label, the affiliation ids it gathers, and an optional colour."""

    model_config = ConfigDict(extra='forbid')

    label: str = Field(min_length=1)
    affiliation_ids: list[str] = Field(min_length=1)
    colour: Optional[str] = Field(default=None, pattern=HEX_COLOUR_PATTERN)


class Params(BaseModel):
    """The messaging params: the window, how many issues each card lists, and the cards."""

    model_config = ConfigDict(extra='forbid')

    window_days: int = Field(default=28, ge=1)
    top_themes: int = Field(default=5, ge=1)
    cards: list[Card] = Field(default_factory=list)


# ---------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------- #

# The tones gold holds, in the order they are drawn, with their names and colours
KNOWN_TONES = (
    ('positive', 'Positive', '#4c9f70'),
    ('neutral', 'Neutral', '#c9b458'),
    ('compare & contrast', 'Compare and contrast', '#9aa3b5'),
    ('negative', 'Negative', '#d9822b'),
)

# Spend with no tone, drawn last
UNCLASSIFIED_TONE_NAME = 'Unclassified'
UNCLASSIFIED_TONE_COLOUR = UNMAPPED_COLOUR

# A tone gold holds that the list above does not know
UNKNOWN_TONE_COLOUR = OTHER_COLOUR

# The colour a card with no spend is drawn in
EMPTY_CARD_COLOUR = '#bbbbbb'

# Bar widths are whole percentages of their table
FULL_WIDTH_PERCENT = 100

# The narrowest a theme bar is drawn, so a small amount still shows
MINIMUM_THEME_BAR_PERCENT = 1

# The note every messaging section carries (ADR 0003)
OVERLAP_NOTE = (
    'One ad can cover several issues, so issue amounts overlap and should not be added together.'
)


# ---------------------------------------------------------------- #
# Results
# ---------------------------------------------------------------- #

@dataclass
class CardFigures:
    """One card's figures: spend, spend by tone and spend by theme."""
    label: str
    colour: str
    spend: float = 0.0
    tone_spend: dict = field(default_factory=dict)
    theme_spend: dict = field(default_factory=dict)


# ---------------------------------------------------------------- #
# Step 1: spend by affiliation
# ---------------------------------------------------------------- #

def window_parameters(window):
    """The query parameters for a window."""
    return {'window_start': window.start, 'window_end': window.end}


def spend_by_affiliation_and_tone(context, window):
    """Spend in the window by affiliation id (as gold holds it) and tone."""
    return context.query(
        f'SELECT scoped.creator_affiliation_id AS affiliation_id,\n'
        f'       scoped.approach AS tone,\n'
        f'       sum(scoped.spend) AS spend\n'
        f'FROM ({context.statewide_spend_sql()}) AS scoped\n'
        f'WHERE scoped.date BETWEEN $window_start AND $window_end\n'
        f'GROUP BY 1, 2',
        window_parameters(window),
    )


def spend_by_affiliation_and_theme(context, window):
    """Spend in the window by affiliation id and theme, each advert counted in full under every theme it carries."""
    return context.query(
        f'SELECT themed.affiliation_id, themed.theme, sum(themed.spend) AS spend\n'
        f'FROM (\n'
        f'  SELECT scoped.creator_affiliation_id AS affiliation_id,\n'
        f'         unnest(scoped.themes) AS theme,\n'
        f'         scoped.spend\n'
        f'  FROM ({context.statewide_spend_sql()}) AS scoped\n'
        f'  WHERE scoped.date BETWEEN $window_start AND $window_end\n'
        f') AS themed\n'
        f'WHERE themed.theme IS NOT NULL\n'
        f'GROUP BY 1, 2',
        window_parameters(window),
    )


# ---------------------------------------------------------------- #
# Step 2: each card's spend
# ---------------------------------------------------------------- #

def card_affiliation_ids(reference, card):
    """Every affiliation id a card matches: each listed id and every id merged into it."""
    matched = set()
    for affiliation_id in card.affiliation_ids:
        for group_id in reference.affiliation_group(affiliation_id):
            matched.add(group_id)
    return matched


def card_colour(reference, card):
    """The card's colour: its own when set, else its first affiliation's."""
    if card.colour is not None:
        return card.colour.lower()
    return reference.affiliation_colour(card.affiliation_ids[0])


def gather_card(reference, card, tone_rows, theme_rows):
    """Add up one card's spend, tone split and theme spend from the affiliation rows."""
    matched_ids = card_affiliation_ids(reference, card)
    figures = CardFigures(label=card.label, colour=card_colour(reference, card))

    # Spend and tone from every row whose affiliation the card matches
    for row in tone_rows:
        if row['affiliation_id'] not in matched_ids:
            continue
        amount = float(row['spend'])
        figures.spend += amount
        tone = row['tone']
        figures.tone_spend[tone] = figures.tone_spend.get(tone, 0.0) + amount

    # Theme spend the same way
    for row in theme_rows:
        if row['affiliation_id'] not in matched_ids:
            continue
        theme = row['theme']
        figures.theme_spend[theme] = figures.theme_spend.get(theme, 0.0) + float(row['spend'])
    return figures


# ---------------------------------------------------------------- #
# Step 3: tone split
# ---------------------------------------------------------------- #

def tone_order(tone_spend):
    """Every tone a card has, as (gold value, name, colour): known tones, unknown tones, then Unclassified."""
    ordered = []
    known_values = []

    # The known tones in their fixed order
    for value, name, colour in KNOWN_TONES:
        known_values.append(value)
        if value in tone_spend:
            ordered.append((value, name, colour))

    # Any tone gold holds that the list does not know, by name
    unknown_values = []
    for value in tone_spend:
        if value is None:
            continue
        if value in known_values:
            continue
        unknown_values.append(value)
    for value in sorted(unknown_values):
        display_name = value[0].upper() + value[1:]
        ordered.append((value, display_name, UNKNOWN_TONE_COLOUR))

    # Spend with no tone goes last
    if None in tone_spend:
        ordered.append((None, UNCLASSIFIED_TONE_NAME, UNCLASSIFIED_TONE_COLOUR))
    return ordered


def whole_percentages(shares):
    """
    Turn shares that sum to 1 into whole percentages that sum to exactly 100.

    Each share is rounded down, then the points left over go to the shares
    that lost the most in rounding (largest remainder).
    """
    # A card with no spend has no tones to share out
    if not shares:
        return []

    floors = []
    remainders = []
    for index, share in enumerate(shares):
        exact = share * FULL_WIDTH_PERCENT
        floor = int(exact)
        floors.append(floor)
        remainders.append((-(exact - floor), index))

    # Hand out the leftover points, largest remainder first
    leftover = FULL_WIDTH_PERCENT - sum(floors)
    remainders.sort()
    for position in range(leftover):
        wrapped_position = position % len(remainders)
        index = remainders[wrapped_position][1]
        floors[index] += 1
    return floors


def tone_rows(figures):
    """One row per tone with spend: its name, colour, share of the card, and bar width in whole percent."""
    ordered = []
    for value, name, colour in tone_order(figures.tone_spend):
        amount = figures.tone_spend[value]
        if amount <= 0:
            continue
        ordered.append({'name': name, 'colour': colour, 'share': safe_share(amount, figures.spend)})

    # Bar cells take whole percentages that fill the bar exactly
    shares = []
    for row in ordered:
        shares.append(row['share'])
    widths = whole_percentages(shares)

    # A tone too small for one whole percent keeps its legend entry but draws no bar cell
    rows = []
    for row, width in zip(ordered, widths):
        row['width'] = width
        rows.append(row)
    return rows


# ---------------------------------------------------------------- #
# Step 4: top themes
# ---------------------------------------------------------------- #

def theme_rows(figures, top_count):
    """The card's top themes by spend, ties by name, each with a bar width relative to the top one."""
    ranked = []
    for theme, amount in figures.theme_spend.items():
        if amount <= 0:
            continue
        ranked.append((-amount, theme))
    ranked.sort()
    top = ranked[:top_count]

    # Bars are measured against the card's biggest theme
    largest = 0.0
    if top:
        largest = -top[0][0]

    rows = []
    for negative_amount, theme in top:
        amount = -negative_amount
        width = round_half_up(safe_share(amount, largest) * FULL_WIDTH_PERCENT)
        if width < MINIMUM_THEME_BAR_PERCENT:
            width = MINIMUM_THEME_BAR_PERCENT
        rows.append({'name': theme, 'spend': amount, 'width': width})
    return rows


# ---------------------------------------------------------------- #
# Step 5: cards in order
# ---------------------------------------------------------------- #

def card_view(figures, params):
    """What the partial needs for one card."""
    is_empty = figures.spend <= 0

    # A card with no spend is greyed and says so
    colour = figures.colour
    if is_empty:
        colour = EMPTY_CARD_COLOUR

    return {
        'label': figures.label,
        'colour': colour,
        'spend': figures.spend,
        'is_empty': is_empty,
        'empty_message': f'No advertising in the last {params.window_days} days',
        'tones': tone_rows(figures),
        'themes': theme_rows(figures, params.top_themes),
    }


def ordered_cards(all_figures):
    """Cards by spend, highest first. Ties, including every card with no spend, keep template order."""
    ordered = list(all_figures)
    ordered.sort(key=lambda figures: -figures.spend)
    return ordered


def pair_up(cards):
    """Split cards into rows of two for the two-column grid."""
    pairs = []
    for index in range(0, len(cards), 2):
        pairs.append(cards[index:index + 2])
    return pairs


def card_summary_line(card):
    """One plain-text line for a card: spend, tone split and top issues."""
    if card['is_empty']:
        return f'{card["label"]}: {card["empty_message"]}.'

    tone_parts = []
    for tone in card['tones']:
        tone_parts.append(f'{format_percent(tone["share"])} {tone["name"].lower()}')
    theme_names = []
    for theme in card['themes']:
        theme_names.append(theme['name'])

    line = f'{card["label"]}: {format_money(card["spend"])}, {", ".join(tone_parts)}.'
    if theme_names:
        line += f' Top issues: {", ".join(theme_names)}.'
    return line


# ---------------------------------------------------------------- #
# The section
# ---------------------------------------------------------------- #

def build(context, params):
    """Build the messaging cards: spend, tone split and top issues per card, ordered by spend."""
    window = context.window(params.window_days)

    # Spend by affiliation, by tone and by theme, read once for every card
    tone_rows_by_affiliation = spend_by_affiliation_and_tone(context, window)
    theme_rows_by_affiliation = spend_by_affiliation_and_theme(context, window)

    # Each card's figures, then the cards in order
    all_figures = []
    for card in params.cards:
        figures = gather_card(context.reference, card, tone_rows_by_affiliation, theme_rows_by_affiliation)
        all_figures.append(figures)

    cards = []
    for figures in ordered_cards(all_figures):
        cards.append(card_view(figures, params))

    summary_lines = [f'Messaging and tone, last {params.window_days} days:']
    for card in cards:
        summary_lines.append(card_summary_line(card))

    variables = {
        'heading': 'Messaging and tone',
        'window_days': params.window_days,
        'window_sentence': window.sentence,
        'cards': cards,
        'card_rows': pair_up(cards),
    }
    return SectionResult(
        variables=variables,
        images=[],
        notes=[OVERLAP_NOTE],
        summary_lines=summary_lines,
    )
