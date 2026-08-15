# Supply Side Marketplace Domain

Rotta 116 is a transport marketplace. The supply side represents people and assets that can execute transport opportunities: autonomous drivers, aggregated partners, partner carriers, own fleet and third-party fleet.

## User Is Not Driver

`User` remains an identity and authentication concept. `Driver` is a business entity that represents a person who can execute freight operations in the field. A `Driver` may be linked to a `User` when that person needs to access web or future mobile interfaces, but the driver profile is not the authentication account.

## Organization As Provider

`Organization` is used to represent companies and institutional participants, including transport companies, fleet owners, partners and carriers. A separate `TransportCompany` entity was not created in this phase because it would duplicate the existing multi-organization foundation. Provider-specific behavior can evolve through organization type, memberships and future bounded contexts.

## Vehicle Ownership

`Vehicle` belongs to an `Organization`, not directly to a `Driver`. This supports owned fleet, aggregated fleet, autonomous providers, third parties and partner carriers. A vehicle may be operated by different drivers over time.

## DriverVehicleAssignment

`DriverVehicleAssignment` records the historical relationship between a driver and a vehicle. It supports active/inactive assignments, primary assignment, `valid_from` and `valid_until`. The current model enforces one active primary vehicle per driver and one active primary driver per vehicle, while preserving historical assignments.

## Approval Is Not Availability

Driver approval and operational availability are separate concepts.

- `approval_status` controls whether the driver has passed registration/document review.
- `availability_status` controls operational state such as offline, available, busy or paused.

An approved driver can be offline. An available driver still depends on future matching, shipment and tracking contexts before receiving freight opportunities.

## Driver Documents

`DriverDocument` stores metadata and a private `storage_key`. Private documents must use the document storage port/adapter and must not be exposed through permanent public URLs. Audit payloads redact personal documents and storage keys.

## Flutter And Tracking Readiness

The future Flutter app will allow drivers to go online, receive opportunities, accept services, update operational status, send photos/signatures/POD and send GPS. This phase does not create the app, mobile API or tracking domain.

Tracking will be a separate bounded context. Historical location must not be stored as latitude/longitude directly in `Driver`. Future tracking records should preserve `occurred_at` and `received_at`, and mobile commands should support an idempotency key such as `client_event_id`.

## Out Of Scope For D1

D1 does not implement loads, transport requests, quotes, pricing, matching, shipments, real tracking, payments, commission, settlement, billing or a Flutter app.
