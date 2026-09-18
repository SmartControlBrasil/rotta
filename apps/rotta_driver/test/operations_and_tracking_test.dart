import 'dart:async';
import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:rotta_driver/features/operations/data/models.dart';
import 'package:rotta_driver/features/operations/data/operations_repository.dart';
import 'package:rotta_driver/features/operations/presentation/providers/operation_detail_provider.dart';
import 'package:rotta_driver/core/api/api_client.dart';
import 'package:rotta_driver/core/config/config.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;

class MockClient extends http.BaseClient {
  final Future<http.Response> Function(http.BaseRequest request) mockHandler;

  MockClient(this.mockHandler);

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    final res = await mockHandler(request);
    final controller = StreamController<List<int>>();
    controller.add(res.bodyBytes);
    controller.close();
    return http.StreamedResponse(
      controller.stream,
      res.statusCode,
      contentLength: res.contentLength,
      headers: res.headers,
      isRedirect: res.isRedirect,
      persistentConnection: res.persistentConnection,
      reasonPhrase: res.reasonPhrase,
      request: request,
    );
  }
}


void main() {
  setUpAll(() async {
    TestWidgetsFlutterBinding.ensureInitialized();
    const channel = MethodChannel('plugins.it_nomads.com/flutter_secure_storage');
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (MethodCall methodCall) async {
      if (methodCall.method == 'read') {
        if (methodCall.arguments['key'] == 'access_token') {
          return 'mock_access_token';
        }
        if (methodCall.arguments['key'] == 'expires_at') {
          return ((DateTime.now().millisecondsSinceEpoch ~/ 1000) + 3600).toString();
        }
      }
      return null;
    });
    await Config.load();
  });

  group('Model Deserialization Tests', () {
    test('OperationDetail parses enriched logistics payload successfully', () {
      final jsonPayload = {
        'id': 'a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d',
        'status': 'IN_TRANSIT',
        'reference_code': 'ROT-10029',
        'carrier': {'id': 'carrier-uuid', 'trade_name': 'TransRotta'},
        'driver': {'id': 'driver-uuid', 'full_name': 'John Doe'},
        'vehicle': {'id': 'vehicle-uuid', 'plate': 'ABC-1234'},
        'stops': [
          {
            'sequence': 1,
            'stop_type': 'PICKUP',
            'city': 'São Paulo',
            'state': 'SP',
            'street': 'Av. Paulista',
            'number': '1000',
            'scheduled_date': '2026-08-16',
            'window_start': '08:00',
            'window_end': '12:00',
          }
        ],
        'cargo': {
          'description': 'Carga Refrigerada de Teste',
          'cargo_type': 'FOOD',
          'cargo_profile': 'REFRIGERATED',
          'weight_kg': 1500.5,
          'volume_m3': 12.0,
          'temperature_control': {
            'min_c': 2.0,
            'max_c': 8.0,
            'target_c': 5.0,
          }
        },
        'tracking': {
          'has_active_session': true,
          'active_session_id': 'session-uuid',
        },
        'pod': {
          'status': 'PENDING',
        },
        'load_type': 'FTL',
        'eta': '2026-08-16T18:00:00Z',
        'delay_minutes': 15,
        'service_level': {
          'state': 'DELAYED',
          'planned_deadline': '2026-08-16T17:45:00Z',
          'computed_delay_minutes': 15,
        },
        'timeline': [
          {
            'id': 'event-uuid-1',
            'event_type': 'STATUS_CHANGED',
            'occurred_at': '2026-08-16T10:00:00Z',
            'recorded_at': '2026-08-16T10:01:00Z',
            'actor': {'id': 'user-uuid', 'username': 'dispatcher1'},
            'source': 'backoffice',
            'metadata': {'old_status': 'ASSIGNED', 'new_status': 'DRIVER_EN_ROUTE_TO_PICKUP'},
          }
        ],
        'thermal_summary': {
          'latest_temperature_c': 5.5,
          'latest_sensor_timestamp': '2026-08-16T11:30:00Z',
          'validity': true,
          'quality': 'EXCELLENT',
          'within_range': true,
          'active_excursion': false,
          'active_excursion_direction': null,
          'excursion_started_at': null,
        }
      };

      final detail = OperationDetail.fromJson(jsonPayload);

      expect(detail.id, 'a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d');
      expect(detail.status, 'IN_TRANSIT');
      expect(detail.referenceCode, 'ROT-10029');
      expect(detail.loadType, 'FTL');
      expect(detail.eta, '2026-08-16T18:00:00Z');
      expect(detail.delayMinutes, 15);
      expect(detail.serviceLevel, isNotNull);
      expect(detail.serviceLevel!.state, 'DELAYED');
      expect(detail.serviceLevel!.computedDelayMinutes, 15);
      expect(detail.timeline.length, 1);
      expect(detail.timeline[0].eventType, 'STATUS_CHANGED');
      expect(detail.timeline[0].actorUsername, 'dispatcher1');
      expect(detail.thermalSummary, isNotNull);
      expect(detail.thermalSummary!.latestTemperatureC, 5.5);
      expect(detail.thermalSummary!.activeExcursion, false);
    });
  });

  group('OperationsRepository Integration Tests', () {
    test('listOperations returns summary list on success', () async {
      final mockResponse = {
        'count': 1,
        'next': null,
        'previous': null,
        'results': [
          {
            'id': 'op-uuid',
            'status': 'ASSIGNED',
            'reference_code': 'ROT-1002',
            'assigned_at': '2026-08-16T10:00:00Z',
            'origin': 'São Paulo',
            'destination': 'Rio de Janeiro',
            'load_type': 'LTL',
            'service_level_state': 'COMPLIANT',
          }
        ]
      };

      final client = ApiClient(
        client: MockClient((req) async {
          expect(req.url.path, '/api/v1/driver/operations/');
          return http.Response(jsonEncode(mockResponse), 200);
        }),
      );

      final repo = OperationsRepository(client: client);
      final list = await repo.listOperations();

      expect(list.length, 1);
      expect(list[0].id, 'op-uuid');
      expect(list[0].loadType, 'LTL');
      expect(list[0].serviceLevelState, 'COMPLIANT');
    });

    test('advanceStatus posts and updates status', () async {
      final client = ApiClient(
        client: MockClient((req) async {
          expect(req.url.path, '/api/v1/driver/operations/op-uuid/advance-status/');
          final body = jsonDecode((req as http.Request).body);
          expect(body['next_status'], 'DRIVER_EN_ROUTE_TO_PICKUP');
          return http.Response(jsonEncode({'id': 'op-uuid', 'status': 'DRIVER_EN_ROUTE_TO_PICKUP'}), 200);
        }),
      );

      final repo = OperationsRepository(client: client);
      await expectLater(
        repo.advanceStatus('op-uuid', 'DRIVER_EN_ROUTE_TO_PICKUP'),
        completes,
      );
    });

    test('reportIncident posts description', () async {
      final client = ApiClient(
        client: MockClient((req) async {
          expect(req.url.path, '/api/v1/driver/operations/op-uuid/incidents/');
          final body = jsonDecode((req as http.Request).body);
          expect(body['description'], 'Pneu furado na BR-116');
          return http.Response(jsonEncode({'id': 'event-uuid'}), 201);
        }),
      );

      final repo = OperationsRepository(client: client);
      await expectLater(
        repo.reportIncident('op-uuid', 'Pneu furado na BR-116'),
        completes,
      );
    });

    test('recordPOD posts POD information with stopId', () async {
      final now = DateTime.now();
      final client = ApiClient(
        client: MockClient((req) async {
          expect(req.url.path, '/api/v1/driver/operations/op-uuid/pod/');
          final body = jsonDecode((req as http.Request).body);
          expect(body['receiver_name'], 'Carlos Recebedor');
          expect(body['latitude'], -23.5505);
          expect(body['longitude'], -46.6333);
          expect(body['notes'], 'Entregue com sucesso');
          expect(body['stop_id'], 'stop-uuid');
          return http.Response(jsonEncode({'id': 'pod-uuid', 'status': 'SUBMITTED'}), 201);
        }),
      );

      final repo = OperationsRepository(client: client);
      await expectLater(
        repo.recordPOD(
          'op-uuid',
          'Carlos Recebedor',
          now,
          latitude: -23.5505,
          longitude: -46.6333,
          notes: 'Entregue com sucesso',
          stopId: 'stop-uuid',
        ),
        completes,
      );
    });

    test('advanceStopStatus posts correct nextStatus', () async {
      final client = ApiClient(
        client: MockClient((req) async {
          expect(req.url.path, '/api/v1/driver/operations/op-uuid/stops/stop-uuid/advance-status/');
          final body = jsonDecode((req as http.Request).body);
          expect(body['next_status'], 'ARRIVED');
          return http.Response(jsonEncode({'id': 'stop-uuid', 'status': 'ARRIVED'}), 200);
        }),
      );

      final repo = OperationsRepository(client: client);
      await expectLater(
        repo.advanceStopStatus('op-uuid', 'stop-uuid', 'ARRIVED'),
        completes,
      );
    });
  });

  group('Provider Tests', () {
    test('OperationDetailProvider processes load, macro and stop status transitions', () async {
      final detailPayload = {
        'id': 'op-uuid',
        'status': 'ASSIGNED',
        'stops': [
          {
            'id': 'stop-uuid',
            'sequence': 1,
            'stop_type': 'PICKUP',
            'status': 'PENDING',
            'has_pod': false,
          }
        ],
        'next_stop': {
          'id': 'stop-uuid',
          'sequence': 1,
          'stop_type': 'PICKUP',
          'status': 'PENDING',
          'has_pod': false,
        },
        'available_actions': [
          {'action': 'START_OPERATION', 'label': 'Iniciar Operação', 'enabled': true},
          {'action': 'REPORT_INCIDENT', 'label': 'Reportar Incidente', 'enabled': true},
        ],
        'tracking': {'has_active_session': false},
        'pod': {'status': 'PENDING'},
      };

      final client = ApiClient(
        client: MockClient((req) async {
          if (req.method == 'GET') {
            return http.Response(jsonEncode(detailPayload), 200);
          } else if (req.method == 'POST' && req.url.path.contains('advance-status') && !req.url.path.contains('stops')) {
            detailPayload['status'] = 'DRIVER_EN_ROUTE_TO_PICKUP';
            detailPayload['available_actions'] = [
              {'action': 'ARRIVE_STOP', 'label': 'Cheguei à Parada', 'enabled': true},
            ];
            return http.Response(jsonEncode({'id': 'op-uuid', 'status': 'DRIVER_EN_ROUTE_TO_PICKUP'}), 200);
          } else if (req.method == 'POST' && req.url.path.contains('stops/stop-uuid/advance-status')) {
            final stops = detailPayload['stops'] as List<dynamic>;
            stops[0]['status'] = 'ARRIVED';
            (detailPayload['next_stop'] as Map<String, dynamic>)['status'] = 'ARRIVED';
            detailPayload['available_actions'] = [
              {'action': 'COMPLETE_STOP', 'label': 'Concluir Parada', 'enabled': true},
            ];
            return http.Response(jsonEncode({'id': 'stop-uuid', 'status': 'ARRIVED'}), 200);
          }
          return http.Response('Not Found', 404);
        }),
      );

      final repo = OperationsRepository(client: client);
      final provider = OperationDetailProvider(repository: repo);

      expect(provider.isLoading, false);
      expect(provider.operation, null);

      await provider.loadDetail('op-uuid');
      expect(provider.isLoading, false);
      expect(provider.operation, isNotNull);
      expect(provider.operation!.status, 'ASSIGNED');
      expect(provider.operation!.nextStop, isNotNull);
      expect(provider.operation!.nextStop!.id, 'stop-uuid');
      expect(provider.operation!.availableActions.map((a) => a.action), contains('START_OPERATION'));

      await provider.advanceStatus('op-uuid', 'DRIVER_EN_ROUTE_TO_PICKUP');
      expect(provider.operation!.status, 'DRIVER_EN_ROUTE_TO_PICKUP');
      expect(provider.operation!.availableActions.map((a) => a.action), contains('ARRIVE_STOP'));

      await provider.advanceStopStatus('op-uuid', 'stop-uuid', 'ARRIVED');
      expect(provider.operation!.nextStop!.status, 'ARRIVED');
      expect(provider.operation!.availableActions.map((a) => a.action), contains('COMPLETE_STOP'));
    });
  });
}
