"""
Saying a template's global filters in plain English, for the email footer.
"""

from dispatch.filters.describe import describe_filter_set, values_words
from dispatch.models.template import FilterSet


def test_government_exclusion_reads_naturally():
    """The Weekly Campaign Brief's global filter becomes one short sentence."""
    filter_set = FilterSet(exclude={'classification': ['government']})
    assert describe_filter_set(filter_set) == ['Excludes government advertising.']


def test_includes_come_before_excludes_and_unmapped_is_named():
    """A key with no phrasing of its own reads through its noun; null reads as unmapped."""
    filter_set = FilterSet(
        include={'datasource': ['meta']},
        exclude={'affiliation_id': ['aff_labor', None]},
    )
    assert describe_filter_set(filter_set) == [
        'Covers only advertising whose source is meta.',
        'Excludes advertising whose affiliation is aff_labor or unmapped.',
    ]


def test_value_lists_join_with_commas_and_or():
    """One, two and three values."""
    assert values_words(['a']) == 'a'
    assert values_words(['a', 'b']) == 'a or b'
    assert values_words(['a', 'b', 'c']) == 'a, b or c'


def test_no_filters_says_nothing():
    """A template with no global filters adds no footer lines."""
    assert describe_filter_set(FilterSet()) == []


def test_affiliation_kind_reads_through_its_noun():
    """The affiliation kind key has no phrasing of its own, so it reads through its noun."""
    filter_set = FilterSet(include={'affiliation_kind': ['party', 'movement']})
    assert describe_filter_set(filter_set) == [
        'Covers only advertising whose affiliation kind is party or movement.',
    ]
