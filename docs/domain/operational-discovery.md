# Operational Discovery Guide

Use this guide to map real transport operations and validate Rotta 116 domain assumptions with carriers, shippers and drivers. Do not answer these questions in this document; record discoveries in a separate dated note/decision.

## Commercial And Demand

- How does a freight request arrive today?
- Who creates/approves quotes?
- How is price calculated and negotiated?
- Which requests are marketplace opportunities vs contracted recurring operations?
- Are there fixed routes/contracts/SLA arrangements?
- What data must remain immutable once an operation is assigned?

## Operation

- How are carrier, driver and vehicle selected?
- Which resources are fixed, preferred or substitutable?
- How is availability controlled?
- Who may reassign an operation after confirmation?
- Which statuses/events are actually used by operations teams?
- What incidents require escalation vs simple timeline recording?

## Multi-Stop And Fractional Cargo

- Are there multiple pickups, multiple deliveries, milk runs or transfer points?
- Must stops be executed strictly in sequence?
- Can a stop be skipped/cancelled and under which authority?
- How are individual lots/volumes tied to pickup and delivery stops?
- Is partial pickup/delivery allowed?
- Does each delivery require its own POD/canhoto?
- What happens when one lot fails while the rest of the route continues?

## Pickup And Delivery Evidence

- How is arrival proven?
- How is pickup completion proven?
- How is delivery proven?
- Are photos/signatures/canhoto required?
- Is receiver identity/document required?
- Are evidence requirements different by customer/cargo type?

## Tracking

- Which operations require GPS tracking?
- What sample interval is acceptable?
- How should offline points be buffered/synchronized?
- What level of accuracy is required?
- Who may see live/historical tracking?
- When must tracking automatically start/stop?

## Refrigerated Cargo

- Which cargo classes require temperature monitoring?
- Where is the acceptable range defined: request, contract, product or customer?
- Which sensors/devices are used?
- What happens during sensor failure/stale readings?
- What excursion thresholds require alerts/escalation?
- Is temperature evidence required as part of delivery/compliance?

## Recurring / Contracted Routes

- What defines a recurring route operationally?
- Validity dates?
- Days of week / calendar exceptions?
- Pickup/delivery windows?
- Standard stops/cargo profile?
- Preferred or fixed carrier/driver/vehicle?
- Substitution rules?
- SLA and penalties?
- Does each occurrence require commercial confirmation or materialize automatically?

## Drivers

- Employee, autonomous, aggregated or third party?
- Which compliance documents expire?
- How is driver area of action defined?
- Can drivers define preferred/avoided regions or desired route direction?
- How is driver payment/commission calculated?

## Fleet

- Owned vs third-party assets?
- Driver-vehicle assignment rules?
- Refrigeration capabilities?
- Maintenance/document controls?
- Existing GPS/temperature devices and APIs?

## Warehousing / Storage

- Is cargo temporarily stored between pickup and delivery?
- Is the warehouse a simple stop or a distinct custody workflow?
- Who owns inventory/custody records?
- Is cross-docking used?
- Does warehouse entry/exit need evidence and SLA timestamps?

## Financial

- How is the customer billed?
- Boleto, PIX, card, invoice/payment term?
- Marketplace commission rules?
- Carrier/driver settlement?
- Toll/fuel/advance reimbursement?
- Subscription/SaaS plan vs transaction fee separation?

## Integrations

- ERP/TMS/WMS?
- Customer APIs?
- WhatsApp/email operational dependencies?
- Existing trackers/sensor platforms?
- Accounting/payment systems?

## Problems And Metrics

- Where is there rework/data re-entry?
- Where is operational information lost?
- Which controls depend on specific people?
- Which delays are caused by waiting/empty travel?
- Which KPIs matter: acceptance, pickup SLA, delivery SLA, detour, empty km, temperature excursions, POD latency?
