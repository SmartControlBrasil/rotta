# Rotta AI Core — Dataset Collection & Instrumentation (v1.0)

Este documento especifica a estratégia de coleta contínua, política de amostragem (*sampling*) e observabilidade da inteligência do **Rotta AI Core**, implementada na Phase AI-06A.

---

## 1. Purpose
A infraestrutura de inteligência precisa registrar avaliações históricas e cruzar dados com outcomes sem inflacionar a persistência com redundâncias (como milhares de pontos GPS com a mesma informação útil) e sem impactar a transação principal de transporte em caso de falha da inteligência. Este módulo estabelece o controle de amostragem, isolamento de falhas e relatórios estatísticos.

---

## 2. Collection Strategy
A coleta baseia-se em um serviço de aplicação (`CollectOperationIntelligenceService`) que orquestra a recepção de sinais (eventos de trânsito ou telemetria) e decide se gera um novo snapshot imutável.

---

## 3. Sampling Policy
A classe `OperationalIntelligenceSamplingPolicyV1` define as condições de qualificação:
- **Debounce Time**: Mínimo de 15 minutos entre snapshots sucessivos de telemetria normal.
- **Significant Change**: Bypass imediato do debounce se houver alteração significativa nas features (ex: SLA overdue mudou, nova excursão térmica detectada, nova contagem de incidentes, parada logística concluída).

---

## 4. Trigger Matrix

| Evento Real | Deve gerar assessment? | Motivo | Frequência | Prioridade |
| ----------- | ---------------------- | ------ | ---------- | ---------- |
| **OPERATION_CREATED** | Sim | Estado inicial da viagem | Única | ALTA |
| **OPERATION_STARTED** | Sim | Início do trânsito físico | Única | ALTA |
| **STATUS_CHANGED** | Sim (Se terminal ou início) | Mudança importante de lifecycle | Baixa | ALTA |
| **LOCATION_POINT_RECORDED** | Sim (Condicional) | Telemetria GPS de trânsito | Alta | BAIXA (Debounced) |
| **THERMAL_READING_RECORDED**| Sim (Condicional) | Telemetria térmica de trânsito | Alta | BAIXA (Debounced) |
| **INCIDENT_REPORTED** | Sim | Risco de segurança/operacional | Baixa | CRÍTICA (Bypass) |
| **POD_CREATED** | Sim | Comprova entrega física de stop | Baixa | ALTA |
| **CANCELLED** | Sim | Fim da jornada por cancelamento | Única | CRÍTICA (Bypass) |

---

## 5. Idempotency vs Sampling

| Conceito | Finalidade | Escopo |
| -------- | ---------- | ------ |
| **Idempotency** | Evita duplicações por retries técnicos na mesma transação. | Hashing do payload exato de features. Se idêntico, retorna o snapshot gravado. |
| **Sampling** | Controla a densidade temporal do dataset de treino. | Avalia o tempo decorrido e a relevância de alterações de contexto. |

---

## 6. Collection Health
A saúde do pipeline é medida por:
- `snapshot_coverage_rate`: Razão de operações que possuem pelo menos 1 snapshot histórico gravado.
- `outcome_coverage_rate`: Razão de operações com outcome resolvido em relação às finalizadas.

---

## 7. Feature Quality
Métricas de completude de dados calculadas em nível de feature:
- `present_count` / `missing_count` / `missing_rate`
- Crucial para monitorar a qualidade de dados de telemetria opcionais (`last_temperature_c`, `remaining_distance_km`).

---

## 8. Label Distribution
BREAKDOWN estatístico dos rótulos observados:
- SLA breached rate: \% de viagens entregues em atraso.
- Thermal excursion rate: \% de viagens refrigeradas com violação térmica.
- Critical incident rate: \% de viagens com sinistro/incidentes críticos.

---

## 9. Dataset Diversity
Indicadores de diversidade do dataset coletado para evitar vieses:
- Contagem por motorista, veículo, cliente, transportadora e rota.
- Proporção entre origens `MARKETPLACE` e `CONTRACTED_ROUTE`.

---

## 10. Baseline Evaluation
Calcula a performance do motor de regras atual (`RuleBasedRiskModel`) contra os outcomes observados para servir de benchmark futuro:
- **Matriz de Confusão**: Verdadeiros Positivos (TP), Falsos Positivos (FP), Verdadeiros Negativos (TN), Falsos Negativos (FN).
- **Métricas**: Precision, Recall, Specificity.

---

## 11. Lead Time
Mede o intervalo de aviso prévio dos alertas de risco:
- Intervalo em minutos entre o primeiro snapshot que indicou `SLA_MARGIN_CRITICAL` e o estouro real do SLA (`sla_breached = True`).

---

## 12. Multi-tenancy
Toda a auditoria, geração de relatórios de dataset e benchmarks são calculados estritamente dentro do escopo do tenant do ator. Não há vazamento cross-tenant.

---

## 13. Privacy
Os relatórios agregados e benchmarks operam sobre dados anonimizados e estatísticas de contagem, eliminando nomes de motoristas, placas de veículos e detalhes de fretes corporativos.

---

## 14. ML Readiness Criteria
Checklist multidimensional obrigatório antes de avançar para treinamento:
- [ ] Mínimo de 100 exemplos positivos do label (ex: 100 atrasos reais).
- [ ] Mínimo de 100 exemplos negativos do label (ex: 100 entregas no prazo).
- [ ] Missing rate de features principais abaixo de 20%.
- [ ] Distribuição de origens logísticas balanceada.

---

## 15. Evolution
A coleta e a instrumentação nos darão a visibilidade necessária para justificar o início da modelagem preditiva estatística (`AI-06B`) ou Machine Learning local (`AI-06C`).
