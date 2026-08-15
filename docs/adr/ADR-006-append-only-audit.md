# ADR-006 - Append-Only Audit Trail

## Context

Operational and security events must be traceable without storing credentials or secrets.

## Decision

Create an `AuditLog` with actor, organization, action, target, before/after payloads, metadata, IP, user agent, request ID, and timestamp. Entries are append-only.

## Consequences

The system gains an early audit foundation. Edits and deletes are blocked in Django Admin, and service-level payload sanitization redacts sensitive keys.
