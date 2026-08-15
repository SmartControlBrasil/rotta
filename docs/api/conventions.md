# Rotta API Conventions

Rotta does not expose business APIs yet. This document records conventions for future mobile and external integration interfaces.

## Base URL

```text
/api/v1/
```

APIs must be versioned from the first production endpoint.

## Identifiers

Business resources use UUID identifiers.

## Dates And Times

Date/time values must use ISO 8601 with timezone information.

Use separate fields when the event happened at a different time from server receipt:

- `occurred_at`: when the event happened on the client/device.
- `received_at`: when Rotta received it.

## Error Format

Future API errors should follow this conceptual shape:

```json
{
  "error": {
    "code": "permission_denied",
    "message": "You do not have permission to perform this action.",
    "request_id": "uuid"
  }
}
```

Do not expose stack traces, secrets, tokens, database details, or internal settings.

## Pagination

Collection endpoints should use a consistent paginated response:

```json
{
  "count": 100,
  "next": "https://example.com/api/v1/resources/?page=2",
  "previous": null,
  "results": []
}
```

## Idempotency

Future command endpoints, especially mobile/offline commands, should support idempotency through one or both of:

```text
Idempotency-Key
client_event_id
```

Retries after network loss must not duplicate business effects.

## HTTP Status Codes

- `200`: successful read/update with response body.
- `201`: resource created.
- `204`: successful action with no response body.
- `400`: malformed request.
- `401`: authentication required or invalid credentials.
- `403`: authenticated but not authorized.
- `404`: resource not found or not visible within scope.
- `409`: conflict with current state or idempotency conflict.
- `422`: semantic validation error, if consciously adopted by the API layer.
- `429`: rate limit exceeded.
- `500`: unexpected server error.
