# Rotta 116

Rotta 116 is a digital transport and logistics platform designed to connect transport demand, carriers, drivers, vehicles and operational execution in a single domain model.

The project is no longer only a technical foundation. The current codebase already contains the marketplace flow, operational execution, driver mobile API, Flutter driver app, tracking, POD, refrigerated-cargo telemetry, multi-stop operations, fractional cargo modeling, organizational RBAC and the public/backoffice presentation layers.

> **Current code and automated tests are the primary source of truth.** Historical ADRs and discovery documents explain why decisions were made, but roadmap statements must not override implemented behavior.

## Current Project Status

Current verified development baseline from the latest project run:

```text
506 passed
0 failed
python manage.py check: no issues
python manage.py makemigrations --check: no changes detected
```

Major capabilities already implemented:

- Django 5.2.x backend with PostgreSQL.
- Hexagonal Architecture + DDD-oriented bounded contexts.
- Custom UUID `User`.
- Multi-organization memberships and organizational scopes.
- RBAC with dedicated operational permissions, including `DRIVER` capabilities.
- Append-only audit trail and request correlation.
- Customer, carrier, driver, vehicle and compliance domains.
- Freight request, stops, cargo profile and cargo lots.
- Quote and offer lifecycle.
- Marketplace matching, invitations, interest and selection.
- Atomic and idempotent `FreightOfferSelection → FreightOperation` materialization.
- `FreightOperation` state machine and immutable operational events.
- LTL/FTL support.
- Multi-stop operational snapshots.
- Fractional cargo lots linked to pickup and delivery stops.
- POD per delivery stop, while preserving legacy single-delivery compatibility.
- GPS tracking sessions, points, batch ingestion and retry-safe idempotency.
- Incident reporting without converting incidents into operation status.
- Refrigerated cargo profile and thermal telemetry separated from GPS.
- Driver preferences and route intents.
- `ContractedRoute` and `ContractedRouteOccurrence` domain modeling.
- Idempotent and thread-safe occurrence materialization into `FreightOperation`.
- Versioned `/api/v1/` driver and customer APIs.
- Flutter driver application under `apps/rotta_driver/`.
- Public site using Cargon as presentation adapter.
- Backoffice using NexaDash as presentation adapter.
- Customer portal for freight-request workflows.

Important domains that remain planned or incomplete:

- Automated scheduling background job / scheduler runner for occurrences.
- Advanced geographic matching using route direction, detour, return cost and historical affinity.
- Warehouse/storage operational workflows.
- Billing, marketplace commission, settlements and payments.
- Push/WebSocket real-time notifications.
- Advanced thermal alerting and external sensor/device integrations.
- Production hardening/deployment procedures and observability.

## Product Vision

Rotta 116 is intended to operate as both a logistics SaaS and a transport marketplace.

The core flow currently implemented is:

```text
FreightRequest
  → FreightQuote
  → FreightOffer
  → Matching
  → Invitation
  → Interest
  → Selection
  → FreightOperation
  → operational events / stops / tracking / incidents
  → ProofOfDelivery
  → DELIVERED
```

The platform must support simple point-to-point transport as well as multi-stop and fractional-cargo journeys.

Longer term, `FreightOperation` is expected to be the common execution aggregate for operations created by more than one commercial source:

```text
Marketplace Selection ───────┐
Contracted Route ─────────────┤
Enterprise API / Manual ──────┤→ FreightOperation

```

The marketplace path is implemented today. Recurring/contracted-route origin is the next architectural evolution and must not be simulated with fake marketplace records.

## Product Principles

### Operational truth over presentation

Business rules live in the backend domain/application layers. Cargon, NexaDash and Flutter are adapters; they do not define freight, matching, status, RBAC, tracking or POD rules.

### Geographic coherence

Matching and route evolution must avoid operationally incoherent sequences. Driver area of action, route direction, additional distance, return distance, journey time and historical affinity are first-class product concerns.

### Progressive driver autonomy

Drivers can maintain preferences and route intents. Future matching must use these preferences without allowing the mobile client to bypass backend rules.

### Multi-stop and fractional cargo are core capabilities

A freight operation is not restricted to `origin → destination`. The domain supports ordered pickup/delivery stops and cargo lots with explicit pickup and delivery relationships.

### Dry and refrigerated cargo share the operational core

Temperature telemetry is modeled separately from GPS tracking and is associated with the operation/cargo context rather than being embedded into location records.

## Client Experiences

### Rotta Web — Cargon

The public site presents Rotta 116, its logistics network, services and conversion paths. Cargon is a visual/presentation adapter only.

### Rotta Backoffice — NexaDash

The backoffice is the operational and administrative center for organizations, users, RBAC, customers, carriers, drivers, vehicles, compliance, freight requests, marketplace, operations, tracking, POD and reports.

### Rotta Customer Portal

Customer-facing web flows support freight-request creation, listing and detail views with organization-aware access control.

### Rotta Driver — Flutter

Location: `apps/rotta_driver/`

Technology:

- Flutter / Dart.
- Android first for operational rollout.
- iOS supported by the same application architecture.
- Package/application identifier: `br.com.rotta116.driver`.

The driver app is an API client. It must not duplicate backend business rules.

## General Architecture

```text
                         ROTTA 116
                            |
               Django Backend / Versioned API
                            |
                      Application Layer
                            |
                         Domain
                            |
               Infrastructure / Repositories
                            |
                       PostgreSQL

      +---------------------+----------------------+------------------+
      |                     |                      |                  |
 Public Web            Backoffice            Customer Portal    Driver Mobile
   Cargon               NexaDash                 Django             Flutter
```

## Stack

### Backend

- Python 3.12+
- Django 5.2.x
- PostgreSQL
- psycopg
- django-environ

### Architecture

- Hexagonal Architecture
- Domain-Driven Design
- Bounded contexts under `src/`
- UUID business identifiers
- Explicit application services
- Versioned API adapters
- Multi-organization RBAC/scopes
- Append-only audit

### Quality

- pytest
- pytest-django
- Ruff
- concurrency tests using real database transactions/threads for critical flows

### Presentation

- Cargon / Bootstrap for public site
- NexaDash / Bootstrap 5 for backoffice
- Flutter / Dart for driver mobile

## Project Structure

```text
src/
  identity/
  organizations/
  audit/
  customers/
  carriers/
  drivers/
  vehicles/
  compliance/
  freights/
  shared/

apps/
  rotta_driver/

templates/
  public/
  backoffice/
  customer/

docs/
  adr/
  api/
  audits/
  architecture/
  domain/

tests/
```

The exact internal folders vary by bounded context, but the intended dependency direction remains:

```text
Domain
  ↓
Application
  ↓
Ports / abstractions
  ↓
Infrastructure and interface adapters
```

Django models are persistence adapters; Django/HTTP views should orchestrate and translate I/O rather than own business rules.

## Main Domain Areas

### Identity and organizations

- Custom `User` with UUID PK.
- `Organization`, business units/branches/departments/teams.
- `Membership`, roles and permissions.
- Scope-aware authorization.

### Supply side

- Carriers.
- Drivers and driver profiles.
- Driver documents/compliance.
- Vehicles and refrigeration profiles.
- Driver-vehicle assignments.
- Driver geographic preferences and route intents.

### Freight commercial flow

- `FreightRequest`.
- `FreightRequestStop` (`PICKUP` / `DELIVERY`).
- `FreightRequestCargo` aggregate cargo profile.
- `FreightCargoLot` for fractional cargo mapped from pickup stop to delivery stop.
- Quotes and offers.

### Marketplace

- Matching candidate generation.
- Offer invitations.
- Driver interest.
- Offer selection.
- Concurrency/idempotency hardening.

### Operational execution

`FreightOperation` is the execution aggregate.

Current global status flow:

```text
ASSIGNED
  → DRIVER_EN_ROUTE_TO_PICKUP
  → ARRIVED_AT_PICKUP
  → LOADING
  → IN_TRANSIT
  → ARRIVED_AT_DELIVERY
  → UNLOADING
  → DELIVERED
```

Non-terminal states may transition to `CANCELLED` according to the domain state machine.

`INCIDENT` is **not** an operation status. Incidents are represented as operational events and do not replace the trip's main lifecycle state.

### Multi-stop operation

Commercial stops are snapshotted into `FreightOperationStop` when an operation is materialized. Cargo lots are snapshotted into `FreightOperationCargoLot`.

This isolates an active operation from later commercial edits to its originating request.

Operational stop states currently support ordered execution, including the `PENDING → ARRIVED → COMPLETED` lifecycle and terminal cancellation behavior implemented by application services.

A delivery lot cannot be completed before its corresponding pickup is complete.

### Proof of Delivery

`ProofOfDelivery.operation` is a foreign key because a multi-destination operation can have multiple PODs. A POD can also be linked one-to-one to a specific `FreightOperationStop`.

New code should use `operation.pods` for the real multi-POD relation. `operation.pod` exists only as a legacy compatibility property returning the first POD.

### Tracking

Tracking is associated with the entire `FreightOperation`, not with each stop.

- `TrackingSession`
- `LocationPoint`
- start/end lifecycle
- single active session protection per operation
- batch location ingestion
- retry/idempotency by `client_event_id` and/or sequence
- active sessions close when the operation reaches terminal delivery/cancellation flows

Do not deduplicate GPS solely by device timestamp; two legitimate samples may share the same timestamp resolution.

### Refrigerated cargo and thermal telemetry

Thermal telemetry is deliberately separate from GPS.

- `ThermalReading`
- `ThermalExcursion`
- sensor/device metadata
- device/server timestamps
- quality/validity
- operation association

This separation allows future refrigerated sensor integrations without coupling temperature to location ingestion.

## RBAC And Organizational Scopes

Authorization is organization-aware and should fail closed.

Representative roles include:

- `SYSTEM_ADMIN`
- `COMPANY_ADMIN`
- `COMMERCIAL_MANAGER`
- `SALESPERSON`
- `OPERATIONS_MANAGER`
- `DISPATCHER`
- `FINANCIAL_MANAGER`
- `FINANCIAL_ANALYST`
- `DRIVER`
- `CUSTOMER`
- `AUDITOR`
- `VIEWER`

The `DRIVER` role intentionally contains only the operational permissions required for the driver's own assigned work:

```text
FREIGHT_OPERATIONS_VIEW
FREIGHT_OPERATIONS_CHANGE_STATUS
FREIGHT_OPERATIONS_REPORT_INCIDENT
FREIGHT_OPERATIONS_RECORD_POD
TRACKING_VIEW
TRACKING_START
TRACKING_RECORD
TRACKING_END
```

Ownership checks remain mandatory: a driver permission does not grant access to another driver's operation.

## Audit And Traceability

The audit foundation is append-only and distinct from operational events.

- `AuditLog` answers who changed/performed what and under which organization/request context.
- `FreightOperationEvent` records the immutable operational timeline of a freight execution.

Do not conflate the two.

## API Strategy

Production-facing application APIs are versioned under:

```text
/api/v1/
```

Current v1 adapters include:

- login / refresh / revoke
- current driver profile/capabilities
- driver preferences
- route intents
- assigned operations and operation detail
- operation status advancement
- operational stop status advancement
- incident reporting
- POD recording
- thermal readings
- tracking start/location/batch/end
- customer freight-request list/detail/create flows

See:

- `docs/api/conventions.md`
- `docs/api/v1.md`

## Idempotency And Concurrency

Critical commands must tolerate mobile retries and concurrent requests.

Current strategies include:

- natural database uniqueness for `Selection → Operation`.
- `transaction.atomic()`.
- `select_for_update()` where serialization is required.
- unique constraints.
- `IntegrityError` recovery where appropriate.
- `client_event_id` / sequence for telemetry retry safety.
- idempotent POD handling with conflict detection for materially different payloads.

Do not implement idempotency with `if not exists: create()` alone.

## Roadmap From Current State

### Next architectural step

Generalize `FreightOperation` origin. Today its `selection` relation is mandatory, which makes marketplace selection the only valid origin. Before recurring routes are introduced, the model should allow other explicit operation origins without fabricating marketplace records.

### Recurring / contracted operations

Planned domain:

- `ContractedRoute` or equivalent.
- validity period.
- recurring calendar/windows.
- standard multi-stop route definition.
- SLA.
- preferred/fixed carrier, driver and vehicle.
- substitution rules.
- materialization into independent `FreightOperation` executions.

A recurring route is an operational agreement/template, not merely a cron job that clones freight requests.

### Matching evolution

Use the full route and driver intent rather than only origin/destination:

- area of action.
- route direction.
- additional distance/detour.
- return implications.
- journey duration.
- vehicle/cargo compatibility.
- historical affinity.

### Storage/warehousing

Model warehouse/storage workflows as a dedicated operational concern without turning every waypoint into a warehouse concept.

### Commercial/financial

- SaaS plans.
- marketplace commission.
- billing.
- settlements.
- payment workflows.

## Mobile Build

### Requisitos do ambiente mobile

- **Java**: 17
- **Flutter SDK**: versão limpa (sem modificações globais).
- **Gradle**: Wrapper 9.3.1 (usado pelo projeto).
- **Android Gradle Plugin (AGP)**: 9.1.0.
- **Kotlin**: 2.4.0.
- **compileSdkVersion**: 34.

### Fluxo de build

```bash
cd apps/rotta_driver
flutter pub get
flutter test
flutter build apk --debug
```

### Build reproduzível

- Não deve haver overrides locais de R8.
- Não edite o SDK Flutter para corrigir problemas específicos do projeto.
- Mudanças de Gradle/AGP/Kotlin devem ser realizadas nos arquivos versionados (`gradle-wrapper.properties`, `settings.gradle`, `app/build.gradle`).
- Consulte a auditoria detalhada em `docs/audits/android_build_reproducibility_review.md`.

## Development

### Setup

Typical local flow:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Use project-specific environment variables and never commit secrets.

### Quality checks

```bash
pytest
python manage.py check
python manage.py makemigrations --check
```

Run focused tests before the full suite when changing a critical bounded context.

### Migrations

Never edit historical migrations to implement new domain behavior. Add new migrations and verify existing data before introducing new uniqueness constraints or non-null relations.

The multi-stop/POD evolution is represented by the current freight migration series, including migration `0010` in the provided project snapshot.

## PostgreSQL

PostgreSQL is the intended persistence engine for production and is relied upon for transactional/concurrency behavior such as row locks and uniqueness enforcement.

Concurrency tests should run against a database configuration capable of exercising the intended semantics; SQLite-only success is not sufficient evidence for row-lock behavior.

## Documentation Map

- `docs/architecture/current-state.md` — current implemented architecture and gaps.
- `docs/api/conventions.md` — API-wide conventions.
- `docs/api/v1.md` — current v1 mobile/customer API.
- `docs/domain/identity-access.md` — identity/RBAC concepts.
- `docs/domain/supply-side.md` — carriers, drivers, vehicles and route preferences.
- `docs/domain/freight-operations.md` — freight, marketplace, operations, multi-stop, POD and tracking.
- `docs/domain/transport-glossary.md` — domain terminology.
- `docs/domain/operational-discovery.md` — discovery checklist for real transport operations.
- `docs/domain/public-site.md` — public-site editorial/route contract.
- `docs/audits/mvp_gap_analysis.md` — living technical gap summary.
- `docs/adr/` — historical architectural decisions.

## ADRs

ADRs under `docs/adr/` are historical decision records. They should not be rewritten as if they were created today. When an ADR's planned decision is now implemented, a short implementation-status note may be appended while preserving its original context and decision.
