import 'package:flutter/material.dart';
import '../rotta_spacing.dart';

class RottaCard extends StatelessWidget {
  final Widget child;
  final EdgeInsetsGeometry? padding;
  final EdgeInsetsGeometry? margin;
  final VoidCallback? onTap;

  const RottaCard({
    Key? key,
    required this.child,
    this.padding,
    this.margin,
    this.onTap,
  }) : super(key: key);

  @override
  Widget build(BuildContext context) {
    final content = Padding(
      padding: padding ?? const EdgeInsets.all(RottaSpacing.md),
      child: child,
    );
    return Card(
      margin: margin ?? const EdgeInsets.symmetric(vertical: RottaSpacing.sm, horizontal: RottaSpacing.md),
      child: onTap != null ? InkWell(onTap: onTap, child: content) : content,
    );
  }
}
