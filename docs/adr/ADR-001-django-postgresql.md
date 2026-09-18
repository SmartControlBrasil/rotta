# ADR-001 - Django + PostgreSQL

## Context

Rotta needs a stable backend foundation for transport and logistics workflows, relational integrity, authentication, migrations, and operational administration.

## Decision

Use Django with PostgreSQL as the primary database. SQLite is not the main project database.

## Consequences

Django provides mature infrastructure for auth, migrations, admin, CSRF, sessions, and tests. PostgreSQL gives relational constraints and JSONB support for audit metadata.

## Implementation Status — 2026-08-22

Django 5.2.x and PostgreSQL remain the active backend/persistence decision. Current concurrency hardening relies on transactional database semantics.
