"""
Inline the CSS of a rendered email so clients that strip `<style>` still see it.

premailer moves every rule it can onto the matching elements' `style`
attributes and keeps the media queries in a `<style>` block for the clients
that honour them. It keeps conditional `<!--[if mso]>` comments as they are,
but drops the document type, so the skeleton's is put back on the front.
"""

from premailer import Premailer


# ---------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------- #

# The document type the skeleton declares, restored after inlining
XHTML_DOCTYPE = (
    '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" '
    '"http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">'
)


# ---------------------------------------------------------------- #
# Inlining
# ---------------------------------------------------------------- #

def strip_doctype(html):
    """Remove a leading document type declaration, if there is one."""
    stripped = html.lstrip()
    starts_with_doctype = stripped[:9].lower() == '<!doctype'
    if not starts_with_doctype:
        return stripped
    end_of_doctype = stripped.index('>') + 1
    return stripped[end_of_doctype:].lstrip()


def inline_css(html):
    """Return the email with its CSS inlined and its document type restored."""
    inliner = Premailer(
        html,
        keep_style_tags=False,
        strip_important=False,
        remove_classes=False,
        disable_validation=True,
        cssutils_logging_level='CRITICAL',
        allow_network=False,
    )
    inlined = inliner.transform()
    body = strip_doctype(inlined)
    return f'{XHTML_DOCTYPE}\n{body}'
