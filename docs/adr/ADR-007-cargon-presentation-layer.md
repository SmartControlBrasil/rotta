# ADR-007 - Cargon as Presentation Layer, Not Domain Architecture

## Context

Rotta will use the Cargon Logistics Cargo Transport Django Template as its official visual layer, but the template is not available in this first stage.

## Decision

Do not build a substitute dashboard. Keep only a temporary minimal page and later adapt Cargon as the presentation layer.

## Consequences

No time is spent on throwaway UI. Cargon will provide visual identity, while Rotta's domain, application, RBAC, audit, and organizational architecture remain independent.
