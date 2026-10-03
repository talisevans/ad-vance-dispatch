"""
Reference data tests: the dashboard colour fallback matches palette.ts, biases
order with unmapped straight after centrist, merges resolve, and the lookup
views keep only the newest row per key.
"""

from dispatch.data.reference import (
    OTHER_COLOUR,
    UNMAPPED_COLOUR,
    derived_bias_colour,
    fallback_affiliation_colour,
    name_hash,
)


# ---------------------------------------------------------------- #
# The ported palette
# ---------------------------------------------------------------- #

# Colours computed by running palette.ts's own hash in Node
DASHBOARD_FALLBACK_COLOURS = {
    'Institute of Public Affairs': '#2563eb',
    'Socialist Alliance': '#f59e0b',
    'Australian Unions': '#f59e0b',
    'Électeurs 😀 Group': '#f59e0b',
    'Victorian Government': '#15803d',
}


def test_fallback_colours_match_the_dashboard():
    """Names with no stored colour take the same slot the dashboard gives them."""
    for name, expected in DASHBOARD_FALLBACK_COLOURS.items():
        assert fallback_affiliation_colour(name) == expected


def test_named_colours_win_over_slots():
    """Parties take their own colour and every independent takes teal."""
    assert fallback_affiliation_colour('Labor') == '#dc2626'
    assert fallback_affiliation_colour('Liberal') == '#1e3a8a'
    assert fallback_affiliation_colour('Independent (right)') == '#0d9488'


def test_hash_wraps_like_javascript():
    """The hash wraps to a signed 32-bit value, as `| 0` does."""
    assert name_hash('a') == 97
    assert name_hash('Institute of Public Affairs') < 2 ** 31
    assert name_hash('Institute of Public Affairs') >= -(2 ** 31)


def test_derived_bias_colour_blends_between_stops():
    """A position halfway between centrist and right blends their colours, rounding halves up."""
    assert derived_bias_colour(0.0) == '#94a3b8'
    assert derived_bias_colour(0.5) == '#6893d7'
    assert derived_bias_colour(5.0) == '#1e40af'


# ---------------------------------------------------------------- #
# Affiliations
# ---------------------------------------------------------------- #

def test_stored_colour_wins(reference):
    """Climate 200's admin-set colour is used, lowercased."""
    assert reference.affiliation_colour('aff_climate_200') == '#0f766e'


def test_unmapped_affiliation_is_grey(reference):
    """A null affiliation draws in the unmapped grey; Other has its own grey."""
    assert reference.affiliation_colour(None) == UNMAPPED_COLOUR
    assert OTHER_COLOUR == '#9ca3af'


def test_merges_resolve_to_the_survivor(reference):
    """aff_lib_old resolves to aff_liberal, and takes its name and colour."""
    assert reference.resolve_affiliation_id('aff_lib_old') == 'aff_liberal'
    assert reference.affiliation_name('aff_lib_old') == 'Liberal'
    assert reference.affiliation_colour('aff_lib_old') == '#1e3a8a'
    assert reference.affiliation_group('aff_lib_old') == ['aff_liberal', 'aff_lib_old']


def test_unknown_affiliation_answers_as_itself(reference):
    """An id the cache lacks is its own survivor and its own group."""
    assert reference.resolve_affiliation_id('aff_unknown') == 'aff_unknown'
    assert reference.affiliation_group('aff_unknown') == ['aff_unknown']


def test_newest_cache_row_wins(reference):
    """The stale Greens row written in June is hidden by the October row."""
    assert reference.affiliations['aff_greens'].name == 'Greens'


# ---------------------------------------------------------------- #
# Biases and creators
# ---------------------------------------------------------------- #

def test_bias_slots_put_unmapped_after_centrist(reference):
    """Left to right: extreme left, left, centrist, unmapped, right, extreme right."""
    labels = []
    for slot in reference.bias_slots():
        labels.append(slot.label)
    assert labels == ['extreme left', 'left', 'centrist', 'unmapped', 'right', 'extreme right']


def test_bias_colours_and_positions(reference):
    """Defined biases use their stored colour; null sits at zero in grey."""
    assert reference.bias_colour('left') == '#ef4444'
    assert reference.bias_colour(None) == UNMAPPED_COLOUR
    assert reference.bias_position(None) == 0.0
    assert reference.bias_position('extreme right') == 2.0


def test_creator_names(reference):
    """Creator names come from the cache, falling back to what the caller knows."""
    assert reference.creator_name('c_jane_smith') == 'Jane Smith for Kew'
    assert reference.creator_name('c_missing', 'Gold name') == 'Gold name'
    assert reference.creator_name('c_missing') == 'c_missing'
