# ADR-004 - Custom User From Project Start

## Context

Django user model changes are expensive after migrations and relationships exist.

## Decision

Use a custom `AUTH_USER_MODEL` based on `AbstractUser` with UUID primary key from the beginning.

## Consequences

Authentication remains compatible with Django while allowing future identity evolution. Business rules are not concentrated inside the user model.
