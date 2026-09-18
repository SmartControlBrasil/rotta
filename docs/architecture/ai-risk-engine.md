# Rotta AI Core — Risk Engine Specification (v1.0)

Este documento especifica o motor de risco baseado em regras (`RuleBasedRiskModel`) implementado na Phase AI-02.

---

## 1. Purpose
O objetivo do **Operational Risk Engine** é fornecer uma pontuação preditiva determinística, compreensível e auditável (explicável) do risco de atraso, sinistro ou quebra de qualidade em cada operação de frete em andamento. Este baseline atua como a primeira camada de inteligência do Rotta 116.

---

## 2. Architecture
O motor é modelado de acordo com a arquitetura de portas e adaptadores (Hexagonal). O domínio da aplicação interage apenas com a interface `RiskModelPort` (`predict(features) -> RiskAssessment`), permitindo que a implementação de heurísticas baseadas em regras seja intercambiável por modelos de Machine Learning (XGBoost/Scikit-Learn) no futuro, sem impacto em outras partes do sistema.

---

## 3. Risk Policy V1
A política de risco (`OperationalRiskPolicyV1`) centraliza todas as configurações de pesos de regras e limites (thresholds). As regras cobrem SLA, rastreamento GPS, telemetria térmica, incidentes e conformidade de alocação de motoristas/veículos.

---

## 4. Risk Rules (Catálogo de Regras)

A tabela abaixo detalha todas as regras ativas no motor de risco:

| Rule Code | Feature | Condition | Weight | Explanation | Version |
| --------- | ------- | --------- | -----: | ----------- | ------- |
| **SLA_OVERDUE** | `sla_overdue` | `True` | 0.40 | SLA da operação está atrasado. | 1.0 |
| **SLA_MARGIN_CRITICAL** | `sla_margin_min` | `< 30` | 0.30 | Margem de SLA crítica (menos de 30 minutos). | 1.0 |
| **SLA_MARGIN_LOW** | `sla_margin_min` | `30 <= margin < 120` | 0.15 | Margem de SLA baixa (menos de 2 horas). | 1.0 |
| **TRACKING_UNAVAILABLE** | `tracking_active` | `False` | 0.20 | Rastreamento inativo em operação com motorista e veículo associados. | 1.0 |
| **TRACKING_STALE** | `last_position_age_min` | `> 60` | 0.15 | Rastreamento estagnado (sem novas posições há mais de 1 hora). | 1.0 |
| **THERMAL_EXCURSION** | `thermal_excursion_count` | `> 0` | 0.25 | Ocorrência de variação térmica fora do limite permitido. | 1.0 |
| **THERMAL_BELOW_MIN** | `temperature_below_min` | `True` | 0.20 | Última temperatura registrada está abaixo do limite mínimo permitido. | 1.0 |
| **THERMAL_ABOVE_MAX** | `temperature_above_max` | `True` | 0.20 | Última temperatura registrada está acima do limite máximo permitido. | 1.0 |
| **CRITICAL_INCIDENT** | `critical_incident_count` | `> 0` | 0.35 | Incidente crítico registrado na timeline da operação. | 1.0 |
| **OPEN_INCIDENT** | `open_incident_count` | `> 0` e `critical == 0` | 0.15 | Incidentes ativos registrados na timeline da operação. | 1.0 |
| **MULTIPLE_OPEN_INCIDENTS**| `open_incident_count` | `> 1` | 0.20 | Múltiplos incidentes registrados na timeline da operação. | 1.0 |
| **MULTI_STOP_COMPLEXITY** | `multi_stop` | `True` | 0.05 | Complexidade moderada devido a múltiplas paradas. | 1.0 |
| **FRACTIONAL_CARGO_COMPLEXITY**| `fractional_cargo` | `True` | 0.05 | Complexidade moderada devido a múltiplos lotes de carga. | 1.0 |
| **NO_DRIVER_ASSIGNED** | `has_driver` | `False` | 0.15 | Nenhum motorista alocado para a operação. | 1.0 |
| **NO_VEHICLE_ASSIGNED** | `has_vehicle` | `False` | 0.10 | Nenhum veículo alocado para a operação. | 1.0 |

---

## 5. Score Aggregation
Utilizamos uma estratégia **capped additive** para agregar o score final de risco:
\[\text{risk\_score} = \min(1.00, \sum \text{triggered\_rules\_weights})\]

Esta abordagem é ideal por sua transparência, simplicidade e linearidade de cálculo.

---

## 6. Risk Levels
O mapeamento de gravidade do risco operacional (`RiskLevel`) baseia-se nos seguintes limites (thresholds):
- `0.00`–`0.24`: **LOW** (Operação saudável)
- `0.25`–`0.49`: **MEDIUM** (Exposição inicial ou problemas leves)
- `0.50`–`0.74`: **HIGH** (Problemas críticos, atraso iminente)
- `0.75`–`1.00`: **CRITICAL** (Atraso consumado, sinistro ou quebra grave)

---

## 7. Explainability
Cada `RiskAssessment` gerado lista explicitamente:
1. `reasons`: Lista de descrições humanas indicando quais regras foram violadas.
2. `contributing_features`: Lista com os nomes das features que influenciaram na decisão.

---

## 8. Missing Data
A ausência de dados de telemetria ou SLA não inflaciona falsamente o score. Regras de rastreamento ou temperatura só são aplicadas se a operação possuir tais requisitos ou dependências estruturais associados no vetor de features.

---

## 9. Versioning
Toda inferência carrega metadados do modelo:
- `model_name`: `"rule_based_operational_risk"`
- `model_version`: `"1.0"`
- `feature_schema_version`: `"1.0"`

Qualquer redefinição de pesos ou novas regras resultará no incremento da versão do modelo para `1.1` ou `2.0`.

---

## 10. Benchmark Scenarios
Para validação e comparação de performance com futuros modelos de Machine Learning, definimos o seguinte conjunto de scores esperados sob cenários sintéticos:

- **Healthy operation:** Sem anomalias térmicas, no horário, rastreamento ativo -> **0.00 LOW**
- **SLA at risk:** SLA com margem < 30 min -> **0.30 MEDIUM**
- **Critical thermal operation:** Excursão ativa de temperatura -> **0.25 MEDIUM**
- **Tracking lost:** Operação em trânsito com perda de GPS por mais de 1 hora -> **0.15 LOW** (se isolado) ou **0.35 MEDIUM** (acumulado com ausência de alocação)
- **Multiple incidents:** Timeline com 2 incidentes ativos -> **0.35 MEDIUM** (0.15 + 0.20)
- **Highly critical combined scenario:** SLA atrasado + incidente crítico + tracking inativo -> **0.95 CRITICAL** (0.40 + 0.35 + 0.20)

---

## 11. ML Evolution Path
O dataset de features gerado no banco servirá de treinamento supervisionado para modelos preditivos (XGBoost ou Random Forest) que aprenderão o risco real final (label: atraso ou sinistro no encerramento). O `RuleBasedRiskModel` será o baseline para comparar o ganho de acurácia e precisão do modelo de Machine Learning.
