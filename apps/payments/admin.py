from django.contrib import admin

from .models import Payment, WebhookEvent


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ["provider_reference", "booking", "amount", "status", "created_at"]
    list_filter = ["status"]
    search_fields = ["provider_reference", "user__email"]


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ["event_id", "event_type", "payment", "status", "received_at"]
    list_filter = ["status", "event_type"]
    search_fields = ["event_id"]
