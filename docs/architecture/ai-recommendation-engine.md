# Rotta AI Core — Recommendation Engine Specification (v1.0)

Este documento especifica o motor de recomendações operacionais (`OperationalRecommendationEngine`) implementado na Phase AI-03.

---

## 1. Purpose
O objetivo do **Recommendation Engine** é transformar os sinais quantitativos de risco calculados no `RiskAssessment` e no vetor de `OperationFeatures` em recomendações e sugestões de mitigação claras e acionáveis para os analistas operacionais da torre de controle do Rotta 116.

---

## 2. Architecture
A engine opera como um serviço em memória puramente funcional. Ela consome o vetor de features e o diagnóstico de risco, e produz DTOs de recomendação tipados, agindo de forma totalmente livre de efeitos colaterais (side effects). Ela não altera nenhum model do banco, não dispara chamadas de API, não contacta motoristas e não cria timelines; toda execução física permanece sob responsabilidade dos use cases de domínio apropriados.

---

## 3. Recommendation Policy V1
As regras de mapeamento de riscos para ações sugeridas são agrupadas na política padrão `OperationalRecommendationPolicyV1`. A engine é pure Python e a sua lógica avalia reason codes estruturados das features e do risco para gerar candidatos de recomendação.

---

## 4. Mapping Rules (Catálogo de Recomendações)

A tabela abaixo descreve o mapeamento de reason codes para tipos de recomendações gerados:

| Risk Reason | Recommendation | Priority | Explanation | Version |
| ----------- | -------------- | -------- | ----------- | ------- |
| **SLA_OVERDUE** | `REVIEW_DELIVERY_WINDOW` | HIGH | Janelas planejadas inviabilizadas por atraso consumado. | 1.0 |
| **SLA_OVERDUE** | `CONTACT_DRIVER` | HIGH | Entrar em contato para obter nova estimativa de trânsito. | 1.0 |
| **SLA_MARGIN_CRITICAL** | `PRIORITIZE_OPERATION` | HIGH | Priorizar descarregamento imediato no destino final. | 1.0 |
| **SLA_MARGIN_LOW** | `MONITOR_OPERATION` | MEDIUM | Monitorar velocidade média e tráfego da rota. | 1.0 |
| **TRACKING_UNAVAILABLE** | `CHECK_TRACKING` | HIGH | Rastreamento inativo em rota com motorista/veículo alocados. | 1.0 |
| **TRACKING_STALE** | `CHECK_TRACKING` | MEDIUM | Sem novas posições GPS recebidas por mais de 1 hora. | 1.0 |
| **THERMAL_ANOMALY** | `CHECK_THERMAL_INTEGRITY` | HIGH | Leituras térmicas ou excursões ativas fora do especificado. | 1.0 |
| **CRITICAL_INCIDENT** | `ESCALATE_INCIDENT` | CRITICAL | Escalar timeline operacional para a gerência de risco. | 1.0 |
| **OPEN_INCIDENT** | `MONITOR_OPERATION` | MEDIUM | Acompanhar evolução de incidentes não críticos na rota. | 1.0 |
| **NO_DRIVER_ASSIGNED** | `ASSIGN_DRIVER` | MEDIUM | Selecionar e vincular motorista qualificado à operação. | 1.0 |
| **NO_VEHICLE_ASSIGNED** | `ASSIGN_VEHICLE` | MEDIUM | Vincular placa/veículo compatível com peso e volume. | 1.0 |
| **COMPLEXITY_WARNING** | `MONITOR_OPERATION` | LOW | Rota complexa multi-stop ou fracionada. | 1.0 |

---

## 5. Priority
Toda recomendação possui uma prioridade de urgência (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`) herdada da gravidade da regra que a disparou.

---

## 6. Deduplication & Priority Merge
Como múltiplos riscos podem sugerir a mesma ação mitigadora, a engine realiza **Deduplicação de Recomendações e Fusão de Prioridades**:
1. Se múltiplas regras geram recomendações do mesmo tipo (ex: `CHECK_TRACKING`), a engine mescla-as em uma recomendação única.
2. A prioridade final da recomendação mesclada corresponde à maior prioridade entre as candidatas (`CRITICAL` > `HIGH` > `MEDIUM` > `LOW`).
3. O `suggested_action` e o `reason_code` são atualizados para corresponder à recomendação de maior gravidade.
4. O campo `reason` concatena as explicações individuais de todas as causas acumuladas.
5. A confiança (`confidence`) assume o valor máximo das contribuições.
6. A lista `source_risk_codes` acumula todos os códigos de riscos de origem causadores da recomendação (sem duplicatas).

---

## 7. Explainability
A inclusão de `reason_code` e `source_risk_codes` no DTO `Recommendation` permite que a torre de controle mostre visualmente (e explique) o porquê de o Rotta estar sugerindo uma ação corretiva.

---

## 8. Versioning
Toda recomendação é carimbada com as versões da política e do modelo:
- `policy_name`: `"operational_recommendation_policy"`
- `policy_version`: `"1.0"`

---

## 9. Assistant Readiness
As recomendações estruturadas formam o contrato perfeito para o assistente virtual do Rotta AI Core. Perguntas como `"O que devo fazer para a operação X?"` serão respondidas mapeando diretamente os DTOs `Recommendation` ativos para respostas em Linguagem Natural, eliminando riscos de alucinação ou injeções de prompt do motor estatístico.

---

## 10. Future Evolution
A engine baseada em regras determinísticas evoluirá para um classificador preditivo (e.g. aprendizado por reforço ou recomendação baseada em filtragem colaborativa do comportamento passado de despachantes) à medida que os dados históricos reais forem coletados pelo sistema na persistência.
