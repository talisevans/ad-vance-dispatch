"""
Send messages through Amazon SES over SMTP, with the `aws_ses` secret.

The secret is JSON holding `host`, `port`, `username` and `password`, the same
one the back end's runtime monitor uses. The job opens one SMTP session per
run and sends every recipient's message through it.

Two seams keep tests away from the network:

  1. `SecretSource` reads a secret. `SecretManagerSource` is the real one.
  2. `Mailer` opens a session that sends messages. `SmtpMailer` is the real
     one; `FakeMailer` records messages and can be told to fail some recipients.
"""

import json
import smtplib

from dispatch.config import PROJECT_ID, SES_SECRET_NAME


# ---------------------------------------------------------------- #
# Secrets
# ---------------------------------------------------------------- #

class SecretSource:
    """Reads a JSON secret by name."""

    def get_secret(self, secret_name):
        """Return the secret's parsed JSON payload."""
        raise NotImplementedError


class SecretManagerSource(SecretSource):
    """Reads secrets from Google Secret Manager."""

    def __init__(self, project_id=PROJECT_ID):
        """Remember the project the secrets live in."""
        self.project_id = project_id

    def get_secret(self, secret_name):
        """Load the latest version of a secret and parse its JSON."""
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        path = f'projects/{self.project_id}/secrets/{secret_name}/versions/latest'
        response = client.access_secret_version(name=path)
        payload = response.payload.data.decode('utf-8')
        return json.loads(payload)


# ---------------------------------------------------------------- #
# Mailers
# ---------------------------------------------------------------- #

class Mailer:
    """Opens a session that sends messages."""

    def session(self):
        """Return a context manager whose value has `send(message)`."""
        raise NotImplementedError


class SmtpSession:
    """One logged-in SMTP connection to SES."""

    def __init__(self, credentials):
        """Remember the credentials; the connection opens on entry."""
        self.credentials = credentials
        self.connection = None

    def __enter__(self):
        """Connect, upgrade to TLS and log in."""
        host = self.credentials['host']
        port = int(self.credentials['port'])
        self.connection = smtplib.SMTP(host, port)
        self.connection.starttls()
        self.connection.login(self.credentials['username'], self.credentials['password'])
        return self

    def __exit__(self, exception_type, exception, traceback):
        """Close the connection, ignoring a server that already hung up."""
        try:
            self.connection.quit()
        except smtplib.SMTPException:
            pass
        return False

    def send(self, message):
        """Send one message. Raises when SES refuses it."""
        self.connection.send_message(message)


class SmtpMailer(Mailer):
    """Sends through SES with the credentials in the `aws_ses` secret."""

    def __init__(self, secret_source=None, secret_name=SES_SECRET_NAME):
        """Remember where the credentials come from."""
        self.secret_source = secret_source
        if self.secret_source is None:
            self.secret_source = SecretManagerSource()
        self.secret_name = secret_name

    def session(self):
        """Open an SMTP session with fresh credentials."""
        credentials = self.secret_source.get_secret(self.secret_name)
        return SmtpSession(credentials)


class FakeSession:
    """A session that records messages and fails the recipients it was told to."""

    def __init__(self, mailer):
        """Remember the mailer whose records and failures this session uses."""
        self.mailer = mailer

    def __enter__(self):
        """Nothing to open."""
        return self

    def __exit__(self, exception_type, exception, traceback):
        """Nothing to close."""
        return False

    def send(self, message):
        """Record the message, or raise for a recipient set to fail."""
        recipient = message['To']
        if recipient in self.mailer.failing_recipients:
            raise smtplib.SMTPRecipientsRefused({recipient: (550, b'mailbox unavailable')})
        self.mailer.sent_messages.append(message)


class FakeMailer(Mailer):
    """An in-memory mailer for tests."""

    def __init__(self, failing_recipients=()):
        """Start with nothing sent and the given recipients set to fail."""
        self.failing_recipients = set(failing_recipients)
        self.sent_messages = []

    def session(self):
        """A fake session over this mailer's records."""
        return FakeSession(self)

    def sent_recipients(self):
        """The To address of every message sent, in order."""
        recipients = []
        for message in self.sent_messages:
            recipients.append(message['To'])
        return recipients
