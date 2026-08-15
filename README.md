# Rotta

Rotta is a digital platform for transport and logistics. It is not only an administrative system for a transport company; it is the foundation for a broader logistics ecosystem connecting demand, cargo, transport capacity, drivers, vehicles, transport companies, logistics professionals, and customers.

The project is currently in the technical foundation phase. The roadmap includes transport contracting, loads, services, drivers, motorcycle couriers, vehicles, transport companies, independent partners, logistics professionals, customers, operational management, marketplace capabilities, tracking, billing, payments, settlements, recurrence, mobile operations, company APIs, and operational intelligence.

## Current Project Status

Implemented currently:

- Django foundation.
- PostgreSQL-ready configuration.
- Custom `User` with UUID primary key.
- Organizations and memberships.
- RBAC.
- Organizational scopes.
- Append-only audit foundation.
- Request ID correlation.
- Tests.
- Architectural documentation.

Not implemented yet:

- Cargon integration.
- NexaDash integration.
- Drivers.
- Vehicles.
- Loads.
- Shipments.
- Marketplace.
- Tracking.
- Financial workflows.
- Mobile app.
- Production API.

## Product Vision

Rotta should connect:

```text
logistics demand
+
loads
+
transport capacity
+
drivers
+
vehicles
+
transport companies
```

The goal is to allow customers to request transport while the platform finds, allocates, and operates compatible resources to execute the service.

Rotta must support owned operations for an established transport company and progressively evolve toward marketplace and integration models across the logistics ecosystem.

## Product Benchmark

Rotta uses Lalamove as a product and UX benchmark, not as a product to be copied.

Conceptual references include:

- Fast transport requests.
- On-demand experience.
- Vehicle selection.
- Matching between demand and driver.
- Driver mobile experience.
- Tracking.
- Scheduling.
- Multiple stops.
- Notifications.
- Customer follow-up.
- Enterprise API integrations.

Rotta must not copy Lalamove's brand, name, visual identity, text, layouts, code, assets, proprietary implementation, or protected proprietary flows.

The reference is behavioral, conceptual, operational, and UX-oriented. Rotta will have its own architecture, visual identity, business rules, and implementation.

## Client Experiences

### Rotta Web

Template: Cargon

Objective: public site, portal, and web experiences related to transport, services, loads, search, and customers.

### Rotta Backoffice

Template: NexaDash

Objective: administrative and operational center.

NexaDash should later support dashboard, operations, loads, transports, drivers, vehicles, customers, organizations, financial workflows, billing, users, RBAC, audit, reports, and settings.

### Rotta Mobile

Technology: Flutter / Dart

Platforms:

- Android.
- iOS.

The mobile app should be especially suited to field operations and driver workflows.

## Presentation Adapter Rule

Cargon, NexaDash, and Flutter are presentation adapters / client interfaces.

They do not own business rules and must not define or contaminate:

- `domain/`.
- `application/`.
- Use cases.
- Business rules.
- Authorization rules.
- Audit rules.

Rotta business architecture belongs to the Django backend, application layer, and domain model.

## General Architecture

```text
                    ROTTA PLATFORM
                           |
                  Django Backend / API
                           |
                      Application
                           |
                         Domain
                           |
                     Repositories
                           |
                       PostgreSQL

       +-------------------+-------------------+
       |                   |                   |
   Rotta Web         Rotta Backoffice     Rotta Mobile
    Cargon              NexaDash             Flutter
```

## Stack

### Backend

- Python 3.12+.
- Django 5.2.x.
- PostgreSQL.
- psycopg.
- django-environ.

### Architecture

- Hexagonal Architecture.
- Domain-Driven Design.
- Bounded contexts.
- UUID business identifiers.
- RBAC.
- Organizational scopes.
- Append-only audit trail.

### Quality

- pytest.
- pytest-django.
- Ruff.

### Web

- Cargon.
- Bootstrap.

### Backoffice

- NexaDash.
- Bootstrap 5.

### Mobile

- Flutter.
- Dart.
- Kotlin only when native Android integration is required.
- Swift only when native iOS integration is required.

## Hexagonal Architecture + DDD

Rotta follows a Hexagonal Architecture and DDD-oriented structure:

```text
Domain
    ↓
Application
    ↓
Ports
    ↓
Adapters / Infrastructure
```

Practical rules:

- The domain must not depend on Django views or templates.
- Business rules must not be scattered through templates.
- External integrations must be modeled as adapters.
- Bounded contexts must not couple to each other indiscriminately.
- Django is used as backend infrastructure, HTTP interface, persistence adapter, admin utility, and API provider.

Current bounded contexts live under `src/` and follow this convention:

- `domain`: domain concepts, enums, and future value objects/entities.
- `application`: use cases and application services.
- `infrastructure/django`: Django models, admin, middleware, persistence, and signals.
- `interfaces/http`: browser-oriented HTTP entrypoints when needed.
- `interfaces/api`: future versioned API entrypoints when real mobile or external integration behavior exists.

Do not create empty API structures only to make the architecture look complete.

## Current Bounded Contexts

### identity

- Custom `User`.
- UUID primary key.
- `Role`.
- `Permission`.
- `RolePermission`.
- `MembershipRole`.
- Authorization helpers.

### organizations

- `Organization`.
- `BusinessUnit`.
- `Branch`.
- `Department`.
- `Team`.
- `Membership`.

### audit

- `AuditLog`.
- Request correlation.
- Authentication events.
- Change tracking foundation.
- Secret sanitization.

### shared

- Shared domain and infrastructure concepts.
- UUID/timestamp base models.
- `AccessScope`.
- Request ID middleware.

## RBAC And Organizational Scopes

Current roles:

```text
SYSTEM_ADMIN
COMPANY_ADMIN
OPERATIONS_MANAGER
DISPATCHER
FINANCIAL_MANAGER
FINANCIAL_ANALYST
COMMERCIAL_MANAGER
SALESPERSON
DRIVER
CUSTOMER
AUDITOR
VIEWER
```

Current scopes:

```text
ALL
COMPANY
BRANCH
DEPARTMENT
TEAM
OWN
NONE
```

`Permission != Scope`.

A future example:

```text
customers.view
+
OWN
```

This means a user may view customers, but only within their own allowed data scope.

## Audit And Traceability

Rotta was designed with auditability from the foundation.

Current audit concepts:

```text
actor
organization
action
target_type
target_id
before
after
metadata
ip_address
user_agent
request_id
created_at
```

Rules:

- `AuditLog` is conceptually append-only.
- Secrets are sanitized.
- Passwords, tokens, API keys, and credentials must never be recorded.
- `request_id` allows technical correlation across request handling and audit records.

## API Strategy

Future mobile and external integration interfaces must use versioned APIs. The planned base path is:

```text
/api/v1/
```

Business endpoints are not implemented yet.

The API will later serve:

- Rotta Mobile.
- Enterprise integrations.
- Partners.
- External systems.
- Automations.

Web and backoffice experiences may use Django session authentication. Mobile will use API-specific authentication. Access/refresh token strategy will be evaluated when the API implementation phase begins.

Do not install JWT or token libraries before concrete API endpoints and authentication flows exist.

## Mobile Strategy

Flutter/Dart is the official technology decision for Rotta Mobile.

Future mobile capabilities may include:

- Android.
- iOS.
- GPS.
- Location.
- Camera.
- Proof-of-delivery uploads.
- Push notifications.
- Maps.
- Biometrics when applicable.
- Partial offline operation.
- Later synchronization.

These capabilities are not implemented yet.

Future device-related concepts should be modeled explicitly instead of being hidden inside user or driver records:

- `Device`.
- `DeviceSession`.
- `PushRegistration`.

## Offline-First Requirement

Offline-first behavior is especially important for driver workflows.

Conceptual flow:

```text
action on device
        ↓
local persistence / queue
        ↓
connectivity returns
        ↓
idempotent synchronization
        ↓
Rotta backend
```

Important concepts:

- `occurred_at`: when the event happened on the device.
- `received_at`: when the server received the event.
- `client_event_id`: future client-generated identifier used for idempotency and retry safety.

This distinction is especially important for transport status changes and tracking events.

## Future Tracking

Tracking must not be implemented as a simple pair of fields such as:

```text
Driver.latitude
Driver.longitude
```

The future model must support historical location records similar to:

```text
LocationPoint
driver
device
shipment
latitude
longitude
accuracy
speed
heading
occurred_at
received_at
```

No tracking code or models are implemented in this stage.

## Load x Shipment

`Load` represents cargo or a logistics need.

`Shipment` represents the operational execution of transport.

A `Load` may exist before a driver, vehicle, or confirmed operation exists.

These models are not implemented yet.

## Multi-Organization Foundation

Rotta is born prepared for multiple organizations.

Even if one transport company is the initial main operation, the architecture must not assume a single fixed transport company. Users relate to organizations through memberships, and access control can be scoped by organization and organizational structure.

## Roadmap

No dates are implied by this roadmap.

### Foundation — Current

- Identity.
- Organizations.
- RBAC.
- Scopes.
- Audit.
- Request ID.
- PostgreSQL foundation.

### Presentation

- Cargon integration.
- NexaDash integration.

### Core Logistics

- Drivers.
- Vehicles.
- Customers.
- Loads.
- Transport Requests.
- Quotations.
- Shipments.
- Stops.
- Operational Events.

### Mobile Operations

- Flutter application.
- Driver workflow.
- Device registration.
- Push.
- Offline sync.
- Proof of delivery.
- Location tracking.

### Marketplace

- Load search.
- Professional search.
- Vehicle search.
- Matching.
- Availability.
- Opportunities.

### Financial

- Billing.
- Receivables.
- Payables.
- Driver settlements.
- Payments.
- Subscriptions.
- Recurring charges.

### Intelligence

- Matching score.
- Suggested pricing.
- ETA.
- Route intelligence.
- Operational analytics.
- Future AI capabilities.

## Development

Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Copy `.env.example` to `.env` and set local values:

```bash
cp .env.example .env
```

Run Django checks:

```bash
.venv/bin/python manage.py check
```

Create migrations when models change:

```bash
.venv/bin/python manage.py makemigrations
```

Check whether migrations are up to date:

```bash
.venv/bin/python manage.py makemigrations --check
```

Apply migrations:

```bash
.venv/bin/python manage.py migrate
```

Run tests:

```bash
.venv/bin/pytest
```

Run Ruff:

```bash
.venv/bin/ruff check .
.venv/bin/ruff format .
```

## PostgreSQL

PostgreSQL is the official database.

The project is prepared for:

```text
DATABASE_URL=postgres://rotta@localhost:5432/rotta
```

Use `.env.example` as the reference for environment variables.

A permanent local environment may require PostgreSQL administrative setup for:

```text
role rotta
database rotta
```

Example SQL, to be run by a privileged PostgreSQL user if needed:

```sql
CREATE USER rotta;
CREATE DATABASE rotta OWNER rotta;
```

Do not invent or commit database passwords. SQLite is not the primary database for this project.

## ADRs

Architecture Decision Records live in `docs/adr/`.

Current ADRs:

- ADR-001 — Django + PostgreSQL.
- ADR-002 — Hexagonal Architecture + DDD.
- ADR-003 — Multi-organization from foundation.
- ADR-004 — Custom User from project start.
- ADR-005 — RBAC + organizational scopes.
- ADR-006 — Append-only audit trail.
- ADR-007 — Cargon as presentation layer, not domain architecture.
- ADR-008 — Flutter mobile.
- ADR-009 — Versioned API.
