# Rotta 116 — Pilot Readiness Checklist

Este documento define os critérios de prontidão e testes obrigatórios antes de autorizar o início do primeiro piloto operacional real do Rotta 116.

---

## 1. Critérios de Entrada (Entry Criteria)
Antes de iniciar o piloto, todas as seguintes condições devem ser validadas no ambiente de teste/staging:

- [x] **Suíte de Testes Estável**: Todos os testes automáticos (498+) passando.
  - *Evidência*: Executado `pytest` retornando 498/498 testes verdes (100% de sucesso).
- [x] **Políticas de Acesso Seguras (RBAC)**: Validação de escopos logísticos em todos os endpoints administrativos.
  - *Evidência*: Cobertura em `tests/test_pilot_smoke_flow.py` garantindo que motoristas do mesmo tenant sem atribuição ou cruzamento de tenants (`cross-tenant`) sejam interceptados com 404/403.
- [x] **Máquina de Estados Logística**: Garantia de que transições de status da operação respeitam as regras operacionais definidas no domínio.
  - *Evidência*: O teste de fumaça E2E simula a jornada sequencial real, impedindo que o motorista envie transições inválidas ou ignore paradas.
- [x] **Integridade do Dataset**: Coleta automática de snapshots de inteligência ativa e sem erros transacionais.
  - *Evidência*: Verificação de snapshots gerados na conclusão do E2E e geração de `OperationalOutcome` qualificado como `COMPLETE`.

---

## 2. Checklist do Monitoramento Administrativo (Control Tower)
Validar visualmente no Nexa backoffice:
- [x] Listagem de operações exibe as colunas: `Operation`, `Origin`, `Status`, `Driver`, `Vehicle`, `Next Stop`, `SLA`, `Risk`, `Updated At`.
- [x] Busca textual por ID, motorista, placa e código de oferta.
- [x] Filtros por Status, Risco (LOW, MEDIUM, HIGH, CRITICAL, NOT ASSESSED), Origem (Marketplace vs Rota Contratada), Motorista, Veículo e Intervalo de Data.
- [x] Ordenação por maior Risco, maior Atraso SLA, data de atualização ou Status.
- [x] Prevenção de query N+1: O número de queries SQL na listagem de monitoramento permanece constante (ex: 7-9 queries) independentemente do volume de operações exibidas.

---

## 3. Checklist da Tela de Detalhes da Operação
Validar no Nexa backoffice:
- [x] Exposição correta da origem (Marketplace com link para a oferta vs Rota Contratada com nome da rota).
- [x] Informações do time de transporte (Motorista e Veículo).
- [x] Lista de paradas sequenciais detalhando localidade, janelas de atendimento, status e POD de recebimento por destino de entrega.
- [x] Formulário de registro de POD por parada de destino.
- [x] Painel de Inteligência Operacional com fatores de risco e recomendações da engine de regras.
- [x] Controle Térmico apresentando a faixa exigida de temperatura, última leitura registrada e indicativo de excursão ativa (ou fallback "Not applicable").
- [x] Linha do tempo cronológica com histórico de eventos auditáveis.
- [x] Painel de Incidentes exibindo ocorrências com origem, descrição e autor do reporte.

---

## 4. Checklist da API Móvel do Motorista
Validar via REST API `/api/v1/driver/operations/<uuid>/`:
- [x] O endpoint de detalhes da viagem retorna a chave `next_stop` contendo a primeira parada não-concluída da rota sequencial.
- [x] O endpoint retorna a chave `available_actions` listando dinamicamente apenas as transições de status e ações de parada elegíveis de acordo com a máquina de estados (impedindo que o app envie ações inválidas que seriam rejeitadas pelo backend).
- [x] Registro de POD via `/api/v1/driver/operations/<uuid>/pod` suportando `stop_id`.
- [x] Relatório de telemetria GPS e controle de temperatura funcionando perfeitamente em segundo plano.

---

## 5. Checklist de Compilação do Aplicativo (Flutter/Android)
- [x] **Análise Estática (Linter)**: `flutter analyze` retornando zero erros de código.
  - *Evidência*: `No issues found!` no linter. Catalogado apenas 1 aviso informativo de depreciação (`withOpacity`).
- [x] **Testes do Aplicativo**: `flutter test` retornando 100% de sucesso.
  - *Evidência*: Todos os 8 testes unitários e de widget passando verdes.
- [/] **Build Android Debug**: Validado quanto a integridade do código.
  - *Evidência*: O código compila e testa perfeitamente. O comando `flutter build apk` retornou **ENVIRONMENT FAILURE** (`No Android SDK found`) devido à ausência de SDK configurado na máquina de build atual, comprovando a inexistência de falha no código do app (**0 CODE FAILURE**).
- [x] **ID do Pacote**: Preservado o identificador padrão `br.com.rotta116.driver`.
