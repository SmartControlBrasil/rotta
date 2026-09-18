# Rotta AI Core — Feature Catalog (v1.0)

Este catálogo documenta todas as features operacionais extraídas e modeladas pelo `OperationalFeatureExtractor` (Phase AI-01) para consumo por motores de heurística, modelos estatísticos e modelos de machine learning.

---

## Tabela de Features

| Feature | Tipo | Fonte | Fórmula | Missing policy | Version |
| ------- | ---- | ----- | ------- | -------------- | ------- |
| **remaining_distance_km** | `float` | Tracking / Stop | Distância geodésica (Haversine) entre a última coordenada GPS e a parada final do tipo DELIVERY. | `None` se GPS ou destino final ausentes. | 1.0 |
| **remaining_time_min** | `float` | - | *Não implementado nesta fase (reservado para modelo/roteamento futuro)*. | `None` | 1.0 |
| **average_speed_kmh** | `float` | - | *Não implementado nesta fase (reservado para histórico futuro)*. | `None` | 1.0 |
| **stop_delay_min** | `int` | SLA | Atraso da parada atual ou previsto em minutos. | `0` (padrão) | 1.0 |
| **driver_on_time_ratio** | `float` | - | *Não implementado nesta fase (reservado para histórico do motorista)*. | `None` | 1.0 |
| **route_deviation_km** | `float` | - | *Não implementado nesta fase (reservado para limites geofence)*. | `None` | 1.0 |
| **thermal_excursion_count** | `int` | Thermal | Contagem total de excursões térmicas gravadas na operação. | `0` | 1.0 |
| **incident_count** | `int` | Incident | Número total de incidentes reportados na timeline. | `0` | 1.0 |
| **total_stops** | `int` | Stop | `len(context.stops)` | `0` | 1.0 |
| **completed_stops** | `int` | Stop | Quantidade de paradas com `status == "COMPLETED"`. | `0` | 1.0 |
| **pending_stops** | `int` | Stop | Quantidade de paradas com `status` em `("PENDING", "ARRIVED")`. | `0` | 1.0 |
| **completed_stop_ratio** | `float` | Stop | `completed_stops / total_stops` | `0.0` se total de paradas for `0`. | 1.0 |
| **pickup_count** | `int` | Stop | Quantidade de paradas com `stop_type == "PICKUP"`. | `0` | 1.0 |
| **delivery_count** | `int` | Stop | Quantidade de paradas com `stop_type == "DELIVERY"`. | `0` | 1.0 |
| **has_sla** | `bool` | SLA | `planned_deadline is not None` | `False` | 1.0 |
| **sla_margin_min** | `float` | SLA | `planned_deadline - reference_time` em minutos. | `None` se sem SLA ou planned_deadline ausente. | 1.0 |
| **sla_overdue** | `bool` | SLA | `True` se status de SLA indicar atraso ou se `reference_time > planned_deadline` e operação não concluída. | `False` | 1.0 |
| **tracking_active** | `bool` | Tracking | Indica se há uma sessão de rastreamento ativa na operação. | `False` | 1.0 |
| **tracking_point_count** | `int` | Tracking | Total de pontos de localização recebidos na sessão. | `0` | 1.0 |
| **last_speed_kmh** | `float` | Tracking | *Não implementado nesta fase (residual database gap)*. | `None` | 1.0 |
| **last_position_age_min** | `float` | Tracking | `reference_time - last_timestamp` em minutos. | `None` se sem pontos de localização. | 1.0 |
| **has_thermal_requirement** | `bool` | Thermal | `temperature_min_c is not None or temperature_max_c is not None` | `False` | 1.0 |
| **temperature_below_min** | `bool` | Thermal | `True` se `last_reading < temperature_min_c`. | `None` se sem temperatura min ou leitura ausente. | 1.0 |
| **temperature_above_max** | `bool` | Thermal | `True` se `last_reading > temperature_max_c`. | `None` se sem temperatura max ou leitura ausente. | 1.0 |
| **last_temperature_c** | `float` | Thermal | Temperatura da última leitura registrada na operação. | `None` se sem leituras térmicas. | 1.0 |
| **open_incident_count** | `int` | Incident | Quantidade de incidentes em aberto. | `0` | 1.0 |
| **critical_incident_count** | `int` | Incident | Quantidade de incidentes com `CRITICAL` no tipo de evento. | `0` | 1.0 |
| **cargo_lot_count** | `int` | Cargo | Quantidade total de lotes de carga (`len(context.cargo_lots)`). | `0` | 1.0 |
| **total_weight_kg** | `float` | Cargo | Soma do peso (`weight_kg`) de todos os lotes de carga. | `0.0` | 1.0 |
| **total_volume_m3** | `float` | Cargo | Soma do volume (`volume_m3`) de todos os lotes de carga. | `0.0` | 1.0 |
| **total_package_count** | `int` | Cargo | *Não implementado nesta fase (gap do DTO CargoLotContext)*. | `0` | 1.0 |
| **multi_stop** | `bool` | Complexity | `total_stops > 2` | `False` | 1.0 |
| **multi_pickup** | `bool` | Complexity | `pickup_count > 1` | `False` | 1.0 |
| **multi_delivery** | `bool` | Complexity | `delivery_count > 1` | `False` | 1.0 |
| **fractional_cargo** | `bool` | Complexity | `cargo_lot_count > 1` | `False` | 1.0 |
| **has_driver** | `bool` | Driver | `driver is not None` | `False` | 1.0 |
| **has_vehicle** | `bool` | Vehicle | `vehicle is not None` | `False` | 1.0 |

---

## Política Geral de Missing Values
Para evitar falsas inferências de algoritmos preditivos e árvores de decisão, a política de missing values é definida com rigor:
1. **Dados Opcionais/Ausentes por Natureza (ex: telemetria GPS, leituras térmicas):** Devem retornar `None` em vez de `0` ou `False`. Um valor de `0` para `remaining_distance_km` significa chegada física, enquanto `None` significa indisponibilidade temporária de GPS.
2. **Totalizadores/Listas Vazias (ex: paradas, lotes de carga):** Devem retornar `0` ou `0.0` (conforme o tipo numérico), pois a ausência de elementos na lista representa de fato um quantitativo nulo.
3. **Inexistência de Requisito (ex: carga sem limite térmico):** Devem retornar `False` para `has_thermal_requirement` e `None` para limites individuais, indicando que não há restrições aplicadas.
