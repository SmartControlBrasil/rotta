import 'package:flutter/material.dart';
import 'package:rotta_driver/design_system/rotta_spacing.dart';
import 'package:rotta_driver/design_system/rotta_typography.dart';
import 'package:rotta_driver/design_system/widgets/rotta_card.dart';

class RottaRouteCard extends StatelessWidget {
  final String? origin;
  final String? destination;
  final int? stopsCount;
  final String? scheduledDate;

  const RottaRouteCard({Key? key, this.origin, this.destination, this.stopsCount, this.scheduledDate}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return RottaCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Rota', style: RottaTypography.subtitleBold),
          const SizedBox(height: RottaSpacing.sm),
          Row(
            children: [
              Expanded(child: Text(origin ?? '-', style: RottaTypography.bodyRegular)),
              const Icon(Icons.arrow_downward, size: 16, color: Color(0xFF777777)),
              Expanded(child: Text(destination ?? '-', style: RottaTypography.bodyRegular)),
            ],
          ),
          if (stopsCount != null) ...[
            const SizedBox(height: RottaSpacing.sm),
            Text(' paradas', style: RottaTypography.caption),
          ],
          if (scheduledDate != null) ...[
            const SizedBox(height: RottaSpacing.sm),
            Text('Previsto: ', style: RottaTypography.caption),
          ],
        ],
      ),
    );
  }
}
