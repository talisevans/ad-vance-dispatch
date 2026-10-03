"""
The job's entry point.

    python -m dispatch.main --record-id <id> [--manual] [--test-recipient <email>]

Cloud Scheduler passes `--record-id` only. The API passes `--manual` for
"Send now" and `--test-recipient` for "Send test to me". The process exits
with the run's exit code, so a failed or partial run fires the Cloud Run job
failure alert.

For a local run, set `DISPATCH_GOLD_DIR` (and optionally `DISPATCH_LOOKUPS_DIR`)
to read a parquet mirror instead of the buckets, and `--layout-dir` to read
layouts from the repository instead of the Dispatch bucket.

To render a Dispatch to disk with no cloud access at all (see `preview.py`):

    python -m dispatch.main --render-only --record-file <json> --data-dir <gold> [--lookups-dir <dir>] [--out out/]
"""

import argparse
import sys

from dispatch.data.gold import resolve_gold_source
from dispatch.delivery.archive import GcsArchiveStore
from dispatch.delivery.ses import SmtpMailer
from dispatch.preview import render_preview
from dispatch.render.layout import GcsLayoutStore, LocalLayoutStore
from dispatch.run import RunRequest, Services, run_record
from dispatch.scheduling.scheduler import CloudSchedulerClient
from dispatch.store.firestore import FirestoreDispatchStore


# ---------------------------------------------------------------- #
# Arguments
# ---------------------------------------------------------------- #

# Where a local render writes its files when no folder is given
DEFAULT_OUT_DIRECTORY = 'out'


def parse_arguments(arguments):
    """Read the command line. A normal run needs --record-id; a local render needs a record file and data."""
    parser = argparse.ArgumentParser(description='Build and send one Dispatch Record.')
    parser.add_argument('--record-id', default=None, help='The Dispatch Record to run.')
    parser.add_argument('--manual', action='store_true',
                        help='A "Send now" run: skip the delivery window and use a fresh slot.')
    parser.add_argument('--test-recipient', default=None,
                        help='A "Send test to me" run: send only to this address, with no ledger.')
    parser.add_argument('--layout-dir', default=None,
                        help='Read layouts from this directory instead of the Dispatch bucket.')

    # A local render: no Firestore, buckets or SES
    parser.add_argument('--render-only', action='store_true',
                        help='Render to disk with local fakes for Firestore, GCS and SES. Sends nothing.')
    parser.add_argument('--record-file', default=None,
                        help='With --render-only: a Dispatch Record as a JSON file.')
    parser.add_argument('--data-dir', default=None,
                        help='With --render-only: a local gold parquet directory.')
    parser.add_argument('--lookups-dir', default=None,
                        help='With --render-only: the lookup caches directory (default <data-dir>/lookups).')
    parser.add_argument('--out', default=DEFAULT_OUT_DIRECTORY,
                        help='With --render-only: where to write the files (default out/).')

    options = parser.parse_args(arguments)

    # A local render needs its record file and data; a normal run needs a record id
    if options.render_only:
        if options.record_file is None or options.data_dir is None:
            parser.error('--render-only needs --record-file and --data-dir')
    elif options.record_id is None:
        parser.error('--record-id is required')
    return options


# ---------------------------------------------------------------- #
# Services
# ---------------------------------------------------------------- #

def real_services(layout_directory):
    """The production services: Firestore, GCS, SES and Cloud Scheduler."""
    layouts = GcsLayoutStore()
    if layout_directory is not None:
        layouts = LocalLayoutStore(layout_directory)

    return Services(
        store=FirestoreDispatchStore(),
        layouts=layouts,
        gold_source=resolve_gold_source(),
        archive=GcsArchiveStore(),
        mailer=SmtpMailer(),
        scheduler=CloudSchedulerClient(),
    )


# ---------------------------------------------------------------- #
# Entry point
# ---------------------------------------------------------------- #

def main(arguments=None):
    """Run one record and return the exit code."""
    options = parse_arguments(arguments)

    # A local render writes files and sends nothing
    if options.render_only:
        preview = render_preview(options.record_file, options.data_dir, options.out, options.lookups_dir)
        return preview.report.exit_code

    request = RunRequest(
        record_id=options.record_id,
        manual=options.manual,
        test_recipient=options.test_recipient,
    )
    services = real_services(options.layout_dir)
    report = run_record(request, services)
    return report.exit_code


if __name__ == '__main__':
    sys.exit(main())
