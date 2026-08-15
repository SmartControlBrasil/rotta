# Rotta

Rotta is a web platform foundation for transport and logistics operations. It is intended to evolve into a TMS, load marketplace, driver and vehicle marketplace, fleet management platform, tracking layer, billing and payment operation, customer portal, driver mobile portal, and operational intelligence layer.

This first stage intentionally implements only the technical foundation: Django configuration, PostgreSQL readiness, hexagonal/DDD-oriented structure, identity, organizations, RBAC, organizational scopes, request traceability, audit logging, tests, and documentation.

## Stack

- Python 3.12+
- Django 5.x
- PostgreSQL
- psycopg 3
- django-environ
- pytest + pytest-django
- Ruff

## Architecture

The project treats Django mainly as infrastructure and HTTP interface. Bounded contexts live under `src/` and are organized around:

- `domain`: enums and future domain objects/value objects.
- `application`: use cases and application services.
- `infrastructure/django`: Django models, admin, middleware, persistence, and signals.
- `interfaces`: future HTTP/API entrypoints when needed.

Current bounded contexts:

- `identity`: custom user, roles, permissions, role permissions, membership role assignments, permission checks.
- `organizations`: organizations, business units, branches, departments, teams, memberships.
- `audit`: append-only audit log and authentication audit events.
- `shared`: UUID/timestamp base models, access scopes, request ID middleware.

Future bounded contexts documented for later phases:

- `drivers`
- `vehicles`
- `customers`
- `loads`
- `transport_requests`
- `quotations`
- `shipments`
- `tracking`
- `documents`
- `billing`
- `payments`
- `subscriptions`
- `notifications`
- `integrations`

Conceptually, a `Load` represents the cargo or logistics need. A `Shipment` represents operational execution of transport.

## Frontend Rule

The official presentation layer for Rotta will be the Cargon Logistics Cargo Transport Django Template. This repository currently includes only a temporary minimal page to validate the backend foundation. Cargon must be adapted as the presentation layer while preserving its visual identity, components, layouts, CSS, and JavaScript wherever possible.

Cargon must not dictate domain architecture. Domain, application, security, RBAC, audit, and organizational boundaries remain independent of the template.

## Environment

Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Copy `.env.example` to `.env` and set local values:

```bash
cp .env.example .env
```

## PostgreSQL

The application is prepared for:

```text
DATABASE_URL=postgres://rotta@localhost:5432/rotta
```

If the database/user do not exist locally, create them with a privileged PostgreSQL account:

```sql
CREATE USER rotta;
CREATE DATABASE rotta OWNER rotta;
```

No production credentials should be committed.

## Migrations

```bash
.venv/bin/python manage.py makemigrations
.venv/bin/python manage.py migrate
```

## Tests

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check
.venv/bin/python manage.py migrate
.venv/bin/pytest
```

## Decisions

- UUID is the primary key for business entities.
- `AUTH_USER_MODEL` is custom from the start.
- Organizations are multi-tenant/multi-organization from the foundation.
- Membership connects user to organization and optional business structure.
- RBAC separates role, permission, assignment, and organizational scope.
- Audit logs are append-only and sanitize sensitive payload keys.
- Request ID is generated or propagated for request traceability.
- Django Admin is enabled only as a technical/emergency tool, not Rotta's official backoffice.
