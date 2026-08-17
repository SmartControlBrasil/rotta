import 'package:flutter/material.dart';
import 'rotta_colors.dart';
import 'rotta_typography.dart';
import 'rotta_spacing.dart';
import 'rotta_radius.dart';

class RottaTheme {
  static ThemeData lightTheme = ThemeData(
    colorScheme: const ColorScheme.light(
      primary: RottaColors.primary,
      secondary: RottaColors.secondary,
      surface: RottaColors.background,
      error: RottaColors.error,
    ),
    scaffoldBackgroundColor: RottaColors.background,
    textTheme: const TextTheme(
      headlineLarge: RottaTypography.headline1,
      headlineMedium: RottaTypography.headline2,
      bodyLarge: RottaTypography.body,
      labelMedium: RottaTypography.caption,
    ),
    visualDensity: VisualDensity.adaptivePlatformDensity,
    useMaterial3: true,
    appBarTheme: const AppBarTheme(
      backgroundColor: RottaColors.primary,
      foregroundColor: RottaColors.onPrimary,
    ),
        cardTheme: const CardThemeData(
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.all(Radius.circular(RottaRadius.md)),
      ),
      margin: EdgeInsets.all(RottaSpacing.md),
    ),
  );
}
