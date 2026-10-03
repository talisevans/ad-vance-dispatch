"""
Fixed names the Dispatch job reaches for: the project, buckets, secrets,
Firestore collections, the job itself, and the environment variables that
point a local run at a parquet mirror instead of the buckets.
"""

import os


# ---------------------------------------------------------------- #
# Project and region
# ---------------------------------------------------------------- #

# The one Google Cloud project every AdVance resource lives in
PROJECT_ID = 'advance-campaign-app'

# Where the job, its triggers and its image live
REGION = 'australia-southeast1'

# The Cloud Run job that builds and sends a Dispatch
JOB_NAME = 'advance-dispatch'

# The service account the job runs as, which also signs the browser links
JOB_SERVICE_ACCOUNT = f'advance-dispatch@{PROJECT_ID}.iam.gserviceaccount.com'


# ---------------------------------------------------------------- #
# Buckets
# ---------------------------------------------------------------- #

# The gold serving layer: seven parquet tables, hive-partitioned on cohort year
GOLD_BUCKET = 'advance_gold'

# The lookup caches sit under this prefix in the lookups bucket
LOOKUPS_BUCKET = 'advance_lookups'
LOOKUPS_PREFIX = 'caches/'

# Template layouts and the archive of every sent Dispatch
DISPATCH_BUCKET = 'advance_dispatch'
TEMPLATES_PREFIX = 'templates/'
ARCHIVE_PREFIX = 'sent/'


# ---------------------------------------------------------------- #
# Firestore
# ---------------------------------------------------------------- #

# Dispatch documents live in the default database
FIRESTORE_DATABASE = '(default)'

# One document per template, written only by publish-templates
TEMPLATES_COLLECTION = 'dispatch_templates'

# One document per Dispatch Record, written by the API and by this job's last_run
RECORDS_COLLECTION = 'dispatch_records'

# The per-slot ledger under each record
RUNS_SUBCOLLECTION = 'runs'

# Generated documents the MCP tools read
CATALOGUE_COLLECTION = 'dispatch_catalogue'
CATALOGUE_TEMPLATE_SCHEMA_DOCUMENT = 'template_schema'
CATALOGUE_SECTION_TYPES_DOCUMENT = 'section_types'


# ---------------------------------------------------------------- #
# Email
# ---------------------------------------------------------------- #

# The SES SMTP credentials secret: JSON with host, port, username and password
SES_SECRET_NAME = 'aws_ses'

# Every Dispatch is sent from this address
SENDER_ADDRESS = 'no-reply@talisevans.dev'
SENDER_DISPLAY_NAME = 'AdVance Dispatch'

# The domain message ids are minted under
MESSAGE_ID_DOMAIN = 'talisevans.dev'

# The most recipients one record may hold
MAX_RECIPIENTS = 50

# Prefix on the subject of a "Send test to me" email
TEST_SUBJECT_PREFIX = '[TEST] '


# ---------------------------------------------------------------- #
# Retention
# ---------------------------------------------------------------- #

# Ledger documents carry an expiry this many days after the run started
LEDGER_RETENTION_DAYS = 30

# The browser link lasts this long, which is the V4 signing maximum
SIGNED_URL_DAYS = 7


# ---------------------------------------------------------------- #
# Local overrides
# ---------------------------------------------------------------- #

# Read gold from this local directory instead of downloading it
GOLD_DIRECTORY_VARIABLE = 'DISPATCH_GOLD_DIR'

# Read the lookup caches from this local directory instead of downloading them
LOOKUPS_DIRECTORY_VARIABLE = 'DISPATCH_LOOKUPS_DIR'

# Where downloaded gold and caches land inside the container
DOWNLOAD_DIRECTORY_VARIABLE = 'DISPATCH_DOWNLOAD_DIR'
DEFAULT_DOWNLOAD_DIRECTORY = '/tmp/advance-dispatch'


def environment_value(name):
    """Return an environment variable's value, or None when it is unset or blank."""
    value = os.environ.get(name, '')
    stripped = value.strip()
    if stripped == '':
        return None
    return stripped
