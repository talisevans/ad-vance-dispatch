"""
The section types the job knows, by type name.

Each section type lives in its own folder, `sections/<type>/`, holding `<type>.py`
and its partial `<type>.html.j2`. Registration is an explicit dictionary: import
the section's module here and add it to SECTION_TYPES under its TYPE_NAME. Nothing is discovered at run time.
"""

from dispatch.sections.bias_gauge import bias_gauge
from dispatch.sections.cumulative_spend import cumulative_spend
from dispatch.sections.messaging_tone import messaging_tone
from dispatch.sections.top_seats import top_seats


# ---------------------------------------------------------------- #
# The registry
# ---------------------------------------------------------------- #

# Section type name to its module. Each module keeps the contract in sections/base.py
SECTION_TYPES = {
    bias_gauge.TYPE_NAME: bias_gauge,
    cumulative_spend.TYPE_NAME: cumulative_spend,
    messaging_tone.TYPE_NAME: messaging_tone,
    top_seats.TYPE_NAME: top_seats,
}


def get_section_type(type_name):
    """Return the module for a section type, raising ValueError for a type nobody registered."""
    section_module = SECTION_TYPES.get(type_name)
    if section_module is None:
        known = ', '.join(sorted(SECTION_TYPES))
        if known == '':
            known = '(none registered)'
        raise ValueError(f'unknown section type "{type_name}". Known types: {known}')
    return section_module
