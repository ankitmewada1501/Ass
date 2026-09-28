from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.catalog.models import CentreTest, DiagnosticCentre, DiagnosticTest

TESTS = [
    ("CBC", "Complete Blood Count", "Measures red cells, white cells and platelets."),
    ("LFT", "Liver Function Test", "Enzymes and proteins indicating liver health."),
    ("TSH", "Thyroid Stimulating Hormone", "Screens for thyroid disorders."),
    ("HBA1C", "HbA1c", "Average blood sugar over the last 3 months."),
    ("MRI-BRAIN", "MRI Brain", "Magnetic resonance imaging of the brain."),
]

CENTRES = [
    ("EVE Diagnostics Koramangala", "80 Feet Rd, Koramangala", "Bengaluru", "560034",
     {"CBC": "350.00", "LFT": "650.00", "TSH": "400.00", "HBA1C": "550.00"}),
    ("EVE Diagnostics Indiranagar", "100 Feet Rd, Indiranagar", "Bengaluru", "560038",
     {"CBC": "380.00", "TSH": "420.00", "MRI-BRAIN": "6500.00"}),
    ("EVE Diagnostics Andheri", "Link Rd, Andheri West", "Mumbai", "400053",
     {"CBC": "400.00", "LFT": "700.00", "HBA1C": "600.00", "MRI-BRAIN": "7200.00"}),
]


class Command(BaseCommand):
    help = "Seed sample diagnostic tests and centres (idempotent)."

    @transaction.atomic
    def handle(self, *args, **options):
        tests = {}
        for code, name, description in TESTS:
            tests[code], _ = DiagnosticTest.objects.update_or_create(
                code=code, defaults={"name": name, "description": description}
            )
        for name, address, city, pincode, prices in CENTRES:
            centre, _ = DiagnosticCentre.objects.update_or_create(
                name=name, city=city, defaults={"address": address, "pincode": pincode}
            )
            for code, price in prices.items():
                CentreTest.objects.update_or_create(
                    centre=centre, test=tests[code], defaults={"price": Decimal(price), "is_active": True}
                )
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(TESTS)} tests and {len(CENTRES)} centres."))
