"""
Delete a record's own Cloud Scheduler trigger once its delivery window has
ended (decision D5). The API creates, updates and pauses triggers; the job
only ever deletes its own.

`SchedulerClient` is the seam: `CloudSchedulerClient` calls the REST API,
`FakeSchedulerClient` records calls for tests.
"""

from dispatch.config import PROJECT_ID, REGION


# ---------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------- #

# The Cloud Scheduler REST endpoint for jobs in the project's region
SCHEDULER_JOBS_URL = (
    f'https://cloudscheduler.googleapis.com/v1/projects/{PROJECT_ID}/locations/{REGION}/jobs'
)

# The status code for a trigger that is already gone
NOT_FOUND_STATUS = 404


# ---------------------------------------------------------------- #
# Clients
# ---------------------------------------------------------------- #

class SchedulerClient:
    """Deletes Cloud Scheduler triggers."""

    def delete_trigger(self, trigger_name):
        """Delete a trigger. Returns False when it was already gone; that is not an error."""
        raise NotImplementedError


class CloudSchedulerClient(SchedulerClient):
    """The Cloud Scheduler REST API, authorised with the job's default credentials."""

    def __init__(self, session=None):
        """Remember an authorised HTTP session, or make one on first use."""
        self.session = session

    def http(self):
        """An authorised session over the default credentials."""
        if self.session is None:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession

            credentials, _project = google.auth.default(
                scopes=['https://www.googleapis.com/auth/cloud-platform'],
            )
            self.session = AuthorizedSession(credentials)
        return self.session

    def delete_trigger(self, trigger_name):
        """Delete the trigger by name, treating a missing one as already deleted."""
        url = f'{SCHEDULER_JOBS_URL}/{trigger_name}'
        response = self.http().delete(url)

        if response.status_code == NOT_FOUND_STATUS:
            return False
        response.raise_for_status()
        return True


class FakeSchedulerClient(SchedulerClient):
    """Records deletions for tests."""

    def __init__(self, existing_triggers=()):
        """Start with some triggers in place."""
        self.triggers = set(existing_triggers)
        self.deleted = []

    def delete_trigger(self, trigger_name):
        """Remove the trigger if it exists, and note the call."""
        self.deleted.append(trigger_name)
        if trigger_name not in self.triggers:
            return False
        self.triggers.remove(trigger_name)
        return True
