import 'package:flutter/material.dart';
import '../rotta_typography.dart';


class RottaInfoRow extends StatelessWidget {
  final String label;
  final String value;
  const RottaInfoRow({Key? key, required this.label, required this.value}) : super(key: key);
  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(label, style: RottaTypography.body.copyWith(fontWeight: FontWeight.w600)),
        Text(value, style: RottaTypography.body),
      ],
    );
  }
}
