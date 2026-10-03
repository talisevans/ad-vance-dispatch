"""
Render one Dispatch to disk with no cloud access, for a developer to open.

    python -m dispatch.main --render-only --record-file <json> --data-dir <gold> --out out/

The real run path (`run.run_record`) runs as a "Send now" run, with every
outside service swapped for a local stand-in:

  1. The record comes from a JSON file and the template from the repository,
     both held in the in-memory Firestore fake.
  2. The layout is read from the repository, and gold from a local parquet
     directory.
  3. The archive is kept in memory, and the "view in browser" link points at
     the `browser.html` written beside the email.
  4. Messages go to the in-memory mailer, so nothing is sent.

The files written to the output directory:

  email.html     the email render (charts by cid:, so they show only in a mail client)
  browser.html   the browser render (charts embedded), the one to open in a browser
  <chart>.png    every chart image
  email.txt      the plain-text part
  message.eml    the full MIME message for the first recipient, to open in a mail client
"""

import json
import os
from dataclasses import dataclass, field

from dispatch.data.gold import resolve_gold_source
from dispatch.delivery.archive import BROWSER_FILE_NAME, FakeArchiveStore
from dispatch.delivery.ses import FakeMailer
from dispatch.publish_templates import TEMPLATES_DIRECTORY, load_template_source
from dispatch.render.layout import LocalLayoutStore
from dispatch.run import RunRequest, Services, run_record
from dispatch.scheduling.scheduler import FakeSchedulerClient
from dispatch.store.firestore import FakeDispatchStore


# ---------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------- #

# The record id used when the record file does not carry one
DEFAULT_RECORD_ID = 'preview'

# The files written beside the archive's own
PLAIN_TEXT_FILE_NAME = 'email.txt'
MESSAGE_FILE_NAME = 'message.eml'

# The MIME type of the plain-text part
PLAIN_TEXT_CONTENT_TYPE = 'text/plain'


def log(message):
    """Write one line to the command's output."""
    print(f'[preview] {message}', flush=True)


# ---------------------------------------------------------------- #
# Local stand-ins
# ---------------------------------------------------------------- #

class PreviewArchiveStore(FakeArchiveStore):
    """An in-memory archive whose browser link is the local `browser.html` beside the email."""

    def signed_url(self, object_path, lifetime):
        """Return a relative link to the browser copy, so it opens from the output folder."""
        self.signed_paths.append(object_path)
        self.events.append(('sign', object_path))
        return BROWSER_FILE_NAME


@dataclass
class PreviewResult:
    """What a preview produced: the run's report, the subject and the files written."""
    report: object
    subject: str = ''
    written_paths: list = field(default_factory=list)


# ---------------------------------------------------------------- #
# Step 1: the record and the template
# ---------------------------------------------------------------- #

def read_record_document(record_file):
    """Read a Dispatch Record from a JSON file, giving it an id when it has none."""
    with open(record_file, encoding='utf-8') as opened_file:
        document = json.load(opened_file)

    # The record's id is its Firestore document name, which a file may leave out
    has_id = bool(document.get('id'))
    if not has_id:
        document['id'] = DEFAULT_RECORD_ID
    return document


def template_document(template_id, templates_directory):
    """Load and validate a template from the repository, as publish-templates would store it."""
    template_directory = os.path.join(templates_directory, template_id)
    source = load_template_source(template_directory)
    return source.template.model_dump(mode='json')


# ---------------------------------------------------------------- #
# Step 2: the services
# ---------------------------------------------------------------- #

def preview_services(record_document, template, templates_directory, gold_directory, lookups_directory):
    """Services for one local run: fakes for Firestore, the archive, SES and Scheduler."""
    record_id = record_document['id']
    store = FakeDispatchStore(
        records={record_id: record_document},
        templates={template['id']: template},
    )

    # Layout paths (`templates/emails/<id>/...`) are relative to the folder holding `templates/`
    emails_directory = os.path.abspath(templates_directory)
    templates_root = os.path.dirname(emails_directory)
    layouts_root = os.path.dirname(templates_root)

    return Services(
        store=store,
        layouts=LocalLayoutStore(layouts_root),
        gold_source=resolve_gold_source(gold_directory, lookups_directory),
        archive=PreviewArchiveStore(),
        mailer=FakeMailer(),
        scheduler=FakeSchedulerClient(),
    )


# ---------------------------------------------------------------- #
# Step 3: writing the files
# ---------------------------------------------------------------- #

def write_file(path, data):
    """Write text or bytes to a file."""
    if isinstance(data, bytes):
        with open(path, 'wb') as opened_file:
            opened_file.write(data)
        return
    with open(path, 'w', encoding='utf-8') as opened_file:
        opened_file.write(data)


def write_archive(archive, out_directory):
    """Write every archived object to the output folder under its own file name. Returns the paths."""
    written_paths = []
    for object_path in sorted(archive.objects):
        data, _content_type = archive.objects[object_path]
        file_name = os.path.basename(object_path)
        target_path = os.path.join(out_directory, file_name)
        write_file(target_path, data)
        written_paths.append(target_path)
    return written_paths


def plain_text_of(message):
    """The plain-text body of a MIME message, or an empty string when it has none."""
    for part in message.walk():
        if part.get_content_type() != PLAIN_TEXT_CONTENT_TYPE:
            continue
        payload = part.get_payload(decode=True)
        return payload.decode('utf-8')
    return ''


def write_message(mailer, out_directory):
    """Write the first recipient's plain text and full message. Returns the paths and the subject."""
    if not mailer.sent_messages:
        return [], ''

    message = mailer.sent_messages[0]
    text_path = os.path.join(out_directory, PLAIN_TEXT_FILE_NAME)
    write_file(text_path, plain_text_of(message))

    message_path = os.path.join(out_directory, MESSAGE_FILE_NAME)
    write_file(message_path, message.as_bytes())
    subject = str(message['Subject'])
    return [text_path, message_path], subject


# ---------------------------------------------------------------- #
# The preview
# ---------------------------------------------------------------- #

def render_preview(record_file, gold_directory, out_directory, lookups_directory=None,
                   templates_directory=TEMPLATES_DIRECTORY):
    """Run one record locally as a "Send now" run and write what it produced. Returns a PreviewResult."""
    record_document = read_record_document(record_file)
    template = template_document(record_document['template_id'], templates_directory)
    services = preview_services(record_document, template, templates_directory, gold_directory, lookups_directory)

    # A manual run skips the delivery window, so any record previews on any day
    request = RunRequest(record_id=record_document['id'], manual=True)
    report = run_record(request, services)
    result = PreviewResult(report=report)
    if report.exit_code != 0:
        log(f'the run failed: {report.reason}')
        return result

    # Write the archive, then the plain text and message
    os.makedirs(out_directory, exist_ok=True)
    archive_paths = write_archive(services.archive, out_directory)
    message_paths, subject = write_message(services.mailer, out_directory)
    result.written_paths = archive_paths + message_paths
    result.subject = subject

    log(f'subject: {subject}')
    for path in result.written_paths:
        log(f'wrote {path}')
    return result
