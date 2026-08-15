# ADR-003 - Multi-Organization From Foundation

## Context

Rotta may initially operate with one transport company, but the product must support customers, partners, suppliers, fleet owners, and other organizations.

## Decision

Model organizations and memberships from the beginning instead of attaching each user irreversibly to one company.

## Consequences

Access control, audit records, and future workflows can be scoped by organization. The first phase has slightly more structure, but avoids a future tenant migration.
