import 'package:flutter/material.dart';

import '../rotta_theme.dart';

class RottaLoading extends StatelessWidget {
  const RottaLoading({Key? key}) : super(key: key);
  @override
  Widget build(BuildContext context) {
    return Center(
      child: SizedBox(
        width: 40,
        height: 40,
        child: CircularProgressIndicator(
          strokeWidth: 3,
          color: RottaTheme.lightTheme.colorScheme.primary,
        ),
      ),
    );
  }
}
