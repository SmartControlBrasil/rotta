import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:geolocator/geolocator.dart';
import 'package:rotta_driver/core/api/tracking_service.dart';
import 'package:rotta_driver/features/operations/data/operations_repository.dart';

class TrackingProvider extends ChangeNotifier {
  final TrackingService _trackingService;
  final OperationsRepository _repository;

  bool _isTracking = false;
  String? _activeSessionId;
  int _offlinePointsCount = 0;
  String? _error;
  
  Timer? _locationTimer;
  Timer? _syncTimer;
  int _sequence = 1;

  TrackingProvider({
    TrackingService? trackingService,
    OperationsRepository? repository,
  })  : _trackingService = trackingService ?? TrackingService(),
        _repository = repository ?? OperationsRepository() {
    _loadOfflineCount();
  }

  bool get isTracking => _isTracking;
  String? get activeSessionId => _activeSessionId;
  int get offlinePointsCount => _offlinePointsCount;
  String? get error => _error;

  Future<void> _loadOfflineCount() async {
    final queue = await _trackingService.getOfflineQueue();
    _offlinePointsCount = queue.length;
    notifyListeners();
  }

  // Open app settings for deniedForever permissions
  Future<bool> openAppSettings() async {
    return await _trackingService.openAppSettings();
  }

  // Open device location settings when GPS is toggled off
  Future<bool> openLocationSettings() async {
    return await _trackingService.openLocationSettings();
  }

  // Request permissions and start tracking session
  Future<void> startTracking(String operationId) async {
    _error = null;
    notifyListeners();

    // 1. Check if GPS service is enabled on device
    final serviceEnabled = await _trackingService.isLocationServiceEnabled();
    if (!serviceEnabled) {
      _error = 'O serviço de localização (GPS) está desativado no dispositivo.';
      notifyListeners();
      throw Exception(_error);
    }

    // 2. Check & request runtime location permissions
    var permission = await _trackingService.checkLocationPermissions();
    if (permission == LocationPermission.denied) {
      permission = await _trackingService.requestLocationPermissions();
      if (permission == LocationPermission.denied) {
        _error = 'Permissão de localização negada pelo motorista.';
        notifyListeners();
        throw Exception(_error);
      }
    }

    if (permission == LocationPermission.deniedForever) {
      _error = 'Permissão de localização negada permanentemente nas configurações do aplicativo.';
      notifyListeners();
      throw Exception(_error);
    }

    try {
      final sessionId = await _repository.startTracking(operationId);
      _activeSessionId = sessionId;
      _isTracking = true;
      _sequence = 1;
      _startPeriodicTracking();
      _startPeriodicSync();
      notifyListeners();
    } catch (e) {
      _error = e.toString();
      notifyListeners();
      rethrow;
    }
  }


  // End tracking session
  Future<void> stopTracking() async {
    if (!_isTracking || _activeSessionId == null) return;
    
    _locationTimer?.cancel();
    _syncTimer?.cancel();

    try {
      await _repository.endTracking(_activeSessionId!);
    } catch (e) {
      debugPrint('Error ending tracking session on backend: $e');
    } finally {
      _isTracking = false;
      _activeSessionId = null;
      // Final sync attempt
      await _trackingService.syncOfflinePoints();
      await _loadOfflineCount();
      notifyListeners();
    }
  }

  void _startPeriodicTracking() {
    _locationTimer?.cancel();
    // Capture location every 10 seconds (for testing and responsiveness)
    _locationTimer = Timer.periodic(const Duration(seconds: 10), (timer) async {
      if (!_isTracking || _activeSessionId == null) return;

      try {
        final pos = await _trackingService.getCurrentPosition();
        final point = {
          'latitude': pos.latitude,
          'longitude': pos.longitude,
          'accuracy_m': pos.accuracy,
          'speed_kph': pos.speed * 3.6, // convert m/s to km/h
          'heading_deg': pos.heading,
          'altitude_m': pos.altitude,
          'recorded_at': DateTime.now().toUtc().toIso8601String(),
          'sequence': _sequence++,
        };

        try {
          await _repository.sendLocation(
            _activeSessionId!,
            pos.latitude,
            pos.longitude,
            pos.accuracy,
            speed: pos.speed * 3.6,
            heading: pos.heading,
            altitude: pos.altitude,
            recordedAt: DateTime.now(),
            sequence: point['sequence'] as int,
          );
          debugPrint('Location point sent successfully.');
        } catch (e) {
          debugPrint('Failed to send location point, saving offline: $e');
          await _trackingService.saveToOfflineQueue(_activeSessionId!, point);
          await _loadOfflineCount();
        }
      } catch (e) {
        debugPrint('Error getting location: $e');
      }
    });
  }

  void _startPeriodicSync() {
    _syncTimer?.cancel();
    // Attempt syncing offline queue every 30 seconds
    _syncTimer = Timer.periodic(const Duration(seconds: 30), (timer) async {
      await _trackingService.syncOfflinePoints();
      await _loadOfflineCount();
    });
  }

  @override
  void dispose() {
    _locationTimer?.cancel();
    _syncTimer?.cancel();
    super.dispose();
  }
}
