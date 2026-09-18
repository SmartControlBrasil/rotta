# Rotta 116 — Current Architecture State

Snapshot alignment: **2026-08-22**.

This document describes the implemented architecture at the current development checkpoint and the next structural boundary. It complements the historical ADRs.

## Current System Shape

```text
                       Public Web (Cargon)
                              |
Customer Portal ───── Django / API v1 ───── Driver Flutter
                              |
                       Application Layer
                              |
        +---------------------+----------------------+
        |                     |                      |
 Identity/Org          Freight Marketplace     Operation/Telemetry
        |                     |                      |
        +---------------------+----------------------+
                              |
                         PostgreSQL
                              |
                    Backoffice (NexaDash)
```

Presentation clients do not own domain rules.

## Core Commercial/Marketplace Flow

```text
FreightRequest
→ FreightQuote
→ FreightOffer
→ Matching
→ FreightOfferInvitation
→ FreightOfferInterest
→ FreightOfferSelection
→ FreightOperation
```

Selection-to-operation materialization is atomic, idempotent and protected against concurrent duplication.

## Operational Aggregate

`FreightOperation` owns execution state and operational history.

Global state machine:

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

Permitted cancellation paths are controlled by the domain state machine.

Incidents are represented by `FreightOperationEvent(INCIDENT_REPORTED)` and do not replace the main state.

## Multi-Stop Snapshot Model

A running operation must not change if the originating commercial request is edited later.

Therefore:

```text
FreightRequestStop       → FreightOperationStop
FreightCargoLot          → FreightOperationCargoLot
```

The operational records are snapshots owned by a particular FreightOperation.

Cargo lots explicitly map:

```text
pickup operational stop → cargo lot → delivery operational stop
```

The application layer enforces ordered execution and pickup-before-delivery integrity.

## POD Model

A FreightOperation may now have multiple POD records:

```text
FreightOperation 1 ─── N ProofOfDelivery
                           |
                           └── optional 1:1 delivery FreightOperationStop
```

`operation.pods` is the canonical relation. `operation.pod` is legacy compatibility only.

## GPS Tracking

```text
FreightOperation
  └── TrackingSession
        └── LocationPoint*
```

Tracking spans the trip rather than individual stops. Active-session creation is concurrency protected. Mobile retry uses explicit event/sequence identifiers rather than timestamp-only deduplication.

## Thermal Telemetry

Temperature telemetry is a separate model family:

```text
FreightOperation
  ├── TrackingSession / LocationPoint   (GPS)
  └── ThermalReading / ThermalExcursion (temperature)
```

This prevents GPS ingestion from becoming coupled to refrigerated sensor protocols.

## Authorization

Organization membership/RBAC controls business access. Driver mobile adds strict driver ownership.

The `DRIVER` role contains only the operation/tracking capabilities required to execute assigned work.

## FreightOperation Origins

`FreightOperation.selection` is now optional, supporting multiple commercial origins classified by `source_type`:

* **MARKETPLACE**: Requires a valid `selection` (1:1 relationship).
* **CONTRACTED_ROUTE**: Created from a materialized `ContractedRouteOccurrence`. `selection` must be null.
* **MANUAL / API**: Created directly without marketplace selection or route occurrence. `selection` must be null.

These invariants are enforced by model validation and database `CheckConstraint` rules.

## Contracted Routes Domain

Acordos operacionais recorrentes são modelados via `ContractedRoute`, que definem o padrão/template operacional:

* **ContractedRoute**: Representa o contrato recorrente entre cliente e transportadora (com motorista/veículo preferenciais opcionais, datas de vigência e dias da semana permitidos).
* **ContractedRouteStop**: O template de paradas da viagem contratada.
* **ContractedRouteOccurrence**: Representa a ocorrência de execução planejada para um dia específico.
* **Materialização**: Ocorre via chamada explícita de serviço, que gera a `FreightOperation` correspondente e realiza os snapshots de paradas da rota no momento da execução. Modificações futuras na rota não impactam execuções passadas.
