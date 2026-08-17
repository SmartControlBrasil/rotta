import 'package:flutter/material.dart';
import 'package:rotta_driver/design_system/rotta_spacing.dart';
import 'package:rotta_driver/design_system/rotta_typography.dart';
import 'package:rotta_driver/design_system/widgets/rotta_primary_button.dart';

class RottaErrorState extends StatelessWidget {
  final String message;
  final VoidCallback onRetry;

  const RottaErrorState({Key? key, required this.message, required this.onRetry}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(RottaSpacing.md),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(message, style: RottaTypography.bodyMedium, textAlign: TextAlign.center),
            const SizedBox(height: RottaSpacing.sm),
            RottaPrimaryButton(onPressed: onRetry, child: const Text('Tentar novamente'),),
          ],
        ),
      ),
    );
  }
}
