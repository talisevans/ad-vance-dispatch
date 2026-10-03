"""
Build the MIME message for one recipient.

The structure, from section 5.11 of the plan:

    multipart/related
      multipart/alternative
        text/plain   headline figures, the window sentence and the browser link
        text/html    the inlined email render, images by cid:
      image/png      one per chart, with a Content-ID header

Headers: From is the Dispatch sender, To is one recipient, Reply-To is the
record's contact, Subject comes from the template.
"""

from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid

from dispatch.config import MESSAGE_ID_DOMAIN, SENDER_ADDRESS, SENDER_DISPLAY_NAME


# ---------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------- #

# Every Dispatch carries this sender
SENDER = formataddr((SENDER_DISPLAY_NAME, SENDER_ADDRESS))


# ---------------------------------------------------------------- #
# Parts
# ---------------------------------------------------------------- #

def alternative_part(plain_text, html):
    """The plain-text and HTML bodies, plain first so clients prefer the HTML."""
    alternative = MIMEMultipart('alternative')
    alternative.attach(MIMEText(plain_text, 'plain', 'utf-8'))
    alternative.attach(MIMEText(html, 'html', 'utf-8'))
    return alternative


def image_part(content_id, image):
    """One chart PNG, attached inline under its Content-ID."""
    part = MIMEImage(image.png, 'png')
    part.add_header('Content-ID', f'<{content_id}>')
    part.add_header('Content-Disposition', 'inline', filename=f'{content_id}.png')
    return part


# ---------------------------------------------------------------- #
# The message
# ---------------------------------------------------------------- #

def build_message(rendered, images, recipient, contact_email):
    """
    Build the message for one recipient. Returns the message and its Message-ID.

    `rendered` is a RenderedDispatch and `images` the (content id, ChartImage)
    pairs from the built Dispatch.
    """
    message = MIMEMultipart('related')
    message_id = make_msgid(domain=MESSAGE_ID_DOMAIN)

    # Headers
    message['From'] = SENDER
    message['To'] = recipient
    message['Subject'] = rendered.subject
    message['Date'] = formatdate(localtime=False)
    message['Message-ID'] = message_id
    if contact_email:
        message['Reply-To'] = contact_email

    # The bodies, then each chart
    message.attach(alternative_part(rendered.plain_text, rendered.email_html))
    for content_id, image in images:
        message.attach(image_part(content_id, image))

    return message, message_id
