"""
Messaging and tone figures against the hand-checked fixture totals in tests/fixtures/README.md.
"""

import pytest
from pydantic import ValidationError

from dispatch.sections.messaging_tone import messaging_tone
from tests.support.section_context import build_section, make_section_context


# ---------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------- #

# The Weekly Campaign Brief's cards, plus a card for an affiliation with no adverts at all
CARDS = [
    {'label': 'Socialist Alliance', 'affiliation_ids': ['aff_socialist_alliance']},
    {'label': 'Labor', 'affiliation_ids': ['aff_labor']},
    {'label': 'Liberal', 'affiliation_ids': ['aff_liberal']},
    {'label': 'Greens', 'affiliation_ids': ['aff_greens']},
    {'label': 'Teals', 'affiliation_ids': ['aff_climate_200']},
]


def build_cards(gold_connection, reference, cards=None, **params):
    """Build the messaging section over the VIC 28-day fixtures and return its cards by label."""
    if cards is None:
        cards = CARDS
    context = make_section_context(gold_connection, reference)
    section_params = {'cards': cards}
    section_params.update(params)
    result = build_section(messaging_tone, context, section_params)

    by_label = {}
    for card in result.variables['cards']:
        by_label[card['label']] = card
    return result, by_label


def tone_shares(card):
    """A card's tones as (name, share, bar width) triples, in drawing order."""
    triples = []
    for tone in card['tones']:
        triples.append((tone['name'], tone['share'], tone['width']))
    return triples


def theme_figures(card):
    """A card's themes as (name, spend, bar width) triples, in order."""
    triples = []
    for theme in card['themes']:
        triples.append((theme['name'], theme['spend'], theme['width']))
    return triples


# ---------------------------------------------------------------- #
# Card order and spend
# ---------------------------------------------------------------- #

def test_cards_ordered_by_spend_with_zero_spend_card_last(gold_connection, reference):
    """Labor $4,480, Liberal $2,800, Teals $1,800, Greens $850, then Socialist Alliance with nothing."""
    result, _cards = build_cards(gold_connection, reference)

    order = []
    for card in result.variables['cards']:
        order.append((card['label'], card['spend']))
    assert order == [
        ('Labor', 4480.0),
        ('Liberal', 2800.0),
        ('Teals', 1800.0),
        ('Greens', 850.0),
        ('Socialist Alliance', 0.0),
    ]


def test_zero_spend_card_is_kept_and_greyed(gold_connection, reference):
    """The card with no adverts stays, greyed, saying there was no advertising in the window."""
    _result, cards = build_cards(gold_connection, reference)
    empty_card = cards['Socialist Alliance']

    assert empty_card['is_empty'] is True
    assert empty_card['colour'] == messaging_tone.EMPTY_CARD_COLOUR
    assert empty_card['empty_message'] == 'No advertising in the last 28 days'
    assert empty_card['tones'] == []
    assert empty_card['themes'] == []


def test_cards_pair_up_for_two_columns(gold_connection, reference):
    """Five cards make three rows of the grid: two, two and one."""
    result, _cards = build_cards(gold_connection, reference)

    row_sizes = []
    for pair in result.variables['card_rows']:
        row_sizes.append(len(pair))
    assert row_sizes == [2, 2, 1]


# ---------------------------------------------------------------- #
# Tone
# ---------------------------------------------------------------- #

def test_merged_affiliation_matches_through_the_card(gold_connection, reference):
    """
    The Liberal card lists aff_liberal only, yet matches aff_lib_old too:
    $2,240 negative + $560 compare and contrast = $2,800, 80% and 20%.
    """
    _result, cards = build_cards(gold_connection, reference)

    assert cards['Liberal']['spend'] == 2800.0
    assert tone_shares(cards['Liberal']) == [
        ('Compare and contrast', 0.2, 20),
        ('Negative', 0.8, 80),
    ]


def test_null_tone_shows_as_unclassified(gold_connection, reference):
    """Climate 200's only advert has no tone, so the Teals card is 100% Unclassified."""
    _result, cards = build_cards(gold_connection, reference)

    assert tone_shares(cards['Teals']) == [('Unclassified', 1.0, 100)]
    assert cards['Teals']['tones'][0]['colour'] == messaging_tone.UNCLASSIFIED_TONE_COLOUR


def test_tone_bar_widths_fill_the_bar():
    """Bar widths are whole percentages that always fill the bar exactly."""
    widths = messaging_tone.whole_percentages([1 / 3, 1 / 3, 1 / 3])
    assert widths == [34, 33, 33]
    assert sum(messaging_tone.whole_percentages([0.125, 0.375, 0.5])) == 100


# ---------------------------------------------------------------- #
# Themes
# ---------------------------------------------------------------- #

def test_themes_count_in_full_for_every_advert(gold_connection, reference):
    """
    Labor: meta_V01 ($2,800, Health and Cost of Living) and google_V11 ($1,680, Health).
    Health $4,480 and Cost of Living $2,800: together more than the card's $4,480, by design.
    """
    _result, cards = build_cards(gold_connection, reference)

    assert theme_figures(cards['Labor']) == [
        ('Health', 4480.0, 100),
        ('Cost of Living', 2800.0, 63),
    ]


def test_themes_rank_by_spend_ties_by_name(gold_connection, reference):
    """Liberal: Crime $2,800 then Cost of Living $2,240. Teals: Climate and Integrity tie at $1,800."""
    _result, cards = build_cards(gold_connection, reference)

    assert theme_figures(cards['Liberal']) == [
        ('Crime', 2800.0, 100),
        ('Cost of Living', 2240.0, 80),
    ]
    assert theme_figures(cards['Teals']) == [
        ('Climate', 1800.0, 100),
        ('Integrity', 1800.0, 100),
    ]


def test_top_themes_limits_each_card(gold_connection, reference):
    """With top_themes 1, each card lists only its biggest issue."""
    _result, cards = build_cards(gold_connection, reference, top_themes=1)
    assert theme_figures(cards['Labor']) == [('Health', 4480.0, 100)]


def test_overlap_note(gold_connection, reference):
    """The section always warns that issue amounts overlap."""
    result, _cards = build_cards(gold_connection, reference)
    assert result.notes == [
        'One ad can cover several issues, so issue amounts overlap and should not be added together.',
    ]


# ---------------------------------------------------------------- #
# Colours and params
# ---------------------------------------------------------------- #

def test_card_colours(gold_connection, reference):
    """A card takes its first affiliation's colour unless it sets its own."""
    cards = [
        {'label': 'Labor', 'affiliation_ids': ['aff_labor']},
        {'label': 'Teals', 'affiliation_ids': ['aff_climate_200'], 'colour': '#1C768C'},
    ]
    _result, by_label = build_cards(gold_connection, reference, cards=cards)

    assert by_label['Labor']['colour'] == '#dc2626'
    assert by_label['Teals']['colour'] == '#1c768c'


def test_card_needs_affiliations():
    """A card with no affiliation ids is refused at publish time."""
    with pytest.raises(ValidationError):
        messaging_tone.Params.model_validate({'cards': [{'label': 'Empty', 'affiliation_ids': []}]})


def test_summary_lines(gold_connection, reference):
    """The plain-text part names each card's spend, tone and top issues."""
    result, _cards = build_cards(gold_connection, reference)
    assert result.summary_lines[2] == (
        'Liberal: $2,800, 20% compare and contrast, 80% negative. Top issues: Crime, Cost of Living.'
    )
    assert result.summary_lines[-1] == 'Socialist Alliance: No advertising in the last 28 days.'
