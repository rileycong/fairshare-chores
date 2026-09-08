from django.contrib import admin

from .models import (
    Chore,
    HistoryRecord,
    Household,
    PushSubscription,
    Roommate,
    SwapRequest,
    Supply,
)


@admin.register(Household)
class HouseholdAdmin(admin.ModelAdmin):
    list_display = ("join_code", "created_at")


@admin.register(Roommate)
class RoommateAdmin(admin.ModelAdmin):
    list_display = ("display_name", "household", "whatsapp_number", "created_at")
    list_filter = ("household",)


@admin.register(Chore)
class ChoreAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "household",
        "assignee",
        "effort",
        "recurrence_kind",
        "reminder_time",
        "due_at",
        "status",
    )
    list_filter = ("household", "status", "effort")


@admin.register(SwapRequest)
class SwapRequestAdmin(admin.ModelAdmin):
    list_display = ("chore", "requested_by", "target", "status", "created_at")
    list_filter = ("status",)


@admin.register(Supply)
class SupplyAdmin(admin.ModelAdmin):
    list_display = ("name", "household", "restocked", "created_at")
    list_filter = ("household",)


@admin.register(HistoryRecord)
class HistoryRecordAdmin(admin.ModelAdmin):
    list_display = ("chore", "assignee", "effort_points", "due_at", "completed_at", "swapped")


@admin.register(PushSubscription)
class PushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("roommate", "endpoint", "created_at")
