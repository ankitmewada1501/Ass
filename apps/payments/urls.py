from django.urls import path

from .views import DevWebhookSimulateView, PaymentViewSet, PaymentWebhookView

payment_list = PaymentViewSet.as_view({"get": "list", "post": "create"})
payment_detail = PaymentViewSet.as_view({"get": "retrieve"})

urlpatterns = [
    path("", payment_list, name="payment-list"),
    path("webhook/", PaymentWebhookView.as_view(), name="payment-webhook"),
    path("dev/simulate-webhook/", DevWebhookSimulateView.as_view(), name="payment-dev-webhook"),
    path("<int:pk>/", payment_detail, name="payment-detail"),
]
