# Rotta 116 Transport Domain Glossary

Current terminology used by the codebase and product discussions.

- **Organization**: company or institutional participant in Rotta, such as customer, carrier, partner or fleet owner.
- **Customer / Shipper / Contratante**: organization or party requesting logistics service.
- **Carrier**: organization responsible for providing transport capacity/execution.
- **Driver**: person executing transport in the field; may be employee, autonomous, aggregated or third party.
- **Vehicle**: transport asset used to execute an operation.
- **FreightRequest**: commercial/operational demand created by a customer before execution exists.
- **FreightRequestStop**: ordered commercial pickup/delivery location belonging to a FreightRequest.
- **FreightRequestCargo**: aggregate cargo profile for the request, including dry/refrigerated characteristics and operational requirements.
- **FreightCargoLot**: fractional cargo lot explicitly linked to a pickup stop and a delivery stop.
- **FreightQuote**: commercial price/service proposal associated with the request workflow.
- **FreightOffer**: marketplace offer representing freight capacity/opportunity to be exposed/matched to supply.
- **Matching**: process that generates/ranks compatible supply candidates for a freight offer.
- **Invitation**: invitation to a candidate driver/carrier to consider an offer.
- **Interest**: driver's/supply-side expression of interest in an offer.
- **Selection**: confirmed marketplace selection that can materialize an operation.
- **FreightOperation**: actual execution aggregate of the transport. This is the canonical term for the real trip/service execution; avoid introducing a parallel `Shipment` aggregate unless a distinct domain need is proven.
- **FreightOperationStop**: immutable operational snapshot of an ordered pickup/delivery stop for a specific FreightOperation.
- **FreightOperationCargoLot**: operational snapshot of a cargo lot mapped to its pickup and delivery operational stops.
- **Stop**: an ordered pickup or delivery location in the current implemented model. Hub/warehouse/waypoint semantics should be added only through explicit domain decisions.
- **Operational Event**: immutable event in the execution timeline, such as operation created, status changed, incident reported, POD created or cancellation.
- **Incident**: operational occurrence attached to a FreightOperation; it does not replace the operation's main status.
- **Proof of Delivery (POD)**: evidence that a delivery happened. Multi-stop operations can have multiple PODs, normally associated with delivery stops.
- **TrackingSession**: lifecycle grouping GPS telemetry for a FreightOperation.
- **LocationPoint**: GPS sample belonging to a TrackingSession; may carry client event/sequence identifiers for retry safety.
- **ThermalReading**: temperature telemetry sample associated with an operation/cargo context, distinct from GPS.
- **ThermalExcursion**: detected interval/condition in which thermal telemetry violates configured bounds.
- **FTL**: full truck/load operation.
- **LTL**: less-than-truckload/fractional operation; Rotta supports multiple cargo lots/stops within one FreightOperation.
- **Driver Route Intent**: driver's declared desired route/direction/time preference used by matching logic.
- **Driver Geographic Preference**: preferred/avoided service regions and area-of-action settings.
- **ContractedRoute (planned)**: recurring operational agreement/template with standardized stops, recurrence windows, SLA and preferred/fixed resources. It is not implemented in the current snapshot.
- **Settlement (planned)**: calculation/record of amounts owed to carriers/drivers/partners.
- **Subscription/Plan (planned commercial domain)**: recurring SaaS access arrangement, distinct from recurring transport routes.
