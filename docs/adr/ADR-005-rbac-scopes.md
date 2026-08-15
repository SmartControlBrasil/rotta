# ADR-005 - RBAC + Organizational Scopes

## Context

Rotta needs access control beyond `is_staff`, including organization-specific roles and future data visibility scopes.

## Decision

Implement roles, permissions, role permissions, membership role assignments, and access scopes as separate concepts.

## Consequences

Permissions answer what a user may do. Scopes answer where or over which data that permission applies. This supports future filtering without inventing fake modules now.
