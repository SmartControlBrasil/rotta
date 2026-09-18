import 'package:flutter/material.dart';
import '../providers/operation_detail_provider.dart';

class DriverOperationActionService {
  static String getActionLabel(String action) {
    switch (action) {
      case 'START_OPERATION':
        return 'Iniciar Operação';
      case 'ARRIVE_PICKUP':
        return 'Cheguei à Coleta';
      case 'START_LOADING':
        return 'Iniciar Carregamento';
      case 'START_TRANSIT':
        return 'Iniciar Viagem';
      case 'ARRIVE_DELIVERY':
        return 'Cheguei ao Destino';
      case 'START_UNLOADING':
        return 'Iniciar Descarregamento';
      case 'COMPLETE_OPERATION':
        return 'Finalizar Operação';
      case 'ARRIVE_STOP':
        return 'Cheguei à Parada';
      case 'COMPLETE_STOP':
        return 'Concluir Parada';
      case 'SUBMIT_POD':
        return 'Registrar Comprovante (POD)';
      case 'REPORT_INCIDENT':
        return 'Reportar Incidente';
      case 'START_TRACKING':
        return 'Iniciar Rastreamento';
      case 'END_TRACKING':
        return 'Encerrar Rastreamento';
      default:
        return '';
    }
  }

  static bool isMainAction(String action) {
    return [
      'START_OPERATION',
      'ARRIVE_PICKUP',
      'START_LOADING',
      'START_TRANSIT',
      'ARRIVE_DELIVERY',
      'START_UNLOADING',
      'COMPLETE_OPERATION',
      'ARRIVE_STOP',
      'COMPLETE_STOP',
      'SUBMIT_POD'
    ].contains(action);
  }

  static Future<void> executeAction({
    required BuildContext context,
    required OperationDetailProvider provider,
    required String action,
    required String operationId,
    String? stopId,
    required VoidCallback onShowIncidentDialog,
    required VoidCallback onShowPodDialog,
    required Future<void> Function() onToggleTracking,
  }) async {
    switch (action) {
      case 'START_OPERATION':
        await provider.advanceStatus(operationId, 'DRIVER_EN_ROUTE_TO_PICKUP');
        break;
      case 'ARRIVE_PICKUP':
        await provider.advanceStatus(operationId, 'ARRIVED_AT_PICKUP');
        break;
      case 'START_LOADING':
        await provider.advanceStatus(operationId, 'LOADING');
        break;
      case 'START_TRANSIT':
        await provider.advanceStatus(operationId, 'IN_TRANSIT');
        break;
      case 'ARRIVE_DELIVERY':
        await provider.advanceStatus(operationId, 'ARRIVED_AT_DELIVERY');
        break;
      case 'START_UNLOADING':
        await provider.advanceStatus(operationId, 'UNLOADING');
        break;
      case 'COMPLETE_OPERATION':
        await provider.advanceStatus(operationId, 'DELIVERED');
        break;
      case 'ARRIVE_STOP':
        if (stopId == null) throw Exception('Stop ID is required for ARRIVE_STOP');
        await provider.advanceStopStatus(operationId, stopId, 'ARRIVED');
        break;
      case 'COMPLETE_STOP':
        if (stopId == null) throw Exception('Stop ID is required for COMPLETE_STOP');
        await provider.advanceStopStatus(operationId, stopId, 'COMPLETED');
        break;
      case 'SUBMIT_POD':
        onShowPodDialog();
        break;
      case 'REPORT_INCIDENT':
        onShowIncidentDialog();
        break;
      case 'START_TRACKING':
      case 'END_TRACKING':
        await onToggleTracking();
        break;
      default:
        debugPrint('Unknown action received and ignored: $action');
    }
  }
}
