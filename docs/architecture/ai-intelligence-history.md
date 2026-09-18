# Rotta AI Core — Intelligence History & Dataset Architecture (v1.0)

Este documento especifica a camada de persistência histórica e estratégia de dataset do **Rotta AI Core**, implementada na Phase AI-04.

---

## 1. Purpose
A camada histórica do Rotta AI Core existe para capturar, preservar e tornar auditável cada avaliação de inteligência produzida para uma operação de frete. Cada snapshot é um registro imutável que documenta o que o sistema sabia, quando sabia, qual modelo analisou, que risco calculou, por que calculou e o que recomendou — tudo em um instante específico no tempo.

---

## 2. Historical Assessment Model

O aggregate histórico é o `IntelligenceSnapshot`, persistido no banco como `IntelligenceAssessmentRecord`.

### Metadados Pesquisáveis (Colunas)
| Campo | Tipo | Descrição |
| ----- | ---- | --------- |
| `id` | UUID | Identificador único do snapshot |
| `organization_id` | UUID | Isolamento multi-tenant explícito |
| `operation_id` | UUID | Operação avaliada |
| `assessed_at` | DateTimeField | Momento da avaliação |
| `reference_time` | DateTimeField | Momento de referência para cálculo de features |
| `risk_score` | Float | Score de risco (0.00–1.00) |
| `risk_level` | CharField | LOW, MEDIUM, HIGH, CRITICAL |
| `model_name` | CharField | Nome do modelo de risco |
| `model_version` | CharField | Versão do modelo |
| `feature_schema_version` | CharField | Versão do schema de features |
| `recommendation_policy_version` | CharField | Versão da política de recomendações |
| `context_fingerprint` | CharField(64) | SHA-256 dos inputs para idempotência |

### Snapshots Versionados (JSONField)
| Campo | Tipo | Conteúdo |
| ----- | ---- | -------- |
| `feature_payload` | JSONField | Vetor completo de features serializado |
| `risk_payload` | JSONField | Score, reasons, contributing_features, recommended_actions |
| `recommendation_payload` | JSONField | Lista de recomendações com tipos, prioridades e reason codes |

---

## 3. Temporal Semantics

Cada feature histórica representa **informação conhecida até `reference_time`**. O `assessed_at` indica quando o sistema executou a avaliação. A separação é fundamental:
- `reference_time`: instante de referência para cálculo (ex: margem de SLA, idade do GPS)
- `assessed_at`: instante em que o snapshot foi criado e persistido

Isso garante que reconstruções futuras de datasets possam respeitar a semântica temporal original.

---

## 4. Feature Snapshot
Features são serializadas explicitamente pelo `IntelligencePayloadSerializer`:
- `datetime` → ISO 8601 UTC
- `Decimal` → string (preserva precisão)
- `Enum` → `.value` (string estável)
- `None` → preservado
- `float` → arredondado a 6 casas decimais

O payload é versionado pelo `feature_schema_version`. Mudanças no schema incrementam a versão.

---

## 5. Risk Snapshot
O `risk_payload` captura o estado completo da avaliação de risco:
- Score numérico, nível qualitativo
- Reasons (explicações humanas)
- Contributing features (features que influenciaram)
- Recommended actions (ações sugeridas pelo modelo)
- Metadados do modelo (nome, versão, timestamp)

---

## 6. Recommendation Snapshot
As recomendações são persistidas exatamente como produzidas naquele momento. Mudanças futuras na política de recomendações não afetam snapshots anteriores. Isso é fundamental para auditoria retrospectiva.

---

## 7. Versioning
Toda avaliação carrega:
- `model_name` + `model_version`: identifica o motor de risco
- `feature_schema_version`: identifica o schema do vetor de features
- `recommendation_policy_version`: identifica a política de recomendações

Sem isso, o histórico de inteligência perde valor para comparação e evolução de modelos.

---

## 8. Idempotency
Critério: mesmo `operation_id` + `context_fingerprint` = assessment duplicado (retry técnico).

O fingerprint é um SHA-256 do payload de features serializado + model_version + feature_schema_version. Se o contexto operacional não mudou desde a última avaliação, o serviço retorna o snapshot existente.

Assessments legítimos consecutivos (fingerprint diferente por mudança real nos dados) sempre criam novo registro.

---

## 9. Outcome Labels (Contrato Futuro)
O dataclass `OperationalOutcome` define o contrato de labels para datasets supervisionados:

| Label | Tipo | Fonte |
| ----- | ---- | ----- |
| `delivered_on_time` | bool | `status == DELIVERED` e `delay_minutes <= 0` |
| `delay_minutes` | int | `FreightOperation.delay_minutes` |
| `sla_breached` | bool | SLA status final |
| `thermal_excursion_occurred` | bool | `ThermalExcursion` count > 0 ao final |
| `critical_incident_occurred` | bool | Eventos CRITICAL na timeline |
| `operation_cancelled` | bool | `status == CANCELLED` |

> **IMPORTANTE**: Esses labels refletem **fatos observados após o encerramento**, não previsões do modelo. O Risk Engine é heurística/previsão; labels são ground truth.

---

## 10. Leakage Prevention
Features usadas para prever atraso em T1 **não podem incluir**:
- `actual_delivery_time`
- `final_delay_minutes`
- Incidentes futuros
- Excursões térmicas futuras

Esses elementos pertencem exclusivamente aos labels/outcomes. O `OperationalFeatureExtractor` calcula features com base apenas em dados disponíveis até `reference_time`.

---

## 11. Online vs Offline Features

| Tipo | Descrição |
| ---- | --------- |
| **Online** | Calculadas no momento operacional pelo `OperationalFeatureExtractor` |
| **Offline** | Reconstruídas historicamente a partir de snapshots persistidos |

O mesmo `OperationalFeatureExtractor` deve ser usado para ambos os cenários para evitar **training-serving skew** (divergência entre features de treinamento e features de produção).

---

## 12. Dataset Strategy
O dataset futuro será composto por:

```text
DatasetRecord
├── operation_id
├── assessed_at
├── features (from feature_payload)
├── labels (from OperationalOutcome)
├── feature_schema_version
└── metadata
```

**Armazenamento atual**: PostgreSQL (fonte de verdade).
**Exportação futura**: Parquet para datasets grandes de treinamento ML.
**Classificação atual**: **DATASET ESTRUTURAL** — a infraestrutura existe, mas não há dados históricos reais acumulados.

---

## 13. Multi-tenancy
Todo registro histórico possui `organization_id` explícito (UUIDField sem FK para manter bounded context isolado). Todas as queries do repository filtram por `organization_id`, impossibilitando consultas cross-tenant.

---

## 14. Privacy
O dataset prioriza identificadores técnicos (UUIDs) e variáveis operacionais. Não são armazenados:
- Nomes de motoristas/clientes como features
- PII sem necessidade
- Payload GPS bruto completo
- Imagens ou documentos binários

Exportações futuras de dataset poderão anonimizar IDs pessoais.

---

## 15. ML Evolution
A evolução do sistema segue a sequência:

```text
1. Rule-Based Intelligence (AI-02) ✅
2. Feature Collection via Snapshots (AI-04) ✅
3. Outcome Labels Collection (AI-05) — próxima fase
4. Statistical/ML Models (AI-06+) — futuro
```

O `RuleBasedRiskModel` será o baseline para comparar o ganho de acurácia de futuros modelos de Machine Learning treinados sobre o dataset histórico.
