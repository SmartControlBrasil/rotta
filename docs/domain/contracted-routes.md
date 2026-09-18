# Contracted Routes Context

This document explains the conceptual model, state machines, recurrence rules, and materialization process for recurrent logistics contracts.

## Core Concepts

In Rotta 116, recurring logistics operations are split into three layers to balance operational templates, planning, and real execution:

1. **ContractedRoute** (Operational Agreement/Template):
   - Represents the commercial agreement for recurring freight.
   - Holds static properties like cargo type, preferred carrier, preferred driver and vehicle, weekdays of operations, and the template list of stops.
2. **ContractedRouteOccurrence** (Planned Occurrence):
   - Represents a concrete planned occurrence on a calendar date.
   - Points to a specific date, overrides or defaults driver/vehicle assignments, and tracks materialization status.
3. **FreightOperation** (Real Execution):
   - Represents the execution of the trip itself.
   - Holds snapshots of stop templates and operational state machine status.

```text
ContractedRoute
      │
      └── (1:N) ──> ContractedRouteOccurrence (planned date)
                           │
                           └── (1:1) ──> FreightOperation (execution)
```

## Weekdays and Validity

A `ContractedRoute` has a validity period defined by `valid_from` and `valid_until` (where `valid_until >= valid_from`).

Weekly recurrence is represented using associated `ContractedRouteWeekday` records. An occurrence can only be planned if:
* The route status is `ACTIVE`.
* The target date is within the validity window.
* The target date's weekday matches one of the weekdays configured for the route.
* No occurrence already exists for the same route and date combination (database unique constraint).

## Materialization

To initiate execution, a planned `ContractedRouteOccurrence` is materialized into a `FreightOperation`.
* **Idempotency & Concurrency**: Handled via row-level locking (`select_for_update`) and database constraints, ensuring that concurrent materialization requests for the same occurrence result in exactly one materialized operation.
* **Stop Template Snapshots**: On materialization, stops are copied from `ContractedRouteStop` to `FreightOperationStop`. Any changes to the original template route after materialization do not modify previously materialized operations.

## Technical Decisions & Snapshots

* **Occurrence não é snapshot completo de rota**: A ocorrência (`ContractedRouteOccurrence`) representa um agendamento operacional concreto e planejamento de designação (contendo a data da ocorrência e os recursos efetivos `driver` e `vehicle`). Ela não armazena um snapshot próprio das paradas da rota. As paradas reais são lidas a partir dos templates de paradas da `ContractedRoute` no exato momento da materialização para a `FreightOperation`.
* **Prioridade de Planejamento**: Os recursos (`driver` e `vehicle`) de execução definidos na ocorrência no momento do planejamento prevalecem sobre quaisquer alterações subsequentes dos recursos preferenciais (`preferred_driver` / `preferred_vehicle`) do template da rota.
