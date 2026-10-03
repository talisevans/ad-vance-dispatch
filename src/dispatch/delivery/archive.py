"""
Archive each run's renders and charts, and sign the browser link (D24, D27).

Layout in `gs://advance_dispatch`:

    sent/<record_id>/<slot>/email.html
    sent/<record_id>/<slot>/browser.html
    sent/<record_id>/<slot>/<content_id>.png

The order is fixed: sign the browser link first, then upload, then send. A
V4 signed URL can be made before its object exists, and signing first means a
signing failure stops the run before anything is uploaded or sent.

Cloud Run credentials hold no private key, so signing goes through the IAM
`signBlob` API: the job passes its service account email and an access token
to `generate_signed_url`. The service account needs
`roles/iam.serviceAccountTokenCreator` on itself.
"""

import datetime

from dispatch.config import ARCHIVE_PREFIX, DISPATCH_BUCKET, JOB_SERVICE_ACCOUNT, PROJECT_ID, SIGNED_URL_DAYS


# ---------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------- #

EMAIL_FILE_NAME = 'email.html'
BROWSER_FILE_NAME = 'browser.html'

HTML_CONTENT_TYPE = 'text/html; charset=utf-8'
PNG_CONTENT_TYPE = 'image/png'

# How long the browser link works
SIGNED_URL_LIFETIME = datetime.timedelta(days=SIGNED_URL_DAYS)


# ---------------------------------------------------------------- #
# Paths
# ---------------------------------------------------------------- #

def archive_prefix(record_id, slot):
    """The archive folder for one record's slot, ending in a slash."""
    return f'{ARCHIVE_PREFIX}{record_id}/{slot}/'


def archive_slot_for_test(now_utc):
    """The archive folder name for a test send, as in `test-20261003T091500Z`."""
    stamp = now_utc.strftime('%Y%m%dT%H%M%SZ')
    return f'test-{stamp}'


# ---------------------------------------------------------------- #
# Stores
# ---------------------------------------------------------------- #

class ArchiveStore:
    """Uploads archive objects and signs links to them."""

    def signed_url(self, object_path, lifetime):
        """Return a V4 signed GET link to an object, valid for `lifetime`."""
        raise NotImplementedError

    def upload(self, object_path, data, content_type):
        """Write one object."""
        raise NotImplementedError


class GcsArchiveStore(ArchiveStore):
    """The Dispatch bucket, signing through IAM signBlob."""

    def __init__(self, storage_client=None, bucket_name=DISPATCH_BUCKET,
                 service_account_email=JOB_SERVICE_ACCOUNT):
        """Remember the bucket, the client and the account that signs."""
        self.storage_client = storage_client
        self.bucket_name = bucket_name
        self.service_account_email = service_account_email

    def client(self):
        """The storage client, created on first use."""
        if self.storage_client is None:
            from google.cloud import storage
            self.storage_client = storage.Client(project=PROJECT_ID)
        return self.storage_client

    def access_token(self):
        """A fresh access token from the job's default credentials."""
        import google.auth
        from google.auth.transport.requests import Request

        credentials, _project = google.auth.default(
            scopes=['https://www.googleapis.com/auth/cloud-platform'],
        )
        credentials.refresh(Request())
        return credentials.token

    def signed_url(self, object_path, lifetime):
        """Sign a V4 GET link through IAM signBlob."""
        bucket = self.client().bucket(self.bucket_name)
        blob = bucket.blob(object_path)
        return blob.generate_signed_url(
            version='v4',
            expiration=lifetime,
            method='GET',
            service_account_email=self.service_account_email,
            access_token=self.access_token(),
        )

    def upload(self, object_path, data, content_type):
        """Upload one object from bytes or text."""
        bucket = self.client().bucket(self.bucket_name)
        blob = bucket.blob(object_path)
        blob.upload_from_string(data, content_type=content_type)


class FakeArchiveStore(ArchiveStore):
    """An in-memory archive for tests."""

    def __init__(self):
        """Start empty, with no links signed."""
        self.objects = {}
        self.signed_paths = []
        self.events = []

    def signed_url(self, object_path, lifetime):
        """Return a recognisable fake link and note that signing happened."""
        self.signed_paths.append(object_path)
        self.events.append(('sign', object_path))
        days = lifetime.days
        return f'https://storage.example.test/{object_path}?expires_in_days={days}'

    def upload(self, object_path, data, content_type):
        """Keep the object in memory and note that uploading happened."""
        self.objects[object_path] = (data, content_type)
        self.events.append(('upload', object_path))


# ---------------------------------------------------------------- #
# Archiving a run
# ---------------------------------------------------------------- #

def sign_browser_url(store, prefix):
    """Sign the link to the browser copy, before anything is uploaded."""
    object_path = prefix + BROWSER_FILE_NAME
    return store.signed_url(object_path, SIGNED_URL_LIFETIME)


def upload_archive(store, prefix, rendered, images):
    """Upload the email copy, the browser copy and every chart PNG under the prefix."""
    store.upload(prefix + EMAIL_FILE_NAME, rendered.email_html, HTML_CONTENT_TYPE)
    store.upload(prefix + BROWSER_FILE_NAME, rendered.browser_html, HTML_CONTENT_TYPE)

    for content_id, image in images:
        store.upload(f'{prefix}{content_id}.png', image.png, PNG_CONTENT_TYPE)
