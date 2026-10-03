"""
Run one Dispatch Record end to end (plan section 5.2).

  1. Load the record. A missing record exits cleanly: a trigger outlived it.
  2. For a scheduled run, honour `status`, `start_delivery` and `end_delivery`.
     After `end_delivery` the job deletes its own trigger and records `skipped`.
  3. Work out the slot: scheduled, manual, or none for a test send.
  4. Load and check the template, its layout and the record's property values.
  5. Open gold and build every section. A section that raises fails the run.
  6. Sign the browser link, render both copies, then upload the archive.
  7. Send to each recipient not already marked `sent` in the slot's ledger,
     recording each outcome as it happens.
  8. Write `last_run` and the ledger's outcome, and choose the exit code:
     non-zero when any recipient failed or anything raised.

Test sends ("Send test to me") go to one address with a `[TEST]` subject, write
no ledger and leave `last_run` alone.
"""

import datetime
import traceback
from dataclasses import dataclass, field
from typing import Callable, Optional

from dispatch.build import build_dispatch, render_dispatch
from dispatch.data.gold import open_gold_from
from dispatch.delivery.archive import archive_prefix, archive_slot_for_test, sign_browser_url, upload_archive
from dispatch.delivery.message import build_message
from dispatch.models.ledger import FAILED_STATUS, SENT_STATUS, RecipientOutcome, RunLedger
from dispatch.models.record import DispatchRecord
from dispatch.models.template import Template
from dispatch.scheduling.slots import manual_slot, scheduled_slot


# ---------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------- #

# The three kinds of run
SCHEDULED_KIND = 'scheduled'
MANUAL_KIND = 'manual'
TEST_KIND = 'test'

# Exit codes
SUCCESS_EXIT_CODE = 0
FAILURE_EXIT_CODE = 1

# Run outcomes
SENT_OUTCOME = 'sent'
PARTIAL_OUTCOME = 'partial'
FAILED_OUTCOME = 'failed'
SKIPPED_OUTCOME = 'skipped'

# Fields publish-templates adds to a template document that are not part of the template itself
PUBLISH_ONLY_FIELDS = ('published_at', 'build_tag', 'sample_path')


def utc_now():
    """The current time in UTC."""
    return datetime.datetime.now(datetime.timezone.utc)


def log(message):
    """Write one line to the job's log."""
    print(f'[dispatch] {message}', flush=True)


# ---------------------------------------------------------------- #
# Inputs and outputs
# ---------------------------------------------------------------- #

@dataclass
class RunRequest:
    """What the command line asked for: a record, and whether this is a manual or test run."""
    record_id: str
    manual: bool = False
    test_recipient: Optional[str] = None

    @property
    def kind(self):
        """Which of the three kinds of run this is. A test recipient wins over manual."""
        if self.test_recipient:
            return TEST_KIND
        if self.manual:
            return MANUAL_KIND
        return SCHEDULED_KIND


@dataclass
class Services:
    """Every outside service a run uses, so tests can hand in fakes."""
    store: object
    layouts: object
    gold_source: object
    archive: object
    mailer: object
    scheduler: object
    clock: Callable = utc_now


@dataclass
class RunReport:
    """How a run ended: its exit code, outcome, slot and who was and was not sent."""
    exit_code: int
    outcome: Optional[str] = None
    slot: Optional[str] = None
    sent: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    reason: str = ''


# ---------------------------------------------------------------- #
# Step 2: the delivery window
# ---------------------------------------------------------------- #

def delivery_window_check(record, request, services, now):
    """Return a RunReport when a scheduled run should stop here, otherwise None."""
    if request.kind != SCHEDULED_KIND:
        return None

    # A paused record sends nothing
    if record.status == 'inactive':
        log(f'record {record.id} is inactive; nothing to do')
        return RunReport(exit_code=SUCCESS_EXIT_CODE, reason='inactive')

    today = record.local_today(now)

    # Before the window opens, wait
    if today < record.start_delivery:
        log(f'record {record.id} starts delivery on {record.start_delivery}; today is {today}')
        return RunReport(exit_code=SUCCESS_EXIT_CODE, reason='before start_delivery')

    # After the window closes, remove the trigger and record the skip
    if today > record.end_delivery:
        deleted = services.scheduler.delete_trigger(record.trigger_name())
        log(f'record {record.id} ended delivery on {record.end_delivery}; trigger deleted: {deleted}')
        services.store.write_last_run(record.id, {
            'slot': None,
            'at': now,
            'outcome': SKIPPED_OUTCOME,
            'error': None,
            'recipient_count': 0,
            'failed_recipients': [],
        })
        return RunReport(exit_code=SUCCESS_EXIT_CODE, outcome=SKIPPED_OUTCOME, reason='after end_delivery')

    return None


# ---------------------------------------------------------------- #
# Step 3: the slot
# ---------------------------------------------------------------- #

def run_slot(record, request, now):
    """The slot this run belongs to, or None for a test send."""
    if request.kind == TEST_KIND:
        return None
    if request.kind == MANUAL_KIND:
        return manual_slot(now)
    return scheduled_slot(record.cron, record.timezone, now)


# ---------------------------------------------------------------- #
# Step 4: template, layout and property values
# ---------------------------------------------------------------- #

def load_template(record, services):
    """Load the record's template, check its schema version, and return it with its layout text."""
    document = services.store.get_template(record.template_id)
    if document is None:
        raise ValueError(f'template "{record.template_id}" does not exist')

    # Set aside the publishing details, which the template model does not accept
    template_fields = dict(document)
    for field_name in PUBLISH_ONLY_FIELDS:
        template_fields.pop(field_name, None)

    # The model refuses a schema version the job does not know
    template = Template.model_validate(template_fields)

    # The record must have been saved against the same schema version
    if template.schema_version != record.template_schema_version:
        raise ValueError(
            f'record expects template schema version {record.template_schema_version}, '
            f'but template "{template.id}" is version {template.schema_version}'
        )

    layout_text = services.layouts.read_layout(template.layout_path)
    return template, layout_text


# ---------------------------------------------------------------- #
# Step 7: the ledger and sending
# ---------------------------------------------------------------- #

def open_ledger(record, request, services, slot, now, as_of_text, prefix):
    """Read the slot's ledger, creating it on the first run of the slot."""
    existing = services.store.read_ledger(record.id, slot)
    if existing is not None:
        return RunLedger.model_validate(existing)

    ledger = RunLedger.start(
        slot=slot,
        kind=request.kind,
        started_at=now,
        as_of=as_of_text,
        archive_prefix=prefix,
    )
    services.store.merge_ledger(record.id, slot, ledger.model_dump(mode='python'))
    return ledger


def send_one(session, rendered, images, recipient, contact_email):
    """Send one recipient's message and return its outcome. A failure is caught, not raised."""
    try:
        message, message_id = build_message(rendered, images, recipient, contact_email)
        session.send(message)
    except Exception as error:
        log(f'send to {recipient} failed: {error}')
        return RecipientOutcome(status=FAILED_STATUS, error=str(error))
    return RecipientOutcome(status=SENT_STATUS, message_id=message_id)


def send_all(record, services, rendered, images, recipients, slot, ledger):
    """Send to each recipient in turn, writing each outcome to the ledger as it happens. Returns every outcome."""
    contact_email = record.contact()
    outcomes = {}

    with services.mailer.session() as session:
        for recipient in recipients:
            outcome = send_one(session, rendered, images, recipient, contact_email)
            outcomes[recipient] = outcome

            # A test send keeps no ledger
            if ledger is None:
                continue
            ledger.recipients[recipient] = outcome
            outcome_fields = outcome.model_dump(exclude_none=True)
            services.store.merge_ledger(record.id, slot, {'recipients': {recipient: outcome_fields}})

    return outcomes


def pinned_as_of_for(existing_ledger):
    """The as_of an earlier attempt at this slot was built with, or None on a first attempt."""
    if existing_ledger is None:
        return None
    if existing_ledger.as_of is None:
        return None
    return datetime.date.fromisoformat(existing_ledger.as_of)


def outcome_for(sent, failed):
    """The run outcome from who was sent and who failed."""
    if not failed:
        return SENT_OUTCOME
    if not sent:
        return FAILED_OUTCOME
    return PARTIAL_OUTCOME


# ---------------------------------------------------------------- #
# Steps 4 to 8: building and sending
# ---------------------------------------------------------------- #

def build_and_send(record, request, services, slot, now):
    """Build the Dispatch, archive it, send it and record the result."""
    is_test = request.kind == TEST_KIND

    # Read the ledger an earlier attempt at this slot left, if any
    existing_ledger = None
    if not is_test:
        existing = services.store.read_ledger(record.id, slot)
        if existing is not None:
            existing_ledger = RunLedger.model_validate(existing)

    # A slot whose every recipient was already sent needs nothing more
    if existing_ledger is not None:
        pending = existing_ledger.recipients_to_send(record.recipients)
        if not pending:
            log(f'slot {slot} already sent to every recipient')
            return RunReport(exit_code=SUCCESS_EXIT_CODE, outcome=SENT_OUTCOME, slot=slot,
                             sent=list(record.recipients), reason='already sent')

    # Step 4: template, layout and property values
    template, layout_text = load_template(record, services)
    property_values = template.validate_property_values(record.property_values)

    # A rerun keeps the as_of of the slot's first attempt, so its archive matches what was sent
    pinned_as_of = pinned_as_of_for(existing_ledger)

    # Step 5: gold and the sections
    connection = open_gold_from(services.gold_source)
    try:
        built = build_dispatch(template, record, property_values, connection, pinned_as_of=pinned_as_of)
    finally:
        connection.close()

    # Step 6: sign first, then render, then upload
    if is_test:
        prefix = archive_prefix(record.id, archive_slot_for_test(now))
    else:
        prefix = archive_prefix(record.id, slot)
    browser_url = sign_browser_url(services.archive, prefix)
    rendered = render_dispatch(built, layout_text, browser_url, is_test)
    upload_archive(services.archive, prefix, rendered, built.images)

    # Step 7: who to send to
    ledger = None
    if is_test:
        recipients = [request.test_recipient]
    else:
        as_of_text = built.dates.as_of.isoformat()
        ledger = open_ledger(record, request, services, slot, now, as_of_text, prefix)
        recipients = ledger.recipients_to_send(record.recipients)

    outcomes = send_all(record, services, rendered, built.images, recipients, slot, ledger)

    # Step 8: the outcome over every current recipient
    if is_test:
        return report_for_test_send(outcomes)
    return finish_ledger(record, services, slot, ledger)


def report_for_test_send(outcomes):
    """The report for a test send: it succeeds only when the one test address was sent."""
    sent = []
    failed = []
    for recipient, outcome in outcomes.items():
        if outcome.status == SENT_STATUS:
            sent.append(recipient)
        else:
            failed.append(recipient)

    outcome = outcome_for(sent, failed)
    exit_code = SUCCESS_EXIT_CODE
    if failed:
        exit_code = FAILURE_EXIT_CODE
    log(f'test send: {outcome}')
    return RunReport(exit_code=exit_code, outcome=outcome, sent=sent, failed=failed)


def finish_ledger(record, services, slot, ledger):
    """Write the slot's outcome and the record's last_run, and choose the exit code."""
    sent = []
    failed = []
    for recipient in record.recipients:
        if ledger.already_sent(recipient):
            sent.append(recipient)
        else:
            failed.append(recipient)

    outcome = outcome_for(sent, failed)
    finished_at = utc_now()

    services.store.merge_ledger(record.id, slot, {'outcome': outcome, 'finished_at': finished_at})
    services.store.write_last_run(record.id, {
        'slot': slot,
        'at': finished_at,
        'outcome': outcome,
        'error': None,
        'recipient_count': len(record.recipients),
        'failed_recipients': failed,
    })

    exit_code = SUCCESS_EXIT_CODE
    if failed:
        exit_code = FAILURE_EXIT_CODE
    log(f'slot {slot}: {outcome}, {len(sent)} sent, {len(failed)} failed')
    return RunReport(exit_code=exit_code, outcome=outcome, slot=slot, sent=sent, failed=failed)


# ---------------------------------------------------------------- #
# The run
# ---------------------------------------------------------------- #

def run_record(request, services):
    """Run one record end to end and return a RunReport. Never raises."""
    now = services.clock()

    # Step 1: the record
    document = services.store.get_record(request.record_id)
    if document is None:
        log(f'record {request.record_id} does not exist; nothing to do')
        return RunReport(exit_code=SUCCESS_EXIT_CODE, reason='record missing')
    record = DispatchRecord.model_validate(document)

    # Step 2: the delivery window
    stopped = delivery_window_check(record, request, services, now)
    if stopped is not None:
        return stopped

    # Step 3: the slot
    slot = run_slot(record, request, now)
    log(f'record {record.id}: {request.kind} run, slot {slot}')

    # Steps 4 to 8, with any failure recorded and turned into a non-zero exit
    try:
        return build_and_send(record, request, services, slot, now)
    except Exception as error:
        log(f'run failed: {error}')
        traceback.print_exc()
        record_failure(record, request, services, slot, error)
        return RunReport(exit_code=FAILURE_EXIT_CODE, outcome=FAILED_OUTCOME, slot=slot, reason=str(error))


def record_failure(record, request, services, slot, error):
    """Write a failed last_run for a scheduled or manual run. A test send records nothing."""
    if request.kind == TEST_KIND:
        return
    try:
        failed = unsent_recipients(record, services, slot)
        services.store.write_last_run(record.id, {
            'slot': slot,
            'at': utc_now(),
            'outcome': FAILED_OUTCOME,
            'error': str(error),
            'recipient_count': len(record.recipients),
            'failed_recipients': failed,
        })
    except Exception as write_error:
        log(f'could not write last_run: {write_error}')


def unsent_recipients(record, services, slot):
    """The record's recipients the slot's ledger does not mark as sent."""
    existing = services.store.read_ledger(record.id, slot)
    if existing is None:
        return list(record.recipients)
    ledger = RunLedger.model_validate(existing)
    return ledger.recipients_to_send(record.recipients)
