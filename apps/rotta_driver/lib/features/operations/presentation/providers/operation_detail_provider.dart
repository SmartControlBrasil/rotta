import 'package:flutter/foundation.dart';
import 'package:rotta_driver/features/operations/data/models.dart';
import 'package:rotta_driver/features/operations/data/operations_repository.dart';

class OperationDetailProvider extends ChangeNotifier {
  final OperationsRepository _repository;

  OperationDetail? _operation;
  bool _isLoading = false;
  bool _isSubmitting = false;
  String? _error;

  OperationDetailProvider({OperationsRepository? repository})
      : _repository = repository ?? OperationsRepository();

  OperationDetail? get operation => _operation;
  bool get isLoading => _isLoading;
  bool get isSubmitting => _isSubmitting;
  String? get error => _error;

  Future<void> loadDetail(String id) async {
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      _operation = await _repository.getOperation(id);
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> advanceStatus(String id, String nextStatus) async {
    _isSubmitting = true;
    _error = null;
    notifyListeners();

    try {
      await _repository.advanceStatus(id, nextStatus);
      // Reload operation details to get the new state/timeline from backend
      _operation = await _repository.getOperation(id);
    } catch (e) {
      _error = e.toString();
      rethrow;
    } finally {
      _isSubmitting = false;
      notifyListeners();
    }
  }

  Future<void> reportIncident(String id, String description) async {
    _isSubmitting = true;
    _error = null;
    notifyListeners();

    try {
      await _repository.reportIncident(id, description);
      // Reload details to update the timeline
      _operation = await _repository.getOperation(id);
    } catch (e) {
      _error = e.toString();
      rethrow;
    } finally {
      _isSubmitting = false;
      notifyListeners();
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
    _isSubmitting = true;
    _error = null;
    notifyListeners();

    try {
      await _repository.recordPOD(
        id,
        receiverName,
        deliveredAt,
        latitude: latitude,
        longitude: longitude,
        notes: notes,
        stopId: stopId,
      );
      // Reload details
      _operation = await _repository.getOperation(id);
    } catch (e) {
      _error = e.toString();
      rethrow;
    } finally {
      _isSubmitting = false;
      notifyListeners();
    }
  }

  Future<void> advanceStopStatus(String id, String stopId, String nextStatus) async {
    _isSubmitting = true;
    _error = null;
    notifyListeners();

    try {
      await _repository.advanceStopStatus(id, stopId, nextStatus);
      // Reload details
      _operation = await _repository.getOperation(id);
    } catch (e) {
      _error = e.toString();
      rethrow;
    } finally {
      _isSubmitting = false;
      notifyListeners();
    }
  }
}
