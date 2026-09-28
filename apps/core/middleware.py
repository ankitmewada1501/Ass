import logging
import time
import uuid

logger = logging.getLogger("apps.request")


class RequestLoggingMiddleware:
    """Attach a request id and log one structured line per request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.request_id = request_id
        start = time.monotonic()
        response = self.get_response(request)
        response["X-Request-ID"] = request_id
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "duration_ms": round((time.monotonic() - start) * 1000, 2),
                "user_id": getattr(getattr(request, "user", None), "id", None),
            },
        )
        return response
