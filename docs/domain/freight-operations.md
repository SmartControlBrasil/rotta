# Freight Marketplace And Operational Execution

This document describes the current freight lifecycle, operational aggregate, multi-stop model, tracking and POD behavior.

## End-To-End Flow

```text
FreightRequest
→ FreightQuote
→ FreightOffer
→ Matching
→ Invitation
→ Interest
→ Selection
→ FreightOperation
→ Stops / Tracking / Events / Incidents
→ POD
→ DELIVERED
```

## FreightRequest

`FreightRequest` represents demand before execution exists.

A request can include ordered `FreightRequestStop` records using the implemented stop types:

- `PICKUP`
- `DELIVERY`

`FreightRequestCargo` describes the request-level cargo profile; `FreightCargoLot` enables fractional cargo by binding a specific lot to a pickup stop and delivery stop.

## Marketplace

Offers are matched to supply candidates. Invitations, interest and selection make the marketplace workflow explicit and auditable.

A confirmed valid `FreightOfferSelection` can materialize exactly one FreightOperation. Concurrency protection uses database uniqueness/locking rather than application-only existence checks.

## FreightOperation

`FreightOperation` is the canonical execution aggregate.

Current status lifecycle:

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

Cancellation is allowed only according to the domain state machine.

Incidents do not become an `INCIDENT` state. They are `FreightOperationEvent` records, leaving the trip status intact.

## Operational Stops

At operation materialization time, request stops are copied into `FreightOperationStop` snapshots.

Reasons:

- execution remains historically stable.
- later commercial edits do not rewrite an active/completed trip.
- stop status belongs to execution, not the commercial request.

Operational stop sequence is unique per operation and execution is ordered.

The current service enforces a lifecycle centered on:

```text
PENDING → ARRIVED → COMPLETED
```

with terminal cancellation behavior where allowed by the service.

## Fractional Cargo

`FreightOperationCargoLot` snapshots each `FreightCargoLot` and references its operational pickup/delivery stops.

The application prevents delivery execution of a lot whose pickup has not been completed.

This enables a single LTL operation such as:

```text
1 PICKUP A   ┐ Lot A
2 PICKUP B   ┐ Lot B
3 DELIVERY C ┘ Lot A
4 DELIVERY D ┘ Lot B
```

without creating separate FreightOperations solely because there are multiple delivery destinations.

## Proof Of Delivery

A multi-stop operation may have multiple PODs.

`ProofOfDelivery` references:

- its FreightOperation.
- optionally one delivery FreightOperationStop (one POD per stop through the current one-to-one stop relation).

A repeated identical POD request is idempotent; a materially conflicting repeat is rejected.

An operation cannot become `DELIVERED` while required delivery stops/PODs remain incomplete.

New code should use `operation.pods`; `operation.pod` is a compatibility property for legacy single-POD consumers.

## Tracking

Tracking belongs to the whole FreightOperation:

```text
FreightOperation → TrackingSession → LocationPoint
```

Key invariants:

- no arbitrary tracking for another driver's operation.
- no new points in ended/invalid sessions.
- terminal operation paths end active tracking.
- explicit client identifiers/sequence provide retry safety.
- timestamp alone is not treated as a uniqueness key.

## Thermal Telemetry

Temperature is not a LocationPoint property.

Thermal telemetry uses `ThermalReading`/`ThermalExcursion` and can be associated with refrigerated operation requirements and sensor/device metadata.

## Operation Origin Generalization

Operations can be instantiated from different sources, represented by `OperationSource`:

* **MARKETPLACE**: Born from `FreightOfferSelection` (1:1 constraint).
* **CONTRACTED_ROUTE**: Materialized from a `ContractedRouteOccurrence`.
* **MANUAL / API**: Created directly without marketplace selection or route occurrence.

Invariants ensure that MARKETPLACE operations must have a selection linked, while other types must not have a selection.

## Contracted Routes execution

Planned recurring operations are modeled as `ContractedRoute` templates. An occurrence `ContractedRouteOccurrence` is planned for a specific day, which is then materialized into a `FreightOperation` with `source_type = CONTRACTED_ROUTE`. Once materialized, the execution follows standard operational stages (tracking, incidents, stop status transitions, POD) identically to marketplace-originated operations.
