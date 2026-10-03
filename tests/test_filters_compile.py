"""
Filter compile tests: include, exclude, null, themes, narrowing, merged
affiliations, and keys that must be refused.

Every count is over the 16 state-jurisdiction fixture adverts (13 Victorian,
3 New South Wales). See tests/fixtures/README.md for the advert list.
"""

import pytest
from pydantic import ValidationError

from dispatch.filters.compile import MATCH_EVERYTHING, compile_filters
from dispatch.models.template import FilterSet


# ---------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------- #

# How many state-jurisdiction adverts the fixtures hold
STATE_ADVERT_COUNT = 16


def matching_ad_keys(connection, filter_sets, affiliation_group=None):
    """The state-jurisdiction ad keys that pass the compiled filter, sorted."""
    compiled = compile_filters(filter_sets, affiliation_group)
    sql = (
        "SELECT adverts.ad_key FROM adverts WHERE adverts.jurisdiction = 'state' "
        f'AND ({compiled.sql}) ORDER BY adverts.ad_key'
    )
    rows = connection.execute(sql, compiled.parameters).fetchall()

    ad_keys = []
    for row in rows:
        ad_keys.append(row[0])
    return ad_keys


def include(**keys):
    """A filter set with only an include map."""
    return FilterSet(include=keys)


def exclude(**keys):
    """A filter set with only an exclude map."""
    return FilterSet(exclude=keys)


# ---------------------------------------------------------------- #
# Include and exclude
# ---------------------------------------------------------------- #

def test_no_filters_match_everything(gold_connection):
    """An empty filter compiles to TRUE and keeps every advert."""
    compiled = compile_filters([FilterSet()])
    assert compiled.sql == MATCH_EVERYTHING
    assert len(matching_ad_keys(gold_connection, [FilterSet()])) == STATE_ADVERT_COUNT


def test_include_keeps_only_listed_values(gold_connection):
    """Including political participants keeps 12 of the 16 state adverts."""
    ad_keys = matching_ad_keys(gold_connection, [include(classification=['political participant'])])
    assert len(ad_keys) == 12
    assert 'meta_V08' not in ad_keys
    assert 'meta_V09' not in ad_keys


def test_exclude_drops_listed_values_and_keeps_nulls(gold_connection):
    """Excluding government drops only the Victorian Government advert."""
    ad_keys = matching_ad_keys(gold_connection, [exclude(classification=['government'])])
    assert len(ad_keys) == STATE_ADVERT_COUNT - 1
    assert 'meta_V08' not in ad_keys


def test_values_in_one_key_are_ored(gold_connection):
    """Two datasources in one list match adverts from either."""
    ad_keys = matching_ad_keys(gold_connection, [include(datasource=['meta', 'google'])])
    assert len(ad_keys) == STATE_ADVERT_COUNT


def test_keys_are_anded(gold_connection):
    """Google AND political participant leaves only Labor's Google advert."""
    ad_keys = matching_ad_keys(
        gold_connection,
        [include(datasource=['google'], classification=['political participant'])],
    )
    assert ad_keys == ['google_V11']


# ---------------------------------------------------------------- #
# Null means unmapped
# ---------------------------------------------------------------- #

def test_include_null_matches_unmapped(gold_connection):
    """Including a null affiliation keeps the four adverts whose creators are unmapped."""
    ad_keys = matching_ad_keys(gold_connection, [include(affiliation_id=[None])])
    assert ad_keys == ['google_V10', 'meta_V06', 'meta_V07', 'meta_V13']


def test_exclude_null_drops_unmapped(gold_connection):
    """Excluding a null affiliation keeps the twelve mapped adverts."""
    ad_keys = matching_ad_keys(gold_connection, [exclude(affiliation_id=[None])])
    assert len(ad_keys) == 12


def test_include_value_and_null_together(gold_connection):
    """A value and null in one list match either, OR'd."""
    ad_keys = matching_ad_keys(gold_connection, [include(approach=['compare & contrast', None])])
    assert ad_keys == ['google_V10', 'meta_V03', 'meta_V05']


def test_exclude_value_keeps_null_rows(gold_connection):
    """Excluding positive tone keeps the two adverts with no tone at all."""
    ad_keys = matching_ad_keys(gold_connection, [exclude(approach=['positive'])])
    assert len(ad_keys) == 8
    assert 'meta_V05' in ad_keys
    assert 'google_V10' in ad_keys


def test_null_bias_covers_government_and_unmapped(gold_connection):
    """Null bias is the four unmapped adverts plus the government advert."""
    ad_keys = matching_ad_keys(gold_connection, [include(bias=[None])])
    assert len(ad_keys) == 5
    assert 'meta_V08' in ad_keys


# ---------------------------------------------------------------- #
# Themes and booleans
# ---------------------------------------------------------------- #

def test_theme_matches_any(gold_connection):
    """An advert carrying Climate among other themes matches."""
    ad_keys = matching_ad_keys(gold_connection, [include(theme=['Climate'])])
    assert ad_keys == ['meta_V04', 'meta_V05']


def test_theme_null_matches_adverts_without_themes(gold_connection):
    """A null theme matches Bob Lee's advert, which carries none."""
    ad_keys = matching_ad_keys(gold_connection, [include(theme=[None])])
    assert ad_keys == ['meta_V07']


def test_theme_exclude(gold_connection):
    """Excluding Cost of Living drops the three state adverts carrying it."""
    ad_keys = matching_ad_keys(gold_connection, [exclude(theme=['Cost of Living'])])
    assert len(ad_keys) == STATE_ADVERT_COUNT - 3


def test_boolean_key(gold_connection):
    """The local-government flag takes true or false."""
    included = matching_ad_keys(gold_connection, [include(is_local_government_content=[True])])
    excluded = matching_ad_keys(gold_connection, [exclude(is_local_government_content=[True])])
    assert included == ['meta_V13']
    assert len(excluded) == STATE_ADVERT_COUNT - 1


# ---------------------------------------------------------------- #
# Sections narrow the globals
# ---------------------------------------------------------------- #

def test_section_narrows_global(gold_connection):
    """Global Meta-only plus section political-participant-only leaves eleven adverts."""
    global_filters = include(datasource=['meta'])
    section_filters = include(classification=['political participant'])
    ad_keys = matching_ad_keys(gold_connection, [global_filters, section_filters])
    assert len(ad_keys) == 11
    assert 'google_V11' not in ad_keys


def test_section_cannot_widen_global(gold_connection):
    """A section naming another affiliation than the global one matches nothing."""
    global_filters = include(affiliation_id=['aff_labor'])
    section_filters = include(affiliation_id=['aff_greens'])
    ad_keys = matching_ad_keys(gold_connection, [global_filters, section_filters])
    assert ad_keys == []


# ---------------------------------------------------------------- #
# Merged affiliations
# ---------------------------------------------------------------- #

def test_superseded_affiliation_keeps_matching(gold_connection, reference):
    """aff_lib_old was merged into aff_liberal, so either id matches both ids' adverts."""
    by_survivor = matching_ad_keys(gold_connection, [include(affiliation_id=['aff_liberal'])],
                                   reference.affiliation_group)
    by_merged = matching_ad_keys(gold_connection, [include(affiliation_id=['aff_lib_old'])],
                                 reference.affiliation_group)
    assert by_survivor == ['meta_N02', 'meta_V02', 'meta_V03']
    assert by_merged == by_survivor


def test_without_merge_rules_ids_match_as_written(gold_connection):
    """Without the reference data, aff_liberal misses the advert still carrying aff_lib_old."""
    ad_keys = matching_ad_keys(gold_connection, [include(affiliation_id=['aff_liberal'])])
    assert ad_keys == ['meta_N02', 'meta_V02']


# ---------------------------------------------------------------- #
# Refusals and safety
# ---------------------------------------------------------------- #

def test_unimplemented_weight_key_is_rejected():
    """A weight key fails validation with a message naming the key."""
    with pytest.raises(ValidationError) as caught:
        FilterSet(include={'platform': ['facebook']})
    assert 'platform' in str(caught.value)
    assert 'not implemented' in str(caught.value)


def test_unknown_key_is_rejected():
    """A key nobody registered fails validation, naming it."""
    with pytest.raises(ValidationError) as caught:
        FilterSet(exclude={'state': ['VIC']})
    assert 'unknown filter key "state"' in str(caught.value)


def test_empty_value_list_is_rejected():
    """An empty list is ambiguous and refused."""
    with pytest.raises(ValidationError):
        FilterSet(include={'classification': []})


def test_wrong_value_type_is_rejected():
    """A boolean key refuses text, and a text key refuses booleans."""
    with pytest.raises(ValidationError):
        FilterSet(include={'is_local_government_content': ['yes']})
    with pytest.raises(ValidationError):
        FilterSet(include={'classification': [True]})


def test_values_are_bound_not_interpolated():
    """Values travel as parameters; the SQL text holds only placeholders."""
    compiled = compile_filters([include(affiliation_id=["aff_labor'; DROP TABLE adverts; --"])])
    assert 'DROP' not in compiled.sql
    assert '$filter_0' in compiled.sql
    assert compiled.parameters == {'filter_0': "aff_labor'; DROP TABLE adverts; --"}
