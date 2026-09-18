# ADR-007 - Cargon as Presentation Layer, Not Domain Architecture

## Context

Rotta will use the Cargon Logistics Cargo Transport Django Template as its official visual layer, but the template is not available in this first stage.

## Decision

Do not build a substitute dashboard. Keep only a temporary minimal page and later adapt Cargon as the presentation layer.

## Consequences

No time is spent on throwaway UI. Cargon will provide visual identity, while Rotta's domain, application, RBAC, audit, and organizational architecture remain independent.
## Implementation Status — 2026-08-22

Cargon is integrated as the Rotta 116 public presentation adapter. Public-template content must reflect the actual platform state without moving business rules into the presentation layer.
