"""
The Dispatch Record: one admin's schedule for one template, with its property
values, recipients, schedule and delivery window.

The API writes these documents (`dispatch_records/<id>`). The job reads them
and writes back only `last_run`.
"""

import datetime
import zoneinfo
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from dispatch.config import MAX_RECIPIENTS


# ---------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------- #

# Day names a weekly schedule may hold
WEEKDAY_NAMES = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')

# The outcomes a run can end with
RUN_OUTCOMES = ('sent', 'partial', 'failed', 'skipped')


# ---------------------------------------------------------------- #
# Schedule and last run
# ---------------------------------------------------------------- #

class Schedule(BaseModel):
    """The schedule preset an admin chose: daily, or weekly on some days, at a time."""

    model_config = ConfigDict(extra='ignore')

    preset: Literal['daily', 'weekly']
    days: list[Literal['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']] = Field(default_factory=list)
    time: str = Field(pattern=r'^([01][0-9]|2[0-3]):(00|15|30|45)$')


class LastRun(BaseModel):
    """What the most recent scheduled or manual run did."""

    model_config = ConfigDict(extra='ignore')

    slot: Optional[str] = None
    at: Optional[Any] = None
    outcome: Literal['sent', 'partial', 'failed', 'skipped']
    error: Optional[str] = None
    recipient_count: int = 0
    failed_recipients: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- #
# The record
# ---------------------------------------------------------------- #

class DispatchRecord(BaseModel):
    """A Dispatch Record as stored in Firestore, plus its document id."""

    model_config = ConfigDict(extra='ignore')

    id: str
    name: str
    template_id: str
    template_schema_version: int
    property_values: dict = Field(default_factory=dict)
    recipients: list[str]
    contact_email: Optional[str] = None
    schedule: Optional[Schedule] = None
    cron: str
    timezone: str
    start_delivery: datetime.date
    end_delivery: datetime.date
    status: Literal['active', 'inactive']
    scheduler_job: Optional[str] = None
    scheduler_error: Optional[str] = None
    last_run: Optional[LastRun] = None
    created_at: Optional[Any] = None
    created_by: Optional[str] = None
    updated_at: Optional[Any] = None
    updated_by: Optional[str] = None

    @field_validator('recipients')
    @classmethod
    def check_recipient_count(cls, recipients):
        """A record holds between one and fifty recipients."""
        if len(recipients) == 0:
            raise ValueError('a record needs at least one recipient')
        if len(recipients) > MAX_RECIPIENTS:
            raise ValueError(f'a record may hold at most {MAX_RECIPIENTS} recipients, got {len(recipients)}')
        return recipients

    @field_validator('timezone')
    @classmethod
    def check_timezone(cls, timezone_name):
        """The timezone must be a real IANA zone name."""
        try:
            zoneinfo.ZoneInfo(timezone_name)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f'unknown timezone "{timezone_name}"') from error
        return timezone_name

    def contact(self):
        """The address unsubscribe requests go to: the contact email, or the record's creator."""
        if self.contact_email:
            return self.contact_email
        return self.created_by

    def zone(self):
        """The record's timezone as a ZoneInfo."""
        return zoneinfo.ZoneInfo(self.timezone)

    def local_today(self, now):
        """Today's date in the record's own timezone, for an aware `now`."""
        local_now = now.astimezone(self.zone())
        return local_now.date()

    def trigger_name(self):
        """The Cloud Scheduler job name that fires this record."""
        return f'dispatch-{self.id}'
