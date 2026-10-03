"""
Whole-run tests with fake services: the ledger makes reruns safe, the delivery
window is honoured, test sends leave no trace, and failures exit non-zero.
"""

import datetime

from dispatch.delivery.archive import BROWSER_FILE_NAME
from dispatch.formatting import window_sentence
from dispatch.run import FAILURE_EXIT_CODE, SUCCESS_EXIT_CODE, RunRequest, run_record
from tests.conftest import RECIPIENTS, RECORD_ID


# ---------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------- #

SLOT = '2026-10-05T09:00'


def scheduled():
    """A scheduled run of the test record."""
    return RunRequest(record_id=RECORD_ID)


def stored_record(services):
    """The record as the fake store now holds it."""
    return services.store.records[RECORD_ID]


# ---------------------------------------------------------------- #
# The ledger
# ---------------------------------------------------------------- #

def test_scheduled_run_sends_to_everyone(make_services):
    """A clean run sends to all three recipients and records `sent`."""
    services = make_services()
    report = run_record(scheduled(), services)

    assert report.exit_code == SUCCESS_EXIT_CODE
    assert report.outcome == 'sent'
    assert report.slot == SLOT
    assert services.mailer.sent_recipients() == RECIPIENTS
    assert stored_record(services)['last_run']['outcome'] == 'sent'

    ledger = services.store.ledgers[(RECORD_ID, SLOT)]
    assert ledger['outcome'] == 'sent'
    assert ledger['kind'] == 'scheduled'
    assert ledger['as_of'] == '2026-10-01'
    assert ledger['archive_prefix'] == f'sent/{RECORD_ID}/{SLOT}/'


def test_rerun_after_partial_send_only_sends_to_the_failed_recipient(make_services):
    """Bob fails first time; the retry five minutes later sends only to Bob."""
    services = make_services(failing_recipients=['bob@example.test'])
    first = run_record(scheduled(), services)

    assert first.exit_code == FAILURE_EXIT_CODE
    assert first.outcome == 'partial'
    assert first.failed == ['bob@example.test']
    assert stored_record(services)['last_run']['failed_recipients'] == ['bob@example.test']
    ledger = services.store.ledgers[(RECORD_ID, SLOT)]
    assert ledger['recipients']['bob@example.test']['status'] == 'failed'
    assert ledger['recipients']['alice@example.test']['status'] == 'sent'

    # Bob's mailbox recovers, and Scheduler retries the same slot
    services.mailer.failing_recipients.clear()
    services.mailer.sent_messages.clear()
    services.clock.advance(minutes=5)
    second = run_record(scheduled(), services)

    assert second.exit_code == SUCCESS_EXIT_CODE
    assert second.slot == SLOT
    assert services.mailer.sent_recipients() == ['bob@example.test']
    assert services.store.ledgers[(RECORD_ID, SLOT)]['outcome'] == 'sent'
    assert stored_record(services)['last_run']['outcome'] == 'sent'


def test_rerun_keeps_the_as_of_of_the_first_attempt(make_services):
    """Alice was sent a brief as of 30 September; Bob's rerun and the archive keep that date."""
    services = make_services(failing_recipients=['bob@example.test'])
    run_record(scheduled(), services)

    # The first attempt was built when gold ended on 30 September; gold now ends on 1 October
    ledger = services.store.ledgers[(RECORD_ID, SLOT)]
    ledger['as_of'] = '2026-09-30'
    services.mailer.failing_recipients.clear()
    services.mailer.sent_messages.clear()
    services.archive.objects.clear()
    services.clock.advance(minutes=5)
    second = run_record(scheduled(), services)

    assert second.exit_code == SUCCESS_EXIT_CODE
    assert services.mailer.sent_recipients() == ['bob@example.test']
    assert services.store.ledgers[(RECORD_ID, SLOT)]['as_of'] == '2026-09-30'

    # The rebuilt archive quotes the first attempt's window, not gold's newer one
    browser_html, _content_type = services.archive.objects[f'sent/{RECORD_ID}/{SLOT}/{BROWSER_FILE_NAME}']
    first_window = window_sentence(7, datetime.date(2026, 9, 24), datetime.date(2026, 9, 30))
    newer_window = window_sentence(7, datetime.date(2026, 9, 25), datetime.date(2026, 10, 1))
    assert first_window in browser_html
    assert newer_window not in browser_html


def test_rerun_of_a_fully_sent_slot_sends_nothing(make_services):
    """Once every recipient is sent, a rerun of the slot sends nothing more."""
    services = make_services()
    run_record(scheduled(), services)
    services.mailer.sent_messages.clear()

    report = run_record(scheduled(), services)
    assert report.exit_code == SUCCESS_EXIT_CODE
    assert services.mailer.sent_recipients() == []


def test_manual_run_uses_a_fresh_slot(make_services):
    """Send now ignores the scheduled slot's ledger and names its own slot."""
    services = make_services()
    run_record(scheduled(), services)
    services.mailer.sent_messages.clear()

    report = run_record(RunRequest(record_id=RECORD_ID, manual=True), services)
    assert report.slot == 'manual-20261004T220000Z'
    assert services.mailer.sent_recipients() == RECIPIENTS
    assert services.store.ledgers[(RECORD_ID, report.slot)]['kind'] == 'manual'


def test_every_recipient_failing_is_failed(make_services):
    """When nobody is sent, the outcome is `failed` and the exit is non-zero."""
    services = make_services(failing_recipients=RECIPIENTS)
    report = run_record(scheduled(), services)
    assert report.outcome == 'failed'
    assert report.exit_code == FAILURE_EXIT_CODE


# ---------------------------------------------------------------- #
# Test sends
# ---------------------------------------------------------------- #

def test_test_send_goes_to_one_address_and_leaves_no_trace(make_services):
    """A test send reaches only the admin, carries [TEST], writes no ledger and keeps last_run."""
    services = make_services()
    request = RunRequest(record_id=RECORD_ID, test_recipient='admin@example.test')
    report = run_record(request, services)

    assert report.exit_code == SUCCESS_EXIT_CODE
    assert services.mailer.sent_recipients() == ['admin@example.test']
    assert services.mailer.sent_messages[0]['Subject'].startswith('[TEST] ')
    assert services.store.ledgers == {}
    assert 'last_run' not in stored_record(services)

    # The archive sits under a test folder
    archived_paths = list(services.archive.objects)
    assert archived_paths[0].startswith(f'sent/{RECORD_ID}/test-20261004T220000Z/')


def test_test_send_ignores_the_delivery_window(make_services):
    """An inactive record can still be test-sent."""
    services = make_services({'status': 'inactive'})
    request = RunRequest(record_id=RECORD_ID, test_recipient='admin@example.test')
    report = run_record(request, services)
    assert services.mailer.sent_recipients() == ['admin@example.test']
    assert report.exit_code == SUCCESS_EXIT_CODE


# ---------------------------------------------------------------- #
# The delivery window
# ---------------------------------------------------------------- #

def test_missing_record_exits_cleanly(make_services):
    """A trigger that outlived its record exits 0 and sends nothing."""
    services = make_services()
    report = run_record(RunRequest(record_id='gone'), services)
    assert report.exit_code == SUCCESS_EXIT_CODE
    assert services.mailer.sent_recipients() == []


def test_inactive_record_sends_nothing(make_services):
    """A paused record's scheduled run does nothing."""
    services = make_services({'status': 'inactive'})
    report = run_record(scheduled(), services)
    assert report.exit_code == SUCCESS_EXIT_CODE
    assert services.mailer.sent_recipients() == []


def test_before_start_delivery_sends_nothing(make_services):
    """A run before start_delivery, in the record's timezone, waits."""
    services = make_services({'start_delivery': '2026-10-06'})
    report = run_record(scheduled(), services)
    assert report.reason == 'before start_delivery'
    assert services.mailer.sent_recipients() == []


def test_after_end_delivery_deletes_the_trigger_and_skips(make_services):
    """The first run after end_delivery deletes its own trigger and records `skipped`."""
    services = make_services({'end_delivery': '2026-10-04'})
    report = run_record(scheduled(), services)

    assert report.exit_code == SUCCESS_EXIT_CODE
    assert report.outcome == 'skipped'
    assert services.scheduler.deleted == [f'dispatch-{RECORD_ID}']
    assert services.scheduler.triggers == set()
    assert stored_record(services)['last_run']['outcome'] == 'skipped'
    assert services.mailer.sent_recipients() == []


def test_end_delivery_is_read_in_the_record_timezone(make_services):
    """22:00 UTC on 4 October is already 5 October in Melbourne, so end_delivery 5 October still sends."""
    services = make_services({'end_delivery': '2026-10-05'})
    report = run_record(scheduled(), services)
    assert report.outcome == 'sent'


# ---------------------------------------------------------------- #
# Failures
# ---------------------------------------------------------------- #

def test_a_failing_section_fails_the_run(make_services):
    """A section that raises stops the run before anything is sent, and exits non-zero."""
    services = make_services()
    template = services.store.templates['probe_brief']
    template['sections'][1]['params']['fail'] = True

    report = run_record(scheduled(), services)
    assert report.exit_code == FAILURE_EXIT_CODE
    assert report.outcome == 'failed'
    assert services.mailer.sent_recipients() == []
    assert stored_record(services)['last_run']['outcome'] == 'failed'
    assert 'probe section was told to fail' in stored_record(services)['last_run']['error']


def test_published_template_with_publish_time_runs(make_services):
    """A template document carrying publish-templates' `published_at` still loads and sends."""
    services = make_services()
    template = services.store.templates['probe_brief']
    template['published_at'] = '2026-10-03T00:00:00+00:00'

    report = run_record(scheduled(), services)
    assert report.exit_code == SUCCESS_EXIT_CODE
    assert report.outcome == 'sent'


def test_schema_version_mismatch_fails(make_services):
    """A record saved against another schema version is refused."""
    services = make_services({'template_schema_version': 2})
    report = run_record(scheduled(), services)
    assert report.exit_code == FAILURE_EXIT_CODE
    assert 'schema version' in report.reason


def test_invalid_property_values_fail(make_services):
    """A state record without a state is refused before any data is read."""
    services = make_services({'property_values': {
        'start_date': '2026-08-01', 'end_date': '2026-11-28', 'jurisdiction': 'state',
    }})
    report = run_record(scheduled(), services)
    assert report.exit_code == FAILURE_EXIT_CODE
    assert '"state" is required' in report.reason


# ---------------------------------------------------------------- #
# Archive order and contents
# ---------------------------------------------------------------- #

def test_sign_happens_before_upload(make_services):
    """The browser link is signed before any object is uploaded."""
    services = make_services()
    run_record(scheduled(), services)

    events = services.archive.events
    assert events[0] == ('sign', f'sent/{RECORD_ID}/{SLOT}/{BROWSER_FILE_NAME}')
    for kind, _path in events[1:]:
        assert kind == 'upload'


def test_archive_holds_both_renders_and_every_chart(make_services):
    """email.html, browser.html and one PNG per probe section are archived."""
    services = make_services()
    run_record(scheduled(), services)

    prefix = f'sent/{RECORD_ID}/{SLOT}/'
    assert sorted(services.archive.objects) == [
        prefix + 'browser.html',
        prefix + 'email.html',
        prefix + 'participants-bar.png',
        prefix + 'statewide-bar.png',
    ]
