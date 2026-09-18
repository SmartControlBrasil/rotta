import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:intl/intl.dart';
import 'package:rotta_driver/design_system/rotta_spacing.dart';
import 'package:rotta_driver/design_system/rotta_typography.dart';
import 'package:rotta_driver/design_system/rotta_colors.dart';
import 'package:rotta_driver/design_system/widgets/rotta_info_row.dart';
import 'package:rotta_driver/design_system/widgets/rotta_status_badge.dart';
import 'package:rotta_driver/design_system/widgets/rotta_loading.dart';
import 'package:rotta_driver/design_system/widgets/rotta_error_state.dart';
import 'package:rotta_driver/features/operations/presentation/providers/operation_detail_provider.dart';
import 'package:rotta_driver/features/operations/presentation/providers/tracking_provider.dart';
import 'package:rotta_driver/features/operations/presentation/widgets/incident_dialog.dart';
import 'package:rotta_driver/features/operations/presentation/widgets/pod_dialog.dart';
import 'package:rotta_driver/features/operations/presentation/services/driver_operation_action_service.dart';

class OperationDetailScreen extends StatefulWidget {
  final String id;
  const OperationDetailScreen({Key? key, required this.id}) : super(key: key);

  @override
  State<OperationDetailScreen> createState() => _OperationDetailScreenState();
}

class _OperationDetailScreenState extends State<OperationDetailScreen> {
  late final OperationDetailProvider _detailProvider;

  @override
  void initState() {
    super.initState();
    _detailProvider = OperationDetailProvider();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _detailProvider.loadDetail(widget.id);
    });
  }

  Future<void> _confirmAndExecute(String action, String? stopId) async {
    final label = DriverOperationActionService.getActionLabel(action);
    if (label.isEmpty) return;

    final confirm = await showModalBottomSheet<bool>(
      context: context,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (context) {
        return Padding(
          padding: const EdgeInsets.all(RottaSpacing.lg),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                'Confirmar Ação',
                style: RottaTypography.subtitleBold.copyWith(fontSize: 18),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: RottaSpacing.md),
              Text(
                'Deseja realmente prosseguir com a ação "$label"?',
                textAlign: TextAlign.center,
                style: RottaTypography.body,
              ),
              const SizedBox(height: RottaSpacing.lg),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: () => Navigator.of(context).pop(false),
                      child: const Text('Cancelar'),
                    ),
                  ),
                  const SizedBox(width: RottaSpacing.md),
                  Expanded(
                    child: ElevatedButton(
                      style: ElevatedButton.styleFrom(
                        backgroundColor: RottaColors.primary,
                        foregroundColor: Colors.white,
                      ),
                      onPressed: () => Navigator.of(context).pop(true),
                      child: const Text('Confirmar'),
                    ),
                  ),
                ],
              ),
            ],
          ),
        );
      },
    );

    if (confirm == true) {
      try {
        final trackingProvider = Provider.of<TrackingProvider>(context, listen: false);
        final op = _detailProvider.operation!;
        await DriverOperationActionService.executeAction(
          context: context,
          provider: _detailProvider,
          action: action,
          operationId: op.id,
          stopId: stopId,
          onShowIncidentDialog: () => _showIncidentDialog(),
          onShowPodDialog: () => _showPodDialog(stopId),
          onToggleTracking: () async {
            if (trackingProvider.isTracking) {
              await trackingProvider.stopTracking();
            } else {
              await trackingProvider.startTracking(op.id);
            }
          },
        );
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Ação "$label" executada com sucesso!')),
          );
        }
      } catch (e) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('Erro ao executar ação: ${e.toString()}')),
          );
        }
        // Force refetch on error to handle stale states immediately
        _detailProvider.loadDetail(widget.id);
      }
    }
  }

  void _showIncidentDialog() {
    showDialog(
      context: context,
      builder: (context) => IncidentDialog(
        onSubmit: (desc) => _detailProvider.reportIncident(widget.id, desc),
      ),
    ).then((success) {
      if (success == true && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Incidente registrado com sucesso!')),
        );
      }
    });
  }

  void _showPodDialog(String? stopId) {
    showDialog(
      context: context,
      builder: (context) => PodDialog(
        stopId: stopId,
        onSubmit: (name, date, {latitude, longitude, notes, stopId}) =>
            _detailProvider.recordPOD(widget.id, name, date,
                latitude: latitude, longitude: longitude, notes: notes, stopId: stopId),
      ),
    ).then((success) {
      if (success == true && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('POD registrado com sucesso!')),
        );
      }
    });
  }

  Widget _section(String title, List<Widget> children) {
    if (children.isEmpty) return const SizedBox.shrink();
    return Card(
      margin: const EdgeInsets.only(bottom: RottaSpacing.md),
      elevation: 2,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      child: Padding(
        padding: const EdgeInsets.all(RottaSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: RottaTypography.subtitleBold.copyWith(color: RottaColors.primary)),
            const Divider(),
            const SizedBox(height: RottaSpacing.xs),
            ...children,
          ],
        ),
      ),
    );
  }

  String _formatDateTime(String? isoStr) {
    if (isoStr == null) return '-';
    try {
      final dt = DateTime.parse(isoStr).toLocal();
      return DateFormat('dd/MM/yyyy HH:mm').format(dt);
    } catch (_) {
      return isoStr;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Detalhe da Operação'),
        actions: [
          IconButton(
            icon: const Icon(Icons.warning_amber_rounded, color: Colors.orange),
            tooltip: 'Registrar Incidente',
            onPressed: () => _showIncidentDialog(),
          ),
        ],
      ),
      body: AnimatedBuilder(
        animation: _detailProvider,
        builder: (context, _) {
          if (_detailProvider.isLoading) {
            return const Center(child: RottaLoading());
          }
          if (_detailProvider.error != null) {
            return RottaErrorState(
              message: 'Erro ao carregar detalhe da operação',
              onRetry: () => _detailProvider.loadDetail(widget.id),
            );
          }
          final op = _detailProvider.operation;
          if (op == null) {
            return const Center(child: Text('Operação não encontrada.'));
          }
          final trackingProvider = Provider.of<TrackingProvider>(context);

          return SingleChildScrollView(
            padding: const EdgeInsets.all(RottaSpacing.md),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // 0. Next Action / Next Stop Highlight Card
                if (op.nextStop != null || op.availableActions.where((a) => DriverOperationActionService.isMainAction(a.action)).isNotEmpty)
                  Card(
                    color: RottaColors.primary.withValues(alpha: 0.05),
                    margin: const EdgeInsets.only(bottom: RottaSpacing.md),
                    shape: RoundedRectangleBorder(
                      side: const BorderSide(color: RottaColors.primary, width: 1.5),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Padding(
                      padding: const EdgeInsets.all(RottaSpacing.md),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Text(
                            'PRÓXIMA ETAPA REQUERIDA',
                            style: RottaTypography.subtitleBold.copyWith(color: RottaColors.primary, fontSize: 12, letterSpacing: 1.2),
                          ),
                          const SizedBox(height: RottaSpacing.sm),
                          if (op.nextStop != null) ...[
                            Text(
                              '${op.nextStop!.stopType == 'PICKUP' ? 'Coleta' : 'Entrega'} #${op.nextStop!.sequence} - ${op.nextStop!.city}/${op.nextStop!.state}',
                              style: RottaTypography.headline3.copyWith(fontSize: 18),
                            ),
                            const SizedBox(height: RottaSpacing.xs),
                            Text('${op.nextStop!.street ?? ''}, ${op.nextStop!.number ?? ''}'),
                            const SizedBox(height: RottaSpacing.md),
                          ],
                          // Render main action buttons
                          ...op.availableActions.where((a) => DriverOperationActionService.isMainAction(a.action)).map((availableAction) {
                            final label = DriverOperationActionService.getActionLabel(availableAction.action);
                            return Padding(
                              padding: const EdgeInsets.only(bottom: RottaSpacing.xs),
                              child: ElevatedButton(
                                style: ElevatedButton.styleFrom(
                                  backgroundColor: RottaColors.primary,
                                  foregroundColor: Colors.white,
                                  padding: const EdgeInsets.symmetric(vertical: 12),
                                ),
                                onPressed: _detailProvider.isSubmitting || !availableAction.enabled
                                    ? null
                                    : () => _confirmAndExecute(availableAction.action, op.nextStop?.id),
                                child: _detailProvider.isSubmitting
                                    ? const CircularProgressIndicator(color: Colors.white)
                                    : Text(
                                        label,
                                        style: const TextStyle(fontWeight: FontWeight.bold),
                                      ),
                              ),
                            );
                          }).toList(),
                          if (op.nextStop == null && op.availableActions.where((a) => DriverOperationActionService.isMainAction(a.action)).isEmpty)
                            const Text('Operação sem ações principais no momento.', style: TextStyle(fontStyle: FontStyle.italic)),
                        ],
                      ),
                    ),
                  ),

                // 1. Operação Section
                _section('Operação', [
                  RottaInfoRow(label: 'Referência', value: op.referenceCode ?? '-'),
                  const SizedBox(height: RottaSpacing.sm),
                  Row(
                    children: [
                      const Text('Status: ', style: TextStyle(fontWeight: FontWeight.bold)),
                      RottaStatusBadge(status: op.status),
                    ],
                  ),
                ]),

                // 2. Rota Section
                _section('Rota', [
                  RottaInfoRow(label: 'Origem', value: op.origin?['address'] ?? '-'),
                  const SizedBox(height: RottaSpacing.sm),
                  RottaInfoRow(label: 'Destino', value: op.destination?['address'] ?? '-'),
                ]),

                // 3. Carga Section
                _section('Carga', [
                  RottaInfoRow(label: 'Descrição', value: op.cargo?.description ?? '-'),
                  RottaInfoRow(label: 'Tipo', value: op.cargo?.cargoType ?? '-'),
                  RottaInfoRow(label: 'Perfil', value: op.cargo?.cargoProfile ?? '-'),
                  RottaInfoRow(label: 'Peso', value: op.cargo?.weightKg != null ? '${op.cargo!.weightKg} kg' : '-'),
                  RottaInfoRow(label: 'Volume', value: op.cargo?.volumeM3 != null ? '${op.cargo!.volumeM3} m³' : '-'),
                  RottaInfoRow(label: 'Tipo de Carga (Load Type)', value: op.loadType ?? '-'),
                ]),

                // 4. Paradas Section
                if (op.stops.isNotEmpty)
                  _section('Paradas', op.stops.map((s) {
                    final dateStr = s.scheduledDate ?? '-';
                    final windowStr = (s.windowStart != null && s.windowEnd != null)
                        ? ' (${s.windowStart} - ${s.windowEnd})'
                        : '';
                    return Padding(
                      padding: const EdgeInsets.only(bottom: RottaSpacing.sm),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Text('Parada ${s.sequence} - ${s.stopType ?? ''}', style: const TextStyle(fontWeight: FontWeight.bold)),
                              const Spacer(),
                              if (s.status != null) RottaStatusBadge(status: s.status!),
                            ],
                          ),
                          Text('${s.street ?? ''}, ${s.number ?? ''} - ${s.city ?? ''}/${s.state ?? ''}'),
                          Text('Agendado: $dateStr$windowStr', style: const TextStyle(fontSize: 12, color: Colors.grey)),
                          if (s.stopType == 'DELIVERY') ...[
                            const SizedBox(height: 2),
                            Text('Comprovante: ${s.hasPod == true ? 'Registrado' : 'Pendente'}',
                                style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: s.hasPod == true ? Colors.green : Colors.orange)),
                          ],
                          const Divider(),
                        ],
                      ),
                    );
                  }).toList()),

                // 5. Veículo Section
                if (op.vehicle != null)
                  _section('Veículo', [
                    RottaInfoRow(label: 'Placa', value: op.vehicle!.plate ?? '-'),
                    RottaInfoRow(label: 'ID', value: op.vehicle!.id ?? '-'),
                  ]),

                // 6. Transportadora / Motorista Section
                _section('Transportadora / Motorista', [
                  RottaInfoRow(label: 'Transportadora', value: op.carrier?.tradeName ?? '-'),
                  RottaInfoRow(label: 'Motorista', value: op.driver?.fullName ?? '-'),
                ]),

                // 7. Condição da carga (Refrigerada) Section
                if (op.cargo?.temperatureControl != null)
                  _section('Condição da Carga (Refrigerada)', [
                    RottaInfoRow(label: 'Temp. Mínima', value: op.cargo!.temperatureControl!.minC != null ? '${op.cargo!.temperatureControl!.minC} °C' : '-'),
                    RottaInfoRow(label: 'Temp. Máxima', value: op.cargo!.temperatureControl!.maxC != null ? '${op.cargo!.temperatureControl!.maxC} °C' : '-'),
                    RottaInfoRow(label: 'Temp. Alvo', value: op.cargo!.temperatureControl!.targetC != null ? '${op.cargo!.temperatureControl!.targetC} °C' : '-'),
                    if (op.thermalSummary != null) ...[
                      const Divider(),
                      Text('Telemetria em Tempo Real:', style: RottaTypography.subtitleBold.copyWith(fontSize: 14)),
                      RottaInfoRow(label: 'Última Leitura', value: '${op.thermalSummary!.latestTemperatureC} °C'),
                      RottaInfoRow(label: 'Horário do Sensor', value: _formatDateTime(op.thermalSummary!.latestSensorTimestamp)),
                      RottaInfoRow(label: 'Qualidade do Sinal', value: op.thermalSummary!.quality ?? 'Normal'),
                      RottaInfoRow(label: 'Leitura Válida', value: op.thermalSummary!.validity ? 'Sim' : 'Não'),
                      RottaInfoRow(label: 'Dentro da Faixa', value: op.thermalSummary!.withinRange == true ? 'Sim' : 'Não'),
                      if (op.thermalSummary!.activeExcursion) ...[
                        const SizedBox(height: RottaSpacing.sm),
                        Container(
                          padding: const EdgeInsets.all(RottaSpacing.sm),
                          decoration: BoxDecoration(
                            color: Colors.red.shade50,
                            border: Border.all(color: Colors.red),
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: Row(
                            children: [
                              const Icon(Icons.error_outline, color: Colors.red),
                              const SizedBox(width: RottaSpacing.sm),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    const Text('Temperatura fora da faixa!', style: TextStyle(color: Colors.red, fontWeight: FontWeight.bold)),
                                    Text('Direção: ${op.thermalSummary!.activeExcursionDirection ?? '-'}'),
                                    Text('Início: ${_formatDateTime(op.thermalSummary!.excursionStartedAt)}'),
                                  ],
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ],
                  ]),

                // 8. SLA Section
                if (op.serviceLevel != null)
                  _section('SLA', [
                    Row(
                      children: [
                        const Text('Estado do SLA: ', style: TextStyle(fontWeight: FontWeight.bold)),
                        RottaStatusBadge(status: op.serviceLevel!.state),
                      ],
                    ),
                    const SizedBox(height: RottaSpacing.xs),
                    RottaInfoRow(label: 'Prazo Limite', value: _formatDateTime(op.serviceLevel!.plannedDeadline)),
                    RottaInfoRow(label: 'Atraso Calculado', value: op.serviceLevel!.computedDelayMinutes != null ? '${op.serviceLevel!.computedDelayMinutes} min' : '-'),
                  ]),

                // 9. Timeline Section
                if (op.timeline.isNotEmpty)
                  _section('Timeline', op.timeline.map((event) {
                    return Padding(
                      padding: const EdgeInsets.only(bottom: RottaSpacing.sm),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Icon(Icons.circle, size: 10, color: RottaColors.primary),
                          const SizedBox(width: RottaSpacing.sm),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  event.eventType.replaceAll('_', ' '),
                                  style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 13),
                                ),
                                Text(
                                  'Registrado em: ${_formatDateTime(event.recordedAt)} (${event.source ?? 'backend'})',
                                  style: const TextStyle(fontSize: 11, color: Colors.grey),
                                ),
                                if (event.actorUsername != null)
                                  Text('Por: ${event.actorUsername}', style: const TextStyle(fontSize: 11, color: Colors.grey)),
                                if (event.metadata != null && event.metadata!.isNotEmpty)
                                  Padding(
                                    padding: const EdgeInsets.only(top: 4.0),
                                    child: Text('Info: ${event.metadata}', style: const TextStyle(fontSize: 11, fontStyle: FontStyle.italic)),
                                  ),
                              ],
                            ),
                          ),
                        ],
                      ),
                    );
                  }).toList()),

                // 10. Tracking Section
                _section('Rastreamento de Viagem', [
                  Text(
                    trackingProvider.isTracking
                        ? 'Sessão de rastreamento ativa no momento.'
                        : 'Sem sessão de rastreamento ativa.',
                    style: TextStyle(
                      fontWeight: FontWeight.bold,
                      color: trackingProvider.isTracking ? Colors.green : Colors.grey,
                    ),
                  ),
                  if (trackingProvider.offlinePointsCount > 0) ...[
                    const SizedBox(height: RottaSpacing.xs),
                    Text(
                      'Pontos offline pendentes de sincronização: ${trackingProvider.offlinePointsCount}',
                      style: const TextStyle(color: Colors.orange, fontWeight: FontWeight.bold),
                    ),
                  ],
                  const SizedBox(height: RottaSpacing.md),
                  ElevatedButton(
                    style: ElevatedButton.styleFrom(
                      backgroundColor: trackingProvider.isTracking ? Colors.red : Colors.green,
                      foregroundColor: Colors.white,
                    ),
                    onPressed: () async {
                      if (trackingProvider.isTracking) {
                        await trackingProvider.stopTracking();
                      } else {
                        try {
                          await trackingProvider.startTracking(op.id);
                        } catch (e) {
                          if (mounted) {
                            ScaffoldMessenger.of(context).showSnackBar(
                              SnackBar(content: Text('Falha ao iniciar tracking: $e')),
                            );
                          }
                        }
                      }
                    },
                    child: Text(
                      trackingProvider.isTracking ? 'Parar Rastreamento' : 'Iniciar Rastreamento',
                    ),
                  ),
                ]),

                // 11. POD Section
                _section('POD (Comprovante de Entrega)', [
                  Row(
                    children: [
                      const Text('Status do Comprovante: ', style: TextStyle(fontWeight: FontWeight.bold)),
                      RottaStatusBadge(status: op.pod.status),
                    ],
                  ),
                  if (op.pod.status == 'PENDING' && op.status == 'DELIVERED') ...[
                    const SizedBox(height: RottaSpacing.md),
                    ElevatedButton(
                      style: ElevatedButton.styleFrom(
                        backgroundColor: RottaColors.primary,
                        foregroundColor: Colors.white,
                      ),
                      onPressed: () => _showPodDialog(null),
                      child: const Text('Registrar Comprovante de Entrega'),
                    ),
                  ],
                ]),

                const SizedBox(height: RottaSpacing.xl),
              ],
            ),
          );
        },
      ),
    );
  }
}
