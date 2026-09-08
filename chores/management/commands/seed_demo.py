from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from chores.models import Chore, Household, Supply
from chores.services import pick_assignee

CHORE_SPECS = [
    ("Take out rubbish", "small", "daily", None, None, "09:00", -1, None),
    ("Clean bathroom", "large", "weekly", None, None, "18:00", 2, None),
    ("Buy toilet paper", "small", "weekly", None, None, "12:00", 3, "Toilet paper"),
    ("Vacuum lounge", "medium", "custom", 2, "weeks", "10:00", 5, None),
    ("Water plants", "small", "monthly", None, None, "08:00", 10, None),
]


class Command(BaseCommand):
    help = "Seed a demo household with roommates, chores, and supplies (idempotent)"

    def handle(self, *args, **options):
        household, created = Household.objects.get_or_create(
            join_code="DEMO01", defaults={"rotation_counter": 0}
        )
        if household.roommates.count() >= 3:
            self.stdout.write("Demo household already seeded; nothing to do.")
            return

        roommates = []
        for display_name, whatsapp_number in [
            ("Ada", "+15550001"),
            ("Ben", "+15550002"),
            ("Cal", "+15550003"),
        ]:
            roommate, _ = household.roommates.get_or_create(
                whatsapp_number=whatsapp_number,
                defaults={"display_name": display_name, "pin": ""},
            )
            if not roommate.pin:
                roommate.set_pin("1234")
                roommate.save()
            roommates.append(roommate)

        supplies = {}
        for supply_name in ("Dish soap", "Toilet paper"):
            supplies[supply_name], _ = Supply.objects.get_or_create(
                household=household, name=supply_name
            )

        now = timezone.now()
        for name, effort, kind, count, unit, reminder, offset_days, supply_name in CHORE_SPECS:
            if household.chores.filter(name=name).exists():
                continue
            Chore.objects.create(
                household=household,
                name=name,
                effort=effort,
                recurrence_kind=kind,
                custom_count=count,
                custom_unit=unit,
                reminder_time=reminder,
                assignee=pick_assignee(household),
                due_at=now + timedelta(days=offset_days),
                status=Chore.Status.ASSIGNED,
                supply=supplies.get(supply_name),
            )

        self.stdout.write(
            f"Demo household ready. Join code: {household.join_code} "
            f"(roommate PINs are 1234)."
        )
