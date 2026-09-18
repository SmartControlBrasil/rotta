import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:rotta_driver/core/api/tracking_service.dart';
import 'package:rotta_driver/design_system/rotta_spacing.dart';
import 'package:rotta_driver/design_system/widgets/rotta_primary_button.dart';

class PodDialog extends StatefulWidget {
  final String? stopId;
  final Future<void> Function(
    String receiverName,
    DateTime deliveredAt, {
    double? latitude,
    double? longitude,
    String? notes,
    String? stopId,
  }) onSubmit;

  const PodDialog({Key? key, required this.onSubmit, this.stopId}) : super(key: key);

  @override
  State<PodDialog> createState() => _PodDialogState();
}

class _PodDialogState extends State<PodDialog> {
  final _formKey = GlobalKey<FormState>();
  final _nameController = TextEditingController();
  final _notesController = TextEditingController();
  final _trackingService = TrackingService();

  bool _loading = false;
  String? _error;
  Position? _currentPosition;
  bool _fetchingGps = false;

  @override
  void initState() {
    super.initState();
    _fetchGpsLocation();
  }

  Future<void> _fetchGpsLocation() async {
    setState(() => _fetchingGps = true);
    try {
      final permission = await _trackingService.checkLocationPermissions();
      if (permission == LocationPermission.whileInUse || permission == LocationPermission.always) {
        final pos = await _trackingService.getCurrentPosition();
        setState(() => _currentPosition = pos);
      }
    } catch (e) {
      debugPrint('Could not retrieve GPS for POD: $e');
    } finally {
      setState(() => _fetchingGps = false);
    }
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      await widget.onSubmit(
        _nameController.text.trim(),
        DateTime.now(),
        latitude: _currentPosition?.latitude,
        longitude: _currentPosition?.longitude,
        notes: _notesController.text.trim().isEmpty ? null : _notesController.text.trim(),
        stopId: widget.stopId,
      );
      if (mounted) Navigator.of(context).pop(true);
    } catch (e) {
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Dialog(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.all(RottaSpacing.lg),
        child: Form(
          key: _formKey,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                'Comprovante de Entrega (POD)',
                style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: RottaSpacing.md),
              TextFormField(
                controller: _nameController,
                decoration: const InputDecoration(
                  labelText: 'Nome do recebedor *',
                  hintText: 'Quem assinou/recebeu a carga...',
                  border: OutlineInputBorder(),
                ),
                validator: (v) => v == null || v.isEmpty ? 'Informe o nome do recebedor' : null,
              ),
              const SizedBox(height: RottaSpacing.md),
              TextFormField(
                controller: _notesController,
                maxLines: 2,
                decoration: const InputDecoration(
                  labelText: 'Observações (Opcional)',
                  hintText: 'Alguma divergência ou comentário adicional...',
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: RottaSpacing.md),
              Row(
                children: [
                  Icon(
                    _currentPosition != null
                        ? Icons.gps_fixed
                        : (_fetchingGps ? Icons.gps_not_fixed : Icons.gps_off),
                    color: _currentPosition != null ? Colors.green : Colors.grey,
                    size: 16,
                  ),
                  const SizedBox(width: RottaSpacing.xs),
                  Expanded(
                    child: Text(
                      _currentPosition != null
                          ? 'Localização GPS capturada'
                          : (_fetchingGps ? 'Buscando sinal GPS...' : 'GPS indisponível'),
                      style: TextStyle(
                        fontSize: 12,
                        color: _currentPosition != null ? Colors.green : Colors.grey,
                      ),
                    ),
                  ),
                ],
              ),
              if (_error != null) ...[
                const SizedBox(height: RottaSpacing.sm),
                Text(
                  _error!,
                  style: const TextStyle(color: Colors.red, fontSize: 13),
                ),
              ],
              const SizedBox(height: RottaSpacing.md),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  TextButton(
                    onPressed: _loading ? null : () => Navigator.of(context).pop(),
                    child: const Text('Cancelar'),
                  ),
                  const SizedBox(width: RottaSpacing.sm),
                  SizedBox(
                    width: 130,
                    child: RottaPrimaryButton(
                      onPressed: _loading ? null : _submit,
                      loading: _loading,
                      child: const Text('Confirmar POD'),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
