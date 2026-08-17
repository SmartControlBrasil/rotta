import 'package:flutter/material.dart';
import 'package:rotta_driver/design_system/widgets/rotta_info_row.dart';
import 'package:rotta_driver/design_system/widgets/rotta_card.dart';
import 'package:rotta_driver/design_system/rotta_spacing.dart';
import 'package:rotta_driver/design_system/rotta_typography.dart';
import 'package:rotta_driver/features/operations/data/models.dart' show TemperatureControl;

class RottaCargoCard extends StatelessWidget {
  final String? description;
  final String? cargoType;
  final String? cargoProfile;
  final double? weightKg;
  final double? volumeM3;
  final TemperatureControl? temperatureControl;

  const RottaCargoCard({
    Key? key,
    this.description,
    this.cargoType,
    this.cargoProfile,
    this.weightKg,
    this.volumeM3,
    this.temperatureControl,
  }) : super(key: key);

  String _profileLabel(String? code) {
    switch (code) {
      case 'DRY_CARGO':
        return 'Carga seca';
      case 'REFRIGERATED_CARGO':
        return 'Carga refrigerada';
      default:
        return code ?? '-';
    }
  }

  @override
  Widget build(BuildContext context) {
    return RottaCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Carga', style: RottaTypography.subtitleBold),
          const SizedBox(height: RottaSpacing.sm),
          if (description != null) RottaInfoRow(label: 'Descrição', value: description!),
          if (cargoType != null) RottaInfoRow(label: 'Tipo', value: cargoType!),
          if (cargoProfile != null) RottaInfoRow(label: 'Perfil', value: _profileLabel(cargoProfile)),
          if (weightKg != null) RottaInfoRow(label: 'Peso (kg)', value: weightKg!.toStringAsFixed(2)),
          if (volumeM3 != null) RottaInfoRow(label: 'Volume (m³)', value: volumeM3!.toStringAsFixed(2)),
          if (temperatureControl != null) ...[
            const SizedBox(height: RottaSpacing.sm),
            RottaInfoRow(label: 'Temp. mínima (°C)', value: temperatureControl!.minC?.toStringAsFixed(1) ?? '-'),
            RottaInfoRow(label: 'Temp. máxima (°C)', value: temperatureControl!.maxC?.toStringAsFixed(1) ?? '-'),
            RottaInfoRow(label: 'Temp. alvo (°C)', value: temperatureControl!.targetC?.toStringAsFixed(1) ?? '-'),
          ],
        ],
      ),
    );
  }
}

// TemperatureControl model reference (import from models if needed)

