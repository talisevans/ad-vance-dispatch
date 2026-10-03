"""
Say a template's global filters in plain English, for the email footer.

Each include or exclude rule becomes one sentence, for example
`exclude.classification = ["government"]` becomes "Excludes government
advertising." A key with its own phrasing in the registry uses it; any other
key reads "Excludes advertising whose source is google."
"""

from dispatch.filters.registry import filter_keys_by_name


# ---------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------- #

# How a null value (unmapped) reads in a sentence
UNMAPPED_WORD = 'unmapped'

# The generic sentences, for keys with no phrasing of their own
GENERIC_EXCLUDE_PHRASE = 'Excludes advertising whose {noun} is {values}.'
GENERIC_INCLUDE_PHRASE = 'Covers only advertising whose {noun} is {values}.'


# ---------------------------------------------------------------- #
# Values
# ---------------------------------------------------------------- #

def value_words(value):
    """One filter value as it reads in a sentence."""
    if value is None:
        return UNMAPPED_WORD
    if value is True:
        return 'true'
    if value is False:
        return 'false'
    return str(value)


def values_words(values):
    """A list of values as one phrase: "a", "a or b", or "a, b or c"."""
    words = []
    for value in values:
        words.append(value_words(value))

    if len(words) == 1:
        return words[0]
    leading = ', '.join(words[:-1])
    return f'{leading} or {words[-1]}'


# ---------------------------------------------------------------- #
# Sentences
# ---------------------------------------------------------------- #

def rule_sentence(key, values, is_exclude):
    """One include or exclude rule as a sentence."""
    filter_key = filter_keys_by_name()[key]
    joined = values_words(values)

    # The key's own phrasing, when it has one
    own_phrase = filter_key.include_phrase
    if is_exclude:
        own_phrase = filter_key.exclude_phrase
    if own_phrase != '':
        return own_phrase.format(values=joined)

    # Otherwise the generic sentence, naming the key by its noun
    generic_phrase = GENERIC_INCLUDE_PHRASE
    if is_exclude:
        generic_phrase = GENERIC_EXCLUDE_PHRASE
    return generic_phrase.format(noun=filter_key.noun, values=joined)


def describe_filter_set(filter_set):
    """Every rule in a filter set as a sentence: the includes first, then the excludes."""
    sentences = []
    for key, values in filter_set.include.items():
        sentences.append(rule_sentence(key, values, False))
    for key, values in filter_set.exclude.items():
        sentences.append(rule_sentence(key, values, True))
    return sentences
