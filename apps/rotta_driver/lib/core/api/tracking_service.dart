import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:geolocator/geolocator.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:rotta_driver/features/operations/data/operations_repository.dart';

class TrackingService {
  final OperationsRepository _repository;
  final FlutterSecureStorage _storage;
  
  static const String _offlineQueueKey = 'tracking_offline_queue';

  TrackingService({
    OperationsRepository? repository,
    FlutterSecureStorage? storage,
  })  : _repository = repository ?? OperationsRepository(),
        _storage = storage ?? const FlutterSecureStorage();

  // Check if location services are enabled and permissions are granted
  Future<LocationPermission> checkLocationPermissions() async {
    bool serviceEnabled = await Geolocator.isLocationServiceEnabled();
    if (!serviceEnabled) {
      return LocationPermission.denied;
    }
    return await Geolocator.checkPermission();
  }

  // Request location permissions
  Future<LocationPermission> requestLocationPermissions() async {
    return await Geolocator.requestPermission();
  }

  // Store a point in the offline queue
  Future<void> saveToOfflineQueue(String sessionUuid, Map<String, dynamic> point) async {
    try {
      final queueStr = await _storage.read(key: _offlineQueueKey);
      List<dynamic> queue = [];
      if (queueStr != null) {
        queue = jsonDecode(queueStr) as List<dynamic>;
      }
      point['session_uuid'] = sessionUuid;
      queue.add(point);
      await _storage.write(key: _offlineQueueKey, value: jsonEncode(queue));
      debugPrint('Saved point to offline queue. Queue size: ${queue.length}');
    } catch (e) {
      debugPrint('Error saving to offline queue: $e');
    }
  }

  // Retrieve all points in the offline queue
  Future<List<Map<String, dynamic>>> getOfflineQueue() async {
    try {
      final queueStr = await _storage.read(key: _offlineQueueKey);
      if (queueStr == null) return [];
      final decoded = jsonDecode(queueStr) as List<dynamic>;
      return decoded.map((e) => Map<String, dynamic>.from(e as Map)).toList();
    } catch (e) {
      debugPrint('Error reading offline queue: $e');
      return [];
    }
  }

  // Clear the offline queue
  Future<void> clearOfflineQueue() async {
    await _storage.delete(key: _offlineQueueKey);
  }

  // Attempt to sync offline points to the backend
  Future<void> syncOfflinePoints() async {
    final points = await getOfflineQueue();
    if (points.isEmpty) return;

    debugPrint('Attempting to sync ${points.length} offline points...');

    // Group by sessionUuid
    final Map<String, List<Map<String, dynamic>>> grouped = {};
    for (final pt in points) {
      final sessionUuid = pt['session_uuid'] as String?;
      if (sessionUuid == null) continue;
      grouped.putIfAbsent(sessionUuid, () => []);
      // Remove session_uuid key from individual point payload
      final cleanPt = Map<String, dynamic>.from(pt)..remove('session_uuid');
      grouped[sessionUuid]!.add(cleanPt);
    }

    bool allSynced = true;
    for (final entry in grouped.entries) {
      final sessionUuid = entry.key;
      final sessionPoints = entry.value;

      try {
        // Send batch in chunks of 50 to avoid hitting limits
        int chunkIdx = 0;
        while (chunkIdx < sessionPoints.length) {
          final end = chunkIdx + 50 > sessionPoints.length ? sessionPoints.length : chunkIdx + 50;
          final chunk = sessionPoints.sublist(chunkIdx, end);
          await _repository.sendLocationBatch(sessionUuid, chunk);
          chunkIdx = end;
        }
        debugPrint('Successfully synced points for session $sessionUuid');
      } catch (e) {
        debugPrint('Failed to sync points for session $sessionUuid: $e');
        allSynced = false;
      }
    }

    if (allSynced) {
      await clearOfflineQueue();
      debugPrint('All offline points synced successfully.');
    } else {
      // Remove successfully synced points or keep all for simple implementation
      final currentQueue = await getOfflineQueue();
      final List<Map<String, dynamic>> remaining = [];
      for (final pt in currentQueue) {
        final sessionUuid = pt['session_uuid'] as String?;
        if (sessionUuid != null && grouped.containsKey(sessionUuid) && grouped[sessionUuid] != null) {
          remaining.add(pt);
        }
      }
      if (remaining.isEmpty) {
        await clearOfflineQueue();
      } else {
        await _storage.write(key: _offlineQueueKey, value: jsonEncode(remaining));
      }
    }
  }

  // Get current position using Geolocator
  Future<Position> getCurrentPosition() async {
    return await Geolocator.getCurrentPosition(
      desiredAccuracy: LocationAccuracy.high,
      timeLimit: const Duration(seconds: 5),
    );
  }
}
