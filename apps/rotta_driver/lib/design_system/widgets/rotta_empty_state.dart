import 'package:flutter/material.dart';
import '../rotta_typography.dart';
import '../rotta_spacing.dart';

class RottaEmptyState extends StatelessWidget {
  final String message;
  const RottaEmptyState({Key? key, required this.message}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(RottaSpacing.md),
        child: Text(
          message,
          style: RottaTypography.body.copyWith(color: Colors.grey),
          textAlign: TextAlign.center,
        ),
      ),
    );
  }
}
