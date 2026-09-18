# Supply Side Marketplace Domain

The Rotta 116 supply side represents the people, organizations and assets capable of executing transport: autonomous drivers, aggregated partners, carriers, owned fleets and third-party fleets.

## User Is Not Driver

`User` is an identity/authentication concept. `Driver` is a business entity representing a person capable of executing freight operations.

A driver may be linked to a user for web/mobile access, but operational driver state remains in the driver domain rather than the authentication model.

## Organization As Provider

`Organization` represents companies and institutional participants. Carrier behavior is modeled in the carrier/supply contexts without creating a duplicate top-level tenancy concept.

This enables one multi-organization authorization/audit foundation across customers, carriers, fleet owners and partners.

## Vehicle Ownership And Assignment

`Vehicle` belongs to an organization rather than directly to a driver.

`DriverVehicleAssignment` preserves the historical relationship between drivers and vehicles, including active/primary assignments and validity periods. The current domain prevents contradictory active-primary relationships while preserving history.

## Driver Approval And Availability

Approval and availability are independent:

- approval/document/compliance status answers whether the driver is eligible.
- availability answers whether the driver is operationally available.

Marketplace matching applies additional constraints; availability alone does not mean every offer is compatible.

## Driver Documents And Compliance

Private driver/vehicle/carrier documents use metadata plus private storage references. Private material must use the document storage port/adapter and must not be exposed through permanent public URLs.

Audit data must redact sensitive document/storage values.

## Driver Geographic Preferences

Drivers can persist geographic preferences and route intentions.

The current code includes driver preferences/route intents consumed by matching evolution. The long-term matching objective is geographic coherence rather than simple proximity:

- base/locality and radius.
- preferred/avoided regions.
- desired route direction.
- additional distance/detour.
- return implications.
- journey time.
- historical affinity.

The backend remains authoritative; Flutter only submits/reads these preferences through API contracts.

## Mobile Operations

The Flutter driver application and `/api/v1/` driver API are implemented.

Current mobile-operational capabilities include:

- authenticated driver identity/capabilities.
- assigned operation list/detail.
- operation state advancement.
- multi-stop execution.
- incident reporting.
- POD submission.
- GPS tracking start/points/batch/end.
- driver preferences and route intents.
- thermal-reading endpoint support in the operational API.

`DRIVER` RBAC permissions are intentionally narrow and must always be combined with operation ownership.

## Tracking Model

Tracking is not stored as latitude/longitude fields directly on `Driver`.

`TrackingSession` represents a tracking lifecycle for a `FreightOperation`; `LocationPoint` stores the emitted samples.

Retry safety relies on explicit identifiers such as `client_event_id`/sequence rather than timestamp-only deduplication.

## Next Supply-Side Evolutions

- deeper geographic matching/scoring.
- preferred/fixed driver and vehicle behavior for contracted recurring routes.
- substitution rules when preferred resources become unavailable.
- operational notifications/push delivery.
- richer fleet-health/maintenance capabilities where relevant.
