# Rotta 116 API Conventions

Rotta exposes versioned application APIs for the driver mobile application and customer-facing integrations. The current production contract starts under:

```text
/api/v1/
```

## Source Of Truth

API behavior is defined by the current URL/view/application-service implementation and its automated tests. This document describes cross-cutting conventions; endpoint-specific behavior lives in `docs/api/v1.md`.

## Identifiers

Business resources use UUID identifiers unless a legacy/internal model explicitly differs.

## Authentication

The current mobile API uses signed bearer/token authentication with explicit login, refresh and revoke endpoints.

Authentication proves identity; authorization remains RBAC/ownership/tenant-aware at the application boundary.

A valid driver token must never imply permission to operate another driver's freight operation.

## Dates And Times

Use ISO 8601 date/time values with timezone information.

When device time differs from server receipt time, retain both concepts when the model supports them:

- device/occurred/recorded timestamp: when the event happened at the source.
- server/received/created timestamp: when Rotta persisted/received it.

This is especially important for GPS and thermal telemetry.

## Error Format

API errors should follow the shared response helpers and expose stable machine-readable codes plus a safe user-facing message. Conceptually:

```json
{
  "error": {
    "code": "permission_denied",
    "message": "You do not have permission to perform this action.",
    "request_id": "uuid"
  }
}
```

Never expose stack traces, secrets, tokens, database internals or private configuration.

## HTTP Status Codes

Use status codes consistently:

- `200` successful read/idempotent action/update.
- `201` resource created.
- `204` successful action with no response body.
- `400` malformed request/body/parameters.
- `401` authentication required, invalid or expired credentials.
- `403` authenticated but unauthorized when revealing existence is acceptable.
- `404` resource not found **or intentionally hidden by ownership/tenant scope**.
- `409` state transition/idempotency/business conflict.
- `422` semantic validation only if consciously adopted by the interface.
- `429` rate limiting.
- `500` unexpected server error.

Driver-owned resource endpoints should generally fail closed without disclosing another driver's resources.

## Pagination

Collection endpoints that can grow materially should expose a consistent paginated representation. Do not introduce inconsistent pagination shapes between driver/customer APIs.

Conceptual form:

```json
{
  "count": 100,
  "next": "...",
  "previous": null,
  "results": []
}
```

## Idempotency

Mobile/offline commands must be retry-safe.

Preferred mechanisms depend on the domain:

- natural database uniqueness.
- `client_event_id`.
- monotonic/sample `sequence`.
- explicit idempotency key when no stable natural key exists.

Current examples:

- Selection → Operation uses the unique Selection/Operation relationship plus transactional locking.
- Location points use `client_event_id` and/or sequence; `recorded_at` alone is **not** an idempotency key.
- POD retries return the existing POD only when the repeated payload is materially equivalent; conflicting repeat payloads are rejected.
- Operational stop/status repeats should not duplicate business events.

Do not rely on application-level `exists()` checks alone for concurrent uniqueness.

## Concurrency

Critical state changes should use the transactional patterns appropriate to the aggregate:

- `transaction.atomic()`.
- `select_for_update()`.
- database unique constraints.
- `IntegrityError` recovery when a concurrent winner is a valid idempotent result.

Tests for concurrency-sensitive code should use real transactional database behavior.

## Multi-Tenancy And Ownership

Every organization-owned resource must be resolved in tenant/permission scope.

Driver mobile operations add a stricter ownership dimension: the authenticated driver's permissions apply only to operations assigned to that driver unless an explicit administrative path is used.

Never fetch a business resource by bare PK and authorize afterward when the scoped query can be applied up front.

## Operational State Machines

Clients do not own state transitions. They request actions/target transitions; the backend state machine validates them.

This applies to:

- FreightOperation status.
- FreightOperationStop execution status.
- TrackingSession lifecycle.
- selection/invitation/marketplace lifecycle.

`INCIDENT_REPORTED` is an operational event, not a FreightOperation status.

## Telemetry

GPS and temperature are independent telemetry domains.

GPS location points belong to `TrackingSession` / `FreightOperation`.

Thermal readings retain their own sensor metadata, timestamps, validity/quality and operation association. Do not add temperature fields to GPS points merely for convenience.

## Backward Compatibility

API changes must preserve existing mobile contracts when feasible. Additive fields are preferred to semantic changes.

For POD specifically, new code should reason in terms of multiple `operation.pods`. Legacy operation-level compatibility must not be interpreted as a guarantee that every operation has exactly one POD.
