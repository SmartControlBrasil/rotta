import 'package:flutter/material.dart';
import 'package:rotta_driver/design_system/rotta_spacing.dart';
import 'package:rotta_driver/design_system/rotta_typography.dart';
import 'package:rotta_driver/design_system/widgets/rotta_card.dart';
import 'package:rotta_driver/design_system/widgets/rotta_info_row.dart';
import 'package:rotta_driver/features/operations/data/models.dart' show TemperatureControl;

class RottaConditionCard extends StatelessWidget {
  final TemperatureControl? temperatureControl;

  const RottaConditionCard({Key? key, this.temperatureControl}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    if (temperatureControl == null) return const SizedBox.shrink();
    return RottaCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Condição da carga', style: RottaTypography.subtitleBold),
          const SizedBox(height: RottaSpacing.sm),
          RottaInfoRow(
            label: 'Temp. mínima (°C)',
            value: temperatureControl!.minC?.toStringAsFixed(1) ?? '-',
          ),
          RottaInfoRow(
            label: 'Temp. máxima (°C)',
            value: temperatureControl!.maxC?.toStringAsFixed(1) ?? '-',
          ),
          RottaInfoRow(
            label: 'Temp. alvo (°C)',
            value: temperatureControl!.targetC?.toStringAsFixed(1) ?? '-',
          ),
        ],
      ),
    );
  }
}
