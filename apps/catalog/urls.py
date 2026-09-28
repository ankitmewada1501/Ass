from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import CentreTestViewSet, DiagnosticCentreViewSet, DiagnosticTestViewSet

router = DefaultRouter()
router.register("centres", DiagnosticCentreViewSet, basename="centre")
router.register("tests", DiagnosticTestViewSet, basename="test")

offering_list = CentreTestViewSet.as_view({"get": "list", "post": "create"})
offering_detail = CentreTestViewSet.as_view({"get": "retrieve", "patch": "partial_update", "delete": "destroy"})

urlpatterns = router.urls + [
    path("centres/<int:centre_pk>/tests/", offering_list, name="centre-tests"),
    path("centres/<int:centre_pk>/tests/<int:pk>/", offering_detail, name="centre-test-detail"),
]
