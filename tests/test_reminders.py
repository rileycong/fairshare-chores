from datetime import datetime, timezone as dt_timezone

import pytest
from django.core.management import call_command
from django.utils import timezone

from .test_services import make_chore, make_household, make_roommate


def at(hour, minute, day=8):
    return datetime(2026, 9, day, hour, minute, tzinfo=dt_timezone.utc)


@pytest.fixture
def clock(monkeypatch):
    class Clock:
        def __init__(self):
            self.now = at(9, 0)

        def set(self, value):
            self.now = value

        def __call__(self):
            return self.now

    clock = Clock()
    monkeypatch.setattr("django.utils.timezone.now", clock)
    return clock


@pytest.fixture
def sent(monkeypatch):
    calls = []

    def fake_notify(roommate, title, body):
        calls.append((roommate, title, body))

    monkeypatch.setattr(
        "chores.management.commands.send_reminders.notify_roommate", fake_notify
    )
    return calls


def make_chore_for_reminder(reminder_time="09:00", assignee=True, due_at=None):
    household = make_household()
    assignee = make_roommate(household, "Ada") if assignee else None
    chore = make_chore(household, assignee, name="Take out rubbish")
    h, m = map(int, reminder_time.split(":"))
    chore.reminder_time = datetime(2026, 1, 1, h, m).time()
    chore.due_at = due_at if due_at is not None else at(9, 0)
    chore.save()
    return chore, assignee


@pytest.mark.django_db
class TestSendReminders:
    def test_sends_for_matching_reminder_time_and_stamps(self, clock, sent):
        chore, ada = make_chore_for_reminder(reminder_time="09:00")

        call_command("send_reminders")

        assert len(sent) == 1
        assert sent[0][0] == ada
        assert "Take out rubbish" in sent[0][1]
        chore.refresh_from_db()
        assert chore.last_reminded_at is not None

    def test_skips_non_matching_times(self, clock, sent):
        make_chore_for_reminder(reminder_time="09:00")
        make_chore_for_reminder(reminder_time="14:30")

        clock.set(at(9, 0))
        call_command("send_reminders")

        assert len(sent) == 1

    def test_skips_unassigned_chores(self, clock, sent):
        make_chore_for_reminder(reminder_time="09:00", assignee=False)

        call_command("send_reminders")

        assert sent == []

    def test_second_run_in_same_minute_sends_nothing(self, clock, sent):
        make_chore_for_reminder(reminder_time="09:00")

        call_command("send_reminders")
        call_command("send_reminders")

        assert len(sent) == 1

    def test_stamp_is_stored_utc_and_repeatable_next_day(self, clock, sent):
        chore, _ = make_chore_for_reminder(reminder_time="09:00")

        clock.set(at(9, 0))
        call_command("send_reminders")
        chore.refresh_from_db()
        first_stamp = chore.last_reminded_at

        clock.set(at(14, 0))
        call_command("send_reminders")
        assert len(sent) == 1

        clock.set(at(9, 0, day=9))
        call_command("send_reminders")

        assert len(sent) == 2
        chore.refresh_from_db()
        assert chore.last_reminded_at > first_stamp
        assert timezone.is_aware(chore.last_reminded_at)

    def test_reminder_uses_notification_layer_for_assignee_only(self, clock, sent):
        household = make_household()
        ada = make_roommate(household, "Ada")
        ben = make_roommate(household, "Ben", "+15550002")
        chore = make_chore(household, ada, name="Mop floor")
        chore.reminder_time = datetime(2026, 1, 1, 9, 0).time()
        chore.due_at = at(9, 0)
        chore.save()
        other = make_chore(household, ben, name="Other chore")
        other.reminder_time = datetime(2026, 1, 1, 14, 30).time()
        other.save()

        call_command("send_reminders")

        assert len(sent) == 1
        assert sent[0][0] == ada
        assert "Mop floor" in sent[0][1]

    def test_output_reports_count(self, clock, sent, capsys):
        make_chore_for_reminder(reminder_time="09:00")

        call_command("send_reminders")

        assert "sent 1 reminder(s)" in capsys.readouterr().out
