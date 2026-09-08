from django.core.management.base import BaseCommand
from django.utils import timezone

from chores.models import Chore
from chores.notifications import notify_roommate


class Command(BaseCommand):
    help = "Send chore reminders whose reminder time matches the current minute"

    def handle(self, *args, **options):
        now_local = timezone.localtime(timezone.now())
        current_minute = (now_local.hour, now_local.minute)
        sent = 0

        chores = Chore.objects.filter(assignee__isnull=False).select_related(
            "assignee", "household"
        )
        for chore in chores:
            reminder = chore.reminder_time
            if (reminder.hour, reminder.minute) != current_minute:
                continue
            if chore.last_reminded_at is not None:
                last_local = timezone.localtime(chore.last_reminded_at)
                if (
                    last_local.date(),
                    last_local.hour,
                    last_local.minute,
                ) == (now_local.date(), now_local.hour, now_local.minute):
                    continue
            notify_roommate(
                chore.assignee,
                f"Chore reminder: {chore.name}",
                f'"{chore.name}" is due {timezone.localtime(chore.due_at).strftime("%b %d at %H:%M")}.',
            )
            chore.last_reminded_at = timezone.now()
            chore.save(update_fields=["last_reminded_at"])
            sent += 1

        self.stdout.write(f"sent {sent} reminder(s)")
