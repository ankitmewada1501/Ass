from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from rest_framework import viewsets

from apps.core.permissions import IsAdminOrReadOnly

from .models import CentreTest, DiagnosticCentre, DiagnosticTest
from .serializers import CentreTestSerializer, DiagnosticCentreSerializer, DiagnosticTestSerializer


class CatalogPermissionMixin:
    """Catalogue reads are public; writes require a staff JWT."""

    permission_classes = [IsAdminOrReadOnly]


class DiagnosticTestViewSet(CatalogPermissionMixin, viewsets.ModelViewSet):
    """Global catalogue of test types. `?search=` filters by name or code."""

    serializer_class = DiagnosticTestSerializer
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = DiagnosticTest.objects.all()
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(code__iexact=search))
        return qs


class DiagnosticCentreViewSet(CatalogPermissionMixin, viewsets.ModelViewSet):
    """
    Diagnostic centres with the tests they offer.

    Filters: `?city=`, `?test=<test id>` (centres offering that test), `?search=` (name).
    DELETE deactivates the centre rather than removing it, so past bookings remain valid.
    """

    serializer_class = DiagnosticCentreSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = DiagnosticCentre.objects.prefetch_related(
            Prefetch(
                "offerings",
                queryset=CentreTest.objects.filter(is_active=True).select_related("test"),
                to_attr="active_offerings",
            )
        )
        if not (self.request.user.is_staff and self.request.query_params.get("include_inactive")):
            qs = qs.filter(is_active=True)

        params = self.request.query_params
        if city := params.get("city"):
            qs = qs.filter(city__iexact=city)
        if search := params.get("search"):
            qs = qs.filter(name__icontains=search)
        if test_id := params.get("test"):
            if test_id.isdigit():
                qs = qs.filter(offerings__test_id=test_id, offerings__is_active=True).distinct()
            else:
                qs = qs.none()
        return qs

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=["is_active", "updated_at"])


class CentreTestViewSet(CatalogPermissionMixin, viewsets.ModelViewSet):
    """Tests offered by one centre (`/centres/{centre_id}/tests/`) with their prices."""

    serializer_class = CentreTestSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_centre(self):
        if not hasattr(self, "_centre"):
            self._centre = get_object_or_404(DiagnosticCentre, pk=self.kwargs["centre_pk"], is_active=True)
        return self._centre

    def get_queryset(self):
        qs = CentreTest.objects.filter(centre=self.get_centre()).select_related("test")
        if not self.request.user.is_staff:
            qs = qs.filter(is_active=True)
        return qs

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if "centre_pk" in self.kwargs:
            context["centre"] = self.get_centre()
        return context

    def perform_create(self, serializer):
        serializer.save(centre=self.get_centre())

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=["is_active", "updated_at"])
