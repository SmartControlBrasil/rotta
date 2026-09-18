# Rotta AI Core — Outcomes & Datasets Architecture (v1.0)

Este documento especifica a arquitetura de resultados observados (*outcomes*), geração de datasets e mitigação de *data leakage* do **Rotta AI Core**, implementada na Phase AI-05.

---

## 1. Purpose
Para evoluir de heurísticas estáticas baseadas em regras para modelos próprios de Machine Learning supervisionados (como classificação de risco ou previsão de atraso/sinistro), precisamos ser capazes de cruzar o que o Rotta sabia sobre uma operação em trânsito (Features) com o que de fato aconteceu no seu desfecho (Labels/Ground Truth). O módulo de Outcomes & Datasets unifica essa coleta de forma isolada por tenant e semanticamente segura contra vazamento de dados futuros.

---

## 2. Prediction vs Outcome

| Dimensão | Prediction Time (T1..Ti) | Outcome Time (Tn) |
| -------- | ------------------------- | ------------------ |
| **Escopo** | Features em tempo real / instantâneas | Resultados observados após encerramento |
| **Entidade** | `OperationFeatures` | `OperationalOutcome` |
| **Fonte** | Telemetria ativa, janelas parciais, status atual | Ground truth do banco logístico, PODs finalizados |
| **Relação** | Um ou mais snapshots históricos por operação | Um único desfecho final por operação |

---

## 3. Ground Truth
A verdade fundamental (*ground truth*) é sempre baseada em fatos observados gravados na base logística real (`FreightOperation`, `ThermalExcursion`, `FreightOperationEvent`).
> **PRINCÍPIO INEGOCIÁVEL**: Scores de risco (`risk_score`) ou níveis qualitativos (`risk_level`) calculados pelo Rule Engine **nunca** devem ser usados como labels de treinamento. Eles são estimativas qualitativas sujeitas a erros e vieses. Os labels devem representar fatos objetivos finais (se atrasou, se quebrou temperatura, se houve incidente).

---

## 4. Outcome Model
O resultado observado de uma operação é mapeado no domínio pelo DTO `OperationalOutcome`:
- `delivered_on_time`: `bool` | `None` se cancelada.
- `delay_minutes`: `int` | Diferença em minutos entre conclusão real e deadline planejado.
- `sla_breached`: `bool` | Indica estouro de prazo ou não-cumprimento de SLA por cancelamento.
- `thermal_excursion_occurred`: `bool` | Excursão térmica detectada em cargas refrigeradas.
- `critical_incident_occurred`: `bool` | Presença de incidente crítico registrado.
- `operation_cancelled`: `bool` | Indica se a operação foi cancelada.
- `resolved_at`: `datetime` | Data da resolução terminal (entrega ou cancelamento).

### Decisão de Persistência: Derivado sob Demanda
Optamos pelo cálculo sob demanda a partir do estado terminal imutável das tabelas da aplicação (`DELIVERED`, `CANCELLED`). Isso evita duplicar dados em tabelas adicionais e mantém os contextos logístico e de inteligência fracamente acoplados, sem dependências transacionais no fluxo crítico da rota.

---

## 5. Label Definitions

### SLA & Atraso
Calculado com base no deadline planejado da operação (definido pela última parada do tipo `DELIVERY` via `SLAService.compute`):
- Se `status == "DELIVERED"`, o atraso real é `completed_at - planned_deadline`.
- Se `status == "CANCELLED"`, `sla_breached` é marcado como `True`, pois a operação falhou em cumprir sua jornada planejada.

### Telemetria Térmica
- Se a operação possuir requisitos de temperatura (`temperature_min_c` ou `temperature_max_c` cadastrados):
  - `thermal_excursion_occurred = True` se `excursion_count > 0` na base histórica da operação.
  - `False` se 0.
- Se não houver requisitos térmicos cadastrados:
  - `thermal_excursion_occurred = None` (excluído de treinamento de risco térmico).

### Incidentes
- `critical_incident_occurred = True` se existir pelo menos um evento do tipo `INCIDENT_REPORTED` cuja descrição ou gravidade seja classificada como `CRITICAL`.

---

## 6. Temporal Semantics
Features extraídas em T1 representam **apenas** o que era conhecido em T1. O `assessed_at` do snapshot preditivo define a fronteira temporal absoluta. Qualquer evento ocorrido após `assessed_at` (como um incidente em T2 ou a entrega em T3) é resultado/desfecho de T1, logo pertence exclusivamente ao label e nunca deve alterar o vetor de features daquele snapshot histórico.

---

## 7. Leakage Prevention
Para mitigar vazamento de dados (*data leakage*), a suíte de testes do Rotta 116 contém testes explícitos que validam que:
- Timestamps de conclusão reais futuros, PODs futuros, incidentes ou excursões térmicas futuras **não contaminam** o snapshot histórico. As features do snapshot preditivo continuam estáticas e idênticas ao momento da avaliação, enquanto o `OperationalOutcome` reflete o estado final posterior.

---

## 8. Dataset Record
A representação de uma linha de treinamento supervisionada é o `DatasetRecord`:

```python
@dataclass
class DatasetRecord:
    snapshot_id: str
    operation_id: str
    organization_id: str
    assessed_at: datetime
    feature_schema_version: str
    model_name: str
    model_version: str
    features: dict  # X (Inputs)
    labels: dict    # y (Ground Truth)
    eligibility: str  # COMPLETE, PARTIAL, INELIGIBLE
    metadata: dict
```

- **COMPLETE**: Operação finalizada (`DELIVERED` ou `CANCELLED`), com outcomes consolidados.
- **PARTIAL**: Operação em andamento; features válidas, mas outcomes provisórios (não elegíveis para treinamento supervisionado final).
- **INELIGIBLE**: Falta de informações básicas na operação (ex: erro de carregamento).

---

## 9. Dataset Builder
O usecase `BuildOperationalRiskDatasetService` orquestra a geração determinística de datasets:
1. Filtra snapshots por `organization_id` e período.
2. Carrega o desfecho operacional via port `OperationResultContextPort`.
3. Calcula outcomes via `BuildOperationalOutcomeService`.
4. Monta `DatasetRecord`s cruzando as features salvas do snapshot histórico com os labels computados.
5. Aplica ordenação determinística por `(assessed_at, snapshot_id)`.

---

## 10. Dataset Quality
O serviço produz um relatório agregador de saúde do dataset (`DatasetQualityReport`):
- `total_records`: Contagem total.
- Breakdown de elegibilidade (`complete_records`, `partial_records`, `ineligible_records`).
- Proporção de registros utilizáveis por rótulo (`records_with_sla_label`, `records_with_thermal_label`, `records_with_incident_label`).
- `missing_tracking_rate`: Frequência de falha ou inatividade de sinal GPS de rastreamento nas features históricas.

---

## 11. Multi-tenancy
O `BuildOperationalRiskDatasetService` valida o acesso do ator (Membership ativo com status `ACTIVE` ou superuser) no port de busca. Tentativas de exportar datasets de organizações alheias resultam em `PermissionDenied`, mesmo que o UUID do tenant seja conhecido.

---

## 12. Reproducibility
Para garantir a reprodutibilidade dos experimentos de ML:
- O dataset gerado é ordenado deterministicamente por `(assessed_at, snapshot_id)`.
- Toda exportação carrega os metadados das versões dos modelos e schemas das features.

---

## 13. ML Readiness
- **Classificação**: **DATASET COLETANDO**
- **Próximos Passos**: O Rotta 116 agora tem capacidade de extração e cruzamento determinísticos. O treinamento de ML de classificação de risco poderá ser iniciado assim que acumularmos um volume aceitável de desfechos operacionais no banco histórico em produção.

---

## 14. Future Training Strategy
Modelos supervisionados de risco (como XGBoost local) usarão os payloads `features` como variáveis preditivas (X) e `sla_breached` / `thermal_excursion_occurred` / `critical_incident_occurred` como alvos binários (y). Split temporal rígido (ex: treino até 2026-09, teste em 2026-10) deve ser empregado para prevenir contaminação temporal de séries logísticas.
