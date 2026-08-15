# ADR-009 - Versioned API

## Context

Rotta will serve multiple clients: the Cargon web portal, the NexaDash backoffice, the Flutter mobile app, and future external integrations.

## Decision

Interfaces for mobile apps and external integrations must use versioned APIs. The planned initial base path is:

```text
/api/v1/
```

Do not implement fictional business endpoints only to fill the architecture.

## Consequences

API evolution can be managed deliberately without coupling mobile or integration clients to browser templates. Bounded contexts should add `interfaces/api` only when real API behavior exists, preserving the existing Hexagonal Architecture and DDD boundaries.
