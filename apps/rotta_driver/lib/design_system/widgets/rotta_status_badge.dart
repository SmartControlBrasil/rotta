import 'package:flutter/material.dart';

import '../rotta_spacing.dart';
import '../rotta_colors.dart';
import '../rotta_radius.dart';

class RottaStatusBadge extends StatelessWidget {
  final String status;
  const RottaStatusBadge({Key? key, required this.status}) : super(key: key);

  Color _colorForStatus() {
    switch (status.toLowerCase()) {
      case 'completed':
      case 'delivered':
      case 'compliant':
        return RottaColors.success;
      case 'pending':
      case 'assigned':
        return RottaColors.secondary;
      case 'canceled':
      case 'delayed':
      case 'critical':
        return RottaColors.error;
      default:
        return RottaColors.primary;
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: RottaSpacing.sm, vertical: RottaSpacing.xs),
      decoration: BoxDecoration(
        color: _colorForStatus().withAlpha((0.1 * 255).round()),
        borderRadius: BorderRadius.circular(RottaRadius.sm),
      ),
      child: Text(
        status,
        style: TextStyle(color: _colorForStatus(), fontWeight: FontWeight.bold),
      ),
    );
  }
}
