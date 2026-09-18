# Rotta AI Core — Architectural Design (Phase AI-00)

Este documento define a visão arquitetural, princípios de design, contratos de domínio, feature engineering e estratégia de integração para o subsistema de inteligência do **Rotta 116**.

---

## 1. Vision
O **Rotta AI Core** é a camada nativa de tomada de decisão estatística e preditiva do sistema. Ele existe para analisar fatos da execução operacional (rotas, telemetria térmica, tracking, SLAs e incidentes) e transformá-los em scores de risco acionáveis, alertas preditivos, recomendações e interfaces de assistência virtual integradas ao produto. Ele é projetado como propriedade intelectual proprietária do Rotta 116, podendo operar com inferência e modelos locais, sem dependência mandatória de APIs externas de terceiros.

---

## 2. Principles
- **Isolamento de Persistência (Hexagonal):** A camada de IA nunca consome ou manipula modelos Django ORM de forma dispersa. Ela consome dados estruturados e normalizados mapeados através de **Ports** (Query Services).
- **Invariância de Regras de Domínio:** A IA recomenda, estima e pontua riscos, mas **nunca decide validade ou autorizações**. O Domínio Logístico original (`src/freights/`) continua sendo o único detentor das regras, limites e permissões corporativas.
- **Tenant Isolation Nativo:** O isolamento multi-tenant se estende a todas as camadas de inteligência. A construção de qualquer contexto de IA obriga a validação de acesso do ator (Membership ativo na Organização).
- **Independência de Provedor:** A arquitetura do AI Core prevê implementações intercambiáveis (adapters), permitindo chaveamento entre heurísticas determinísticas, modelos locais de Machine Learning (XGBoost, Scikit-Learn) ou APIs de nuvem.

---

## 3. AI Bounded Context
O subsistema de inteligência é modelado como um bounded context isolado localizado em `src/intelligence/`:

- **intelligence/domain:** Contratos puros, DTOs de dados normalizados (`models.py`), vetor de features operacionais (`features.py`) e enums (`enums.py`). Sem nenhuma dependência externa do Django, banco de dados ou bibliotecas de inferência.
- **intelligence/application:** Interfaces estruturais (Ports) para a carga de dados e chamada de modelos preditivos (`ports.py`).
- **intelligence/infrastructure:** Adapters concretos para a extração física de dados baseados no Django ORM (`infrastructure/django/query_services.py`) e implementações de inferência locais/remotas de modelos.

---

## 4. Relationship with Operational Core
```text
  Freight Operation (Core)
             │
             ▼ (Get Context Request)
    [Query Service Adapter] ◄── Enforces Tenant Isolation Check
             │
             ▼ (Maps into DTOs)
      OperationContext
             │
             ▼ (Extracts Features)
     OperationFeatures
             │
             ▼ (Feeds Model Port)
       [RiskModelPort]
             │
             ▼ (Predicts)
       RiskAssessment ──► Output Score (e.g. 0.85 HIGH RISK)
```

---

## 5. Data Sources
O AI Core consolida informações agregadas provenientes das seguintes tabelas e sub-contextos operacionais:
- `FreightOperation` (Status, metadados de carga/limites térmicos).
- `FreightOperationStop` (Janelas horárias, ordem de sequência e status).
- `FreightOperationCargoLot` (Pesos, volumes e vinculação de paradas pickup/delivery).
- `TrackingSession` & `LocationPoint` (Status de sessões GPS ativas, coordenadas e telemetria de trânsito).
- `ThermalReading` & `ThermalExcursion` (Temperaturas em tempo real e ocorrências de quebra de especificação térmica).
- `FreightOperationEvent` (Timeline e histórico de auditoria/incidências relatadas).

---

## 6. OperationContext Contract
Toda a análise do AI Core se inicia com o DTO `OperationContext` (declarado em `src/intelligence/domain/models.py`), contendo apenas dados puros e imutáveis da operação sem o peso do Django ORM:
- Mapeamento completo de motoristas, veículos e transportadoras.
- Coleção ordenada de paradas e lotes de carga fracionados.
- Resumo de telemetria GPS e leituras de sensores térmicos.
- Status atual da análise de SLA (ON_TIME, DELAYED, etc.).

---

## 7. Feature Architecture
Os extratores transformam o `OperationContext` em um vetor de features tipado (`OperationFeatures`), desacoplando o cálculo matemático da lógica preditiva do modelo:
- `remaining_distance_km` / `remaining_time_min` (Estimativas de tráfego espacial).
- `stop_delay_min` / `average_speed_kmh` (Desempenho atual do trânsito).
- `thermal_excursion_count` / `incident_count` (Exposições térmicas e ocorrências).

Todas as features seguem o versionamento de schema (`feature_schema_version`) para assegurar retrocompatibilidade com modelos de ML treinados sob conjuntos de features antigos.

---

## 8. Risk Intelligence
O primeiro serviço do Rotta AI Core é a **Inteligência de Risco Operacional (Operational Risk Intelligence)**:
- Consome o vetor de features versionado.
- Produz o DTO `RiskAssessment` contendo:
  - `risk_score`: float de `0.00` a `1.00`.
  - `risk_level`: enums de gravidade (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
  - `reasons`: explicações qualitativas (ex: `"Excursão térmica ativa há 45 min"`).
  - `recommended_actions`: ações de mitigação (ex: `"Contatar transportadora para verificar alimentação do baú frio"`).

---

## 9. Recommendation Engine
O contrato de recomendação estruturada (`Recommendation`) permite sugerir melhorias de alocação de frota, ações corretivas de rota e otimizações de despacho baseadas em confiança (`confidence`), tipo (`RecommendationType`) e prioridade (`HIGH`, `MEDIUM`, `LOW`).

---

## 10. Assistant Architecture
O Assistente Virtual do Rotta é projetado sob uma arquitetura estruturada de **Intent-Detection & Tools (Agente)** para prevenir injeção de prompt e vazamentos cross-tenant:
1. Pergunta do Usuário em Linguagem Natural.
2. Reconhecimento de Intenções (Ex: `"Quais operações estão atrasadas?"` -> `GET_OPERATIONS_AT_RISK`).
3. Execução de Ports e Query Services autorizados baseados no RBAC/Tenant do ator.
4. Resposta estruturada normalizada.
5. Tradução da resposta para Linguagem Natural.

---

## 11. Model Ports
O port `RiskModelPort` (`predict(features) -> RiskAssessment`) abstrai o mecanismo preditivo. A aplicação orquestra os dados sem conhecer se a inferência ocorre via código Python estático, Scikit-learn, XGBoost ou microsserviço de ML externo.

---

## 12. Local AI Strategy
- **Fase Inicial:** Motores de regras determinísticos baseados no conhecimento de especialistas.
- **Fase de Coleta:** Geração automática de labels de risco e armazenamento de features no banco para compor o dataset de treinamento.
- **Fase Estatística:** Modelos locais leves (como regressão logística ou árvores de decisão simples) executados na própria CPU do servidor.
- **Fase ML Avancado:** Modelos de gradiente boosting (XGBoost/LightGBM) carregados em memória para inferências instantâneas e rastreáveis na persistência.

---

## 13. Security / Multi-tenancy
- **Isolamento de Dados:** Validação de Membership ativo no query service impede vazamento de dados confidenciais cross-tenant.
- **Minimização de Dados de Geolocalização:** Armazenamento reduzido de coordenadas brutas em datasets de treinamento.
- **Explicabilidade:** Todos os scores preditivos expõem contribuição de features e reason codes para auditoria e transparência corporativa.

---

## 14. Observability
Logs padronizados monitoram a saúde preditiva do modelo:
```python
{
    "input_context_id": "op-1234",
    "feature_version": "v1.0",
    "model_name": "operational_risk_model",
    "model_version": "v1.2",
    "score": 0.87,
    "latency_ms": 14.5
}
```

---

## 15. Roadmap

### AI-01 — Operational Feature Engine (Cálculo de features a partir do contexto) [CONCLUÍDO]
### AI-02 — Rule-Based Operational Risk (Motor determinístico inicial de riscos) [CONCLUÍDO]
### AI-03 — Recommendation Engine (DTOs e heurísticas de sugestões logísticas) [CONCLUÍDO]
### AI-04 — Historical Dataset Collection (Coleta automatizada de dados reais para ML) [CONCLUÍDO]
### AI-05 — Outcome Labels & Dataset Collection (Resultados observados e conjunto de dados supervisionado) [CONCLUÍDO]
### AI-06A — Dataset Collection & Instrumentation (Estratégia de amostragem, isolamento e CLI de relatórios) [CONCLUÍDO]
### AI-06A.1 — Operational Intelligence Integration (Integração de eventos reais e interface backoffice com N+1 check) [CONCLUÍDO]
### AI-06B — Statistical / ML Risk Model (Integração de inferência Scikit-Learn/XGBoost local)
### AI-07 — Assistant Core (Motor de intenções e chamadas de ferramentas)
### AI-08 — Matching Intelligence (IA para pontuação e ranking de ofertas/candidatos)
### AI-09 — Pricing Intelligence (IA para sugestão e otimização dinâmica de frete)
### AI-10 — Forecasting (Previsão de ETA e demandas de frete por praça)
### AI-11 — Document Intelligence (OCR e validação automática de canhotos de POD)
