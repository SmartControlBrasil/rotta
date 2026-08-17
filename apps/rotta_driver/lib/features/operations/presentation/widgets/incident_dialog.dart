import 'package:flutter/material.dart';
import 'package:rotta_driver/design_system/rotta_spacing.dart';
import 'package:rotta_driver/design_system/widgets/rotta_primary_button.dart';

class IncidentDialog extends StatefulWidget {
  final Future<void> Function(String description) onSubmit;

  const IncidentDialog({Key? key, required this.onSubmit}) : super(key: key);

  @override
  State<IncidentDialog> createState() => _IncidentDialogState();
}

class _IncidentDialogState extends State<IncidentDialog> {
  final _formKey = GlobalKey<FormState>();
  final _controller = TextEditingController();
  bool _loading = false;
  String? _error;

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      await widget.onSubmit(_controller.text.trim());
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
                'Registrar Incidente',
                style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold),
              ),
              const SizedBox(height: RottaSpacing.md),
              TextFormField(
                controller: _controller,
                maxLines: 4,
                decoration: const InputDecoration(
                  labelText: 'Descrição do ocorrido',
                  hintText: 'Descreva detalhadamente o incidente operacional...',
                  border: OutlineInputBorder(),
                  alignLabelWithHint: true,
                ),
                validator: (v) => v == null || v.isEmpty ? 'Por favor, descreva o incidente' : null,
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
                    width: 120,
                    child: RottaPrimaryButton(
                      onPressed: _loading ? null : _submit,
                      loading: _loading,
                      child: const Text('Enviar'),
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
