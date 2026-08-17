import 'package:flutter/material.dart';
import 'package:rotta_driver/design_system/rotta_spacing.dart';
import 'package:rotta_driver/design_system/rotta_typography.dart';
import 'package:rotta_driver/design_system/widgets/rotta_card.dart';
import 'package:rotta_driver/design_system/widgets/rotta_info_row.dart';

class RottaServiceLevelCard extends StatelessWidget {
  final String? assignedAt;
  final String? plannedPickupAt;
  final String? plannedDeliveryAt;

  const RottaServiceLevelCard({
    Key? key,
    this.assignedAt,
    this.plannedPickupAt,
    this.plannedDeliveryAt,
  }) : super(key: key);

  @override
  Widget build(BuildContext context) {
    final List<Widget> rows = [];
    if (assignedAt != null) {
      rows.add(RottaInfoRow(label: 'Atribuída em', value: assignedAt!));
    }
    if (plannedPickupAt != null) {
      rows.add(RottaInfoRow(label: 'Coleta prevista', value: plannedPickupAt!));
    }
    if (plannedDeliveryAt != null) {
      rows.add(RottaInfoRow(label: 'Entrega prevista', value: plannedDeliveryAt!));
    }
    if (rows.isEmpty) return const SizedBox.shrink();
    return RottaCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Nível de Serviço', style: RottaTypography.subtitleBold),
          const SizedBox(height: RottaSpacing.sm),
          ...rows,
        ],
      ),
    );
  }
}


