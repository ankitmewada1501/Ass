from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler


class Conflict(APIException):
    """The request is valid but conflicts with the current state of a resource."""

    status_code = 409
    default_detail = "Request conflicts with the current state of the resource."
    default_code = "conflict"


def api_exception_handler(exc, context):
    """Wrap every DRF error in a consistent envelope: {"error": {code, message, details}}."""
    response = exception_handler(exc, context)
    if response is None:
        return None

    data = response.data
    if isinstance(data, dict) and set(data) == {"detail"}:
        message, details = str(data["detail"]), None
    else:
        message, details = "Invalid request.", data
    code = getattr(exc, "default_code", "error")
    if hasattr(exc, "get_codes"):
        codes = exc.get_codes()
        if isinstance(codes, str):
            code = codes
    response.data = {"error": {"code": code, "message": message, "details": details}}
    return response
