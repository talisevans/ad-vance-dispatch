"""
The run ledger: one document per record per slot
(`dispatch_records/<id>/runs/<slot>`), holding each recipient's outcome.

A rerun of the same slot reads the ledger and sends only to recipients not
already marked `sent`, which is what makes a Scheduler retry safe.
"""

import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from dispatch.config import LEDGER_RETENTION_DAYS


# ---------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------- #

# A recipient's status in the ledger
SENT_STATUS = 'sent'
FAILED_STATUS = 'failed'


# ---------------------------------------------------------------- #
# Models
# ---------------------------------------------------------------- #

class RecipientOutcome(BaseModel):
    """What happened when one recipient was sent this slot's email."""

    model_config = ConfigDict(extra='ignore')

    status: Literal['sent', 'failed']
    message_id: Optional[str] = None
    error: Optional[str] = None


class RunLedger(BaseModel):
    """The ledger for one slot of one record."""

    model_config = ConfigDict(extra='ignore')

    slot: str
    kind: Literal['scheduled', 'manual']
    started_at: datetime.datetime
    finished_at: Optional[datetime.datetime] = None
    as_of: Optional[str] = None
    outcome: Optional[Literal['sent', 'partial', 'failed', 'skipped']] = None
    recipients: dict[str, RecipientOutcome] = Field(default_factory=dict)
    archive_prefix: Optional[str] = None
    expire_at: datetime.datetime

    @classmethod
    def start(cls, slot, kind, started_at, as_of, archive_prefix):
        """A fresh ledger for a slot, expiring after the retention period."""
        expire_at = started_at + datetime.timedelta(days=LEDGER_RETENTION_DAYS)
        return cls(
            slot=slot,
            kind=kind,
            started_at=started_at,
            as_of=as_of,
            archive_prefix=archive_prefix,
            expire_at=expire_at,
        )

    def already_sent(self, recipient):
        """Whether this recipient has already been sent this slot's email."""
        outcome = self.recipients.get(recipient)
        if outcome is None:
            return False
        return outcome.status == SENT_STATUS

    def recipients_to_send(self, recipients):
        """The recipients from a list who are not yet marked sent, in list order."""
        pending = []
        for recipient in recipients:
            if self.already_sent(recipient):
                continue
            pending.append(recipient)
        return pending
