# Driver Pilot Runbook — Rotta 116

Este documento orienta operadores e motoristas na preparação, execução e validação do primeiro piloto real em campo do Rotta 116.

---

## 1. Preparação do Ambiente de Piloto
Antes de iniciar a viagem física, o Operador de Transporte deve criar os seguintes registros no Nexa Backoffice:

1. **Organização (Tenant)**: Confirmar que a Transportadora está cadastrada e ativa.
2. **Motorista (Driver)**: Cadastrar o motorista e associá-lo ao seu respectivo usuário no sistema.
3. **Veículo (Vehicle)**: Cadastrar a placa do veículo a ser utilizado.
4. **Operação de Frete (FreightOperation)**: Criar a operação contendo a rota desejada (mínimo de stops sequenciais) e associar o motorista e o veículo correspondentes.
5. **Carga**: Registrar os requisitos térmicos (se houver).

---

## 2. Roteiro de Execução do Motorista

### Passo 1: Autenticação
1. Abrir o aplicativo **Rotta Driver**.
2. Digitar o usuário/email e senha cadastrados.
3. Confirmar que o login foi realizado e a lista de operações atribuídas é exibida.

### Passo 2: Início da Operação
1. Localizar e abrir a operação atribuída.
2. Na parte superior da tela, o card **PRÓXIMA ETAPA REQUERIDA** exibirá o botão **Iniciar Operação**.
3. Tocar no botão e confirmar. O status da operação mudará para `DRIVER_EN_ROUTE_TO_PICKUP`.
4. Ligar o rastreamento tocando em **Iniciar Rastreamento** (conceder permissões de GPS se solicitado).

### Passo 3: Paradas de Coleta (Pickups)
1. Ao chegar ao local de coleta, tocar em **Cheguei à Coleta** (ou **Cheguei à Parada**).
2. O status da operação avançará para `ARRIVED_AT_PICKUP`.
3. Tocar em **Iniciar Carregamento** (status avança para `LOADING`).
4. Ao concluir o carregamento, tocar em **Concluir Parada** e depois em **Iniciar Viagem** (status avança para `IN_TRANSIT`).
5. Repetir o procedimento de chegada e conclusão para coletas subsequentes.

### Passo 4: Paradas de Entrega (Deliveries) e Registro de POD
1. Ao chegar ao cliente de entrega, tocar em **Cheguei ao Destino** (ou **Cheguei à Parada**).
2. O status da parada passa para `ARRIVED`.
3. A ação de conclusão da parada estará bloqueada e o botão **Registrar Comprovante (POD)** será exibido.
4. Tocar em **Registrar Comprovante (POD)**, preencher o nome do recebedor, notas adicionais (GPS é capturado automaticamente) e confirmar.
5. O botão **Concluir Parada** ficará disponível. Tocar e confirmar.
6. Repetir o fluxo para entregas subsequentes.

### Passo 5: Conclusão
1. Após a conclusão da última entrega, o card exibirá o botão **Finalizar Operação**.
2. Tocar e confirmar. O status macro mudará para `DELIVERED`.
3. Tocar em **Parar Rastreamento** para encerrar a telemetria GPS.

---

## 3. Validação do Painel de Controle (Backoffice)
Durante e após a viagem do motorista, o operador de backoffice deve verificar:
- **Control Tower**: A listagem de operações reflete em tempo real o status, a parada atual, o risco e a telemetria do veículo.
- **Timeline e Incidentes**: Todas as ações de status e reportes de incidentes do motorista devem estar logadas cronologicamente.
- **PODs**: Os comprovantes de recebimento devem estar visíveis e vinculados especificamente a cada parada de entrega na tela de detalhes.
- **Inteligência Operacional**: Fatores de risco recalculados e snapshots históricos gerados sem erros transacionais.

---

## 4. Contingências e Falhas Comuns

### Queda de Sinal de Internet
- **Comportamento**: Ações de transição de status falharão temporariamente com erros de rede.
- **Contingência**: O rastreamento GPS continuará salvando os pontos em cache local. O motorista deve aguardar a estabilização do sinal e tentar refazer a ação.

### Transição Rejeitada (Conflict 409 / Stale State)
- **Comportamento**: A tela exibe um aviso de conflito ou transição inválida.
- **Contingência**: O aplicativo forçará um refetch automático para recarregar o estado mais recente do servidor. O motorista deve visualizar o card de ações atualizado e prosseguir.
