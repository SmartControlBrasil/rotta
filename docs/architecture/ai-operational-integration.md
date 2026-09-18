# Rotta AI Core — Operational Intelligence Integration (v1.0)

Este documento especifica a arquitetura e os contratos de integração entre o Core Operacional de Logística e o **Rotta AI Core**, implementada na Phase AI-06A.1.

---

## 1. Purpose
A integração operacional visa conectar as avaliações de risco e as recomendações de mitigação aos fluxos físicos e telas de monitoramento do sistema em tempo real, sem violar os limites arquiteturais do DDD e garantindo isolamento total de falhas.

---

## 2. Event Integration
Os eventos operacionais do ciclo de vida logística disparam chamadas explícitas no Use Case/Application Layer, após a persistência bem-sucedida do evento na base operacional.

A chamada é executada através do mecanismo `transaction.on_commit(callback)` do Django para garantir que:
1. O assessment ocorra apenas após o evento operacional estar totalmente persistido no banco de dados.
2. A inteligência leia dados consistentes e já comitados.
3. Lock de banco de dados não sejam estendidos desnecessariamente.

---

## 3. Trigger Matrix

| Evento Real | Origem / Use Case | Event Type Disparado | Comportamento da Sampling Policy |
| ----------- | ----------------- | -------------------- | -------------------------------- |
| **Criar Operação** | `create_operation_from_selection` ou `materialize_contracted_route_occurrence` | `"OPERATION_CREATED"` | **Bypass** (Não há snapshot anterior, então avalia imediatamente) |
| **Mudar Status** | `change_operation_status` | `"STATUS_CHANGED"` | **Bypass** (Evento crítico: avalia imediatamente) |
| **Registrar POD** | `record_proof_of_delivery` | `"POD_CREATED"` | **Bypass** (Evento crítico: avalia imediatamente) |
| **Reportar Incidente**| `report_operation_incident` | `"INCIDENT_REPORTED"`| **Bypass** (Evento crítico: avalia imediatamente) |
| **Telemetria GPS** | `record_location_point` | `"LOCATION_POINT_RECORDED"` | **Debounce** (Limitado a no máximo 1 snapshot a cada 15 min, exceto se houver variação de risco) |
| **Telemetria Térmica**| `record_thermal_reading` | `"THERMAL_READING_RECORDED"`| **Debounce** (Limitado a no máximo 1 snapshot a cada 15 min, exceto se houver excursão térmica) |

---

## 4. Sampling
A política de amostragem (`OperationalIntelligenceSamplingPolicyV1`) evita avalanches de escrita causadas por telemetrias GPS e térmicas recorrentes.
- Um debounce temporal de **15 minutos** é enforcado por padrão.
- Bypass imediato ocorre caso:
  - O score de risco mude por mais de `0.10`.
  - O nível de risco transicione de patamar (ex: `LOW` para `MEDIUM`).
  - O número de incidentes ou variações térmicas mude.

---

## 5. Failure Isolation
A inteligência é tratada como um componente advisory (não-bloqueante). Toda a orquestração de coleta e processamento é encapsulada em blocos `try-except` robustos. Falhas no pipeline de IA (ex: estouro de timeout, erro do motor de regras) são logadas com traceback completo, mas **nunca propagadas** de forma a interromper a execução do fluxo principal da logística real.

---

## 6. Outcome Integration
Quando uma operação atinge um estado terminal (`DELIVERED` ou `CANCELLED`):
1. A transição de status dispara o assessment final da operação.
2. A partir deste estado, o `BuildOperationalRiskDatasetService` consegue computar os desfechos reais (SLA breched, thermal excursions, incidentes) e classificar os registros históricos associados àquela operação como elegíveis (`COMPLETE` / `PARTIAL`).

---

## 7. Backoffice Read Model
Para evitar a exposição de models internos do ORM e a ocorrência de N+1 queries na listagem de operações do Nexa, foi introduzido o DTO `OperationIntelligenceDTO`:

```python
@dataclass
class OperationIntelligenceDTO:
    operation_id: str
    risk_score: Optional[float]
    risk_level: str  # LOW, MEDIUM, HIGH, CRITICAL, or NOT_ASSESSED
    assessed_at: Optional[datetime]
    reasons: List[str]
    recommendations: List[dict]
    model_version: Optional[str]
    feature_schema_version: Optional[str]
```

- **Estado Neutro**: Se a operação não foi avaliada, o read model retorna `risk_level = "NOT_ASSESSED"` e `risk_score = None`. Isso garante que o dashboard não pinte uma operação não avaliada como de risco `LOW` por padrão.

---

## 8. RBAC
A exibição e consulta das informações de risco e inteligência operativa no backoffice estão vinculadas à verificação das permissões logísticas adequadas (`PermissionCode.FREIGHT_OPERATIONS_VIEW`).

---

## 9. Multi-tenancy
O `OperationIntelligenceQueryService` enforça regras rígidas de isolamento de tenant. Usuários sem perfil de superuser (`is_superuser = True`) têm o acesso restrito a dados pertencentes às organizações nas quais possuem filiação ativa (`Membership` ativa).

---

## 10. Performance & N+1 Prevention
O carregamento em lote dos assessments na tela de listagem de operações ocorre em **exatamente 1 query adicional** usando subconsultas no Django ORM:

```python
latest_ids_subquery = IntelligenceAssessmentRecord.objects.filter(
    operation_id=OuterRef("operation_id")
).order_by("-assessed_at").values("id")[:1]

records = records_query.filter(id__in=Subquery(latest_ids_subquery))
```
Isso previne a degradação de performance no banco de dados quando centenas de operações são listadas simultaneamente na tela do painel administrativo.

---

## 11. Observability
Logs técnicos registram qualquer anomalia no pipeline com as chaves contextuais:
- `operation_id`
- `organization_id`
- `event_type`
- `error`

---

## 12. Dataset Collection
A maturidade do dataset permanece classificada como `DATASET COLETANDO`. O pipeline de instrumentação está integrado, mas depende do span temporal do tráfego real de produção para acumular dados de Machine Learning.

---

## 13. Future Feedback Loop
Futuramente, a interface do operador no Nexa poderá disponibilizar ações rápidas para aceitar ou rejeitar recomendações geradas (ações como `CONTACT_CARRIER` ou `CALL_DRIVER`). A captura desse feedback retroalimentará a engine para otimizar os limiares de acionamento das regras.
