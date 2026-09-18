import 'dart:convert';
import 'package:rotta_driver/core/api/api_client.dart';
import '../data/models.dart';

class OperationsRepository {
  final ApiClient _client;

  OperationsRepository({ApiClient? client}) : _client = client ?? ApiClient();

  Future<List<OperationSummary>> listOperations({int page = 1, int pageSize = 10}) async {
    final response = await _client.get('/api/v1/driver/operations/', queryParameters: {
      'page': page.toString(),
      'page_size': pageSize.toString(),
    });
    if (response.statusCode != 200) {
      throw Exception('Failed to fetch operations (status ${response.statusCode})');
    }
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    final results = data['results'] as List<dynamic>;
    return results.map((e) => OperationSummary.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<OperationDetail> getOperation(String id) async {
    final response = await _client.get('/api/v1/driver/operations/$id/');
    if (response.statusCode != 200) {
      throw Exception('Failed to fetch operation detail (status ${response.statusCode})');
    }
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    return OperationDetail.fromJson(data);
  }

  Future<void> advanceStatus(String id, String nextStatus) async {
    final response = await _client.post(
      '/api/v1/driver/operations/$id/advance-status/',
      body: {'next_status': nextStatus},
    );
    if (response.statusCode != 200) {
      final body = jsonDecode(response.body);
      throw Exception(body['message'] ?? 'Failed to advance status');
    }
  }

  Future<void> reportIncident(String id, String description) async {
    final response = await _client.post(
      '/api/v1/driver/operations/$id/incidents/',
      body: {'description': description},
    );
    if (response.statusCode != 201) {
      final body = jsonDecode(response.body);
      throw Exception(body['message'] ?? 'Failed to report incident');
    }
  }

  Future<void> recordPOD(
    String id,
    String receiverName,
    DateTime deliveredAt, {
    double? latitude,
    double? longitude,
    String? notes,
    String? stopId,
  }) async {
    final Map<String, dynamic> body = {
      'receiver_name': receiverName,
      'delivered_at': deliveredAt.toUtc().toIso8601String(),
    };
    if (latitude != null) body['latitude'] = latitude;
    if (longitude != null) body['longitude'] = longitude;
    if (notes != null) body['notes'] = notes;
    if (stopId != null) body['stop_id'] = stopId;

    final response = await _client.post(
      '/api/v1/driver/operations/$id/pod/',
      body: body,
    );
    if (response.statusCode != 201) {
      final resBody = jsonDecode(response.body);
      throw Exception(resBody['message'] ?? 'Failed to record POD');
    }
  }

  Future<void> advanceStopStatus(String id, String stopId, String nextStatus) async {
    final response = await _client.post(
      '/api/v1/driver/operations/$id/stops/$stopId/advance-status/',
      body: {'next_status': nextStatus},
    );
    if (response.statusCode != 200) {
      final body = jsonDecode(response.body);
      throw Exception(body['message'] ?? 'Failed to advance stop status');
    }
  }

  Future<String> startTracking(String id) async {
    final response = await _client.post(
      '/api/v1/driver/operations/$id/tracking/start/',
      body: {'source': 'mobile'},
    );
    if (response.statusCode != 201) {
      final body = jsonDecode(response.body);
      throw Exception(body['message'] ?? 'Failed to start tracking');
    }
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    return data['tracking_session_id'] as String;
  }

  Future<void> sendLocation(
    String sessionUuid,
    double latitude,
    double longitude,
    double accuracy, {
    double? speed,
    double? heading,
    double? altitude,
    DateTime? recordedAt,
    int? sequence,
  }) async {
    final Map<String, dynamic> body = {
      'latitude': latitude,
      'longitude': longitude,
      'accuracy_m': accuracy,
      'recorded_at': (recordedAt ?? DateTime.now()).toUtc().toIso8601String(),
    };
    if (speed != null) body['speed_kph'] = speed;
    if (heading != null) body['heading_deg'] = heading;
    if (altitude != null) body['altitude_m'] = altitude;
    if (sequence != null) body['sequence'] = sequence;

    final response = await _client.post(
      '/api/v1/tracking/$sessionUuid/locations/',
      body: body,
    );
    if (response.statusCode != 201) {
      final resBody = jsonDecode(response.body);
      throw Exception(resBody['message'] ?? 'Failed to send location');
    }
  }

  Future<void> sendLocationBatch(String sessionUuid, List<Map<String, dynamic>> points) async {
    final response = await _client.post(
      '/api/v1/tracking/$sessionUuid/locations/batch/',
      body: points, // ApiClient expects Map<String, dynamic>? but we can encode directly or update ApiClient
    );
    if (response.statusCode != 201) {
      throw Exception('Failed to send locations batch');
    }
  }

  Future<void> endTracking(String sessionUuid) async {
    final response = await _client.post(
      '/api/v1/tracking/$sessionUuid/end/',
    );
    if (response.statusCode != 200) {
      final body = jsonDecode(response.body);
      throw Exception(body['message'] ?? 'Failed to end tracking');
    }
  }
}
