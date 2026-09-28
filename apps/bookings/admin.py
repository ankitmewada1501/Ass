from django.contrib import admin

from .models import Booking


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "centre", "test", "appointment_at", "amount", "status"]
    list_filter = ["status", "centre"]
    search_fields = ["user__email"]
    raw_id_fields = ["user"]
