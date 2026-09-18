# ADR-002 - Hexagonal Architecture + DDD

## Context

Rotta will grow into multiple bounded contexts such as identity, organizations, drivers, vehicles, loads, shipments, billing, and tracking.

## Decision

Organize code by bounded context with domain, application, infrastructure, and interface layers. Django models and middleware live in infrastructure.

## Consequences

The domain stays less coupled to Django views and templates. Some Django conventions are adapted, but the codebase remains easier to evolve by business capability.

## Implementation Status — 2026-08-22

The bounded-context/application-service structure is active across identity, organizations, supply-side, freight marketplace and operational execution. Presentation adapters remain outside domain ownership.
