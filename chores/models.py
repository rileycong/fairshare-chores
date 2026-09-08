from django.contrib.auth.hashers import check_password, make_password
from django.db import models


class Household(models.Model):
    join_code = models.CharField(max_length=8, unique=True)
    rotation_counter = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Household {self.join_code}"


class Roommate(models.Model):
    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="roommates"
    )
    display_name = models.CharField(max_length=80)
    pin = models.CharField(max_length=128)
    whatsapp_number = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["household", "whatsapp_number"],
                name="unique_whatsapp_per_household",
            )
        ]

    def __str__(self):
        return self.display_name

    def set_pin(self, raw_pin):
        self.pin = make_password(raw_pin)

    def check_pin(self, raw_pin):
        return check_password(raw_pin, self.pin)


class Supply(models.Model):
    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="supplies"
    )
    name = models.CharField(max_length=120)
    restocked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Chore(models.Model):
    class Effort(models.TextChoices):
        SMALL = "small", "Small"
        MEDIUM = "medium", "Medium"
        LARGE = "large", "Large"

    class Status(models.TextChoices):
        ASSIGNED = "assigned", "Assigned"
        SWAP_REQUESTED = "swap_requested", "Swap requested"
        OVERDUE = "overdue", "Overdue"

    class RecurrenceKind(models.TextChoices):
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"
        CUSTOM = "custom", "Custom"

    class CustomUnit(models.TextChoices):
        HOURS = "hours", "Hours"
        DAYS = "days", "Days"
        WEEKS = "weeks", "Weeks"
        MONTHS = "months", "Months"

    EFFORT_POINTS = {
        Effort.SMALL: 1,
        Effort.MEDIUM: 2,
        Effort.LARGE: 3,
    }

    household = models.ForeignKey(
        Household, on_delete=models.CASCADE, related_name="chores"
    )
    name = models.CharField(max_length=120)
    notes = models.TextField(blank=True)
    effort = models.CharField(
        max_length=10, choices=Effort.choices, default=Effort.MEDIUM
    )
    recurrence_kind = models.CharField(
        max_length=10, choices=RecurrenceKind.choices, default=RecurrenceKind.DAILY
    )
    custom_count = models.PositiveSmallIntegerField(null=True, blank=True)
    custom_unit = models.CharField(
        max_length=10, choices=CustomUnit.choices, null=True, blank=True
    )
    reminder_time = models.TimeField()
    assignee = models.ForeignKey(
        Roommate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chores",
    )
    due_at = models.DateTimeField()
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ASSIGNED
    )
    supply = models.ForeignKey(
        Supply,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="chores",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    @property
    def effort_points(self):
        return self.EFFORT_POINTS[self.effort]


class SwapRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        DECLINED = "declined", "Declined"

    chore = models.ForeignKey(
        Chore, on_delete=models.CASCADE, related_name="swap_requests"
    )
    requested_by = models.ForeignKey(
        Roommate, on_delete=models.CASCADE, related_name="swap_requests_sent"
    )
    target = models.ForeignKey(
        Roommate, on_delete=models.CASCADE, related_name="swap_requests_received"
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Swap {self.chore}: {self.requested_by} -> {self.target} ({self.status})"


class HistoryRecord(models.Model):
    chore = models.ForeignKey(
        Chore, on_delete=models.CASCADE, related_name="history_records"
    )
    assignee = models.ForeignKey(
        Roommate, on_delete=models.CASCADE, related_name="history_records"
    )
    effort_points = models.PositiveSmallIntegerField()
    due_at = models.DateTimeField()
    completed_at = models.DateTimeField()
    swapped = models.BooleanField(default=False)

    class Meta:
        ordering = ["-completed_at"]

    def __str__(self):
        return f"{self.chore} completed by {self.assignee}"


class PushSubscription(models.Model):
    roommate = models.ForeignKey(
        Roommate, on_delete=models.CASCADE, related_name="push_subscriptions"
    )
    endpoint = models.URLField(max_length=500, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Push for {self.roommate}"
