from django.contrib import admin

from .models import CentreTest, DiagnosticCentre, DiagnosticTest


class CentreTestInline(admin.TabularInline):
    model = CentreTest
    extra = 1


@admin.register(DiagnosticCentre)
class DiagnosticCentreAdmin(admin.ModelAdmin):
    list_display = ["name", "city", "is_active"]
    list_filter = ["city", "is_active"]
    search_fields = ["name"]
    inlines = [CentreTestInline]


@admin.register(DiagnosticTest)
class DiagnosticTestAdmin(admin.ModelAdmin):
    list_display = ["code", "name"]
    search_fields = ["code", "name"]
