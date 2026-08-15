import uuid


class RequestIDMiddleware:
    header_name = "HTTP_X_REQUEST_ID"
    response_header = "X-Request-ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming_request_id = request.META.get(self.header_name)
        request.request_id = incoming_request_id or str(uuid.uuid4())

        response = self.get_response(request)
        response[self.response_header] = request.request_id
        return response
