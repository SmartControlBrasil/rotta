import uuid

from .logging import reset_request_id, set_request_id


class RequestIDMiddleware:
    header_name = "HTTP_X_REQUEST_ID"
    response_header = "X-Request-ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = self._request_id_from_header(request) or str(uuid.uuid4())
        token = set_request_id(request.request_id)
        try:
            response = self.get_response(request)
        finally:
            reset_request_id(token)
        response[self.response_header] = request.request_id
        return response

    def _request_id_from_header(self, request) -> str | None:
        incoming_request_id = request.META.get(self.header_name, "")
        try:
            return str(uuid.UUID(incoming_request_id))
        except (TypeError, ValueError, AttributeError):
            return None
