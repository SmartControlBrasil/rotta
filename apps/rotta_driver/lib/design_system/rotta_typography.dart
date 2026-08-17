import 'package:flutter/material.dart';
import 'rotta_colors.dart';

class RottaTypography {
  static const TextStyle headline1 = TextStyle(
    fontSize: 32,
    fontWeight: FontWeight.bold,
    color: RottaColors.onBackground,
    letterSpacing: -0.5,
  );

  static const TextStyle headline2 = TextStyle(
    fontSize: 24,
    fontWeight: FontWeight.w600,
    color: RottaColors.onBackground,
  );

  static const TextStyle headline3 = TextStyle(
    fontSize: 20,
    fontWeight: FontWeight.w600,
    color: RottaColors.onBackground,
  );

  static const TextStyle body = TextStyle(
    fontSize: 16,
    color: RottaColors.onBackground,
    height: 1.5,
  );

  static const TextStyle bodyRegular = TextStyle(
    fontSize: 16,
    fontWeight: FontWeight.w400,
    color: RottaColors.onBackground,
  );

  static const TextStyle bodyMedium = TextStyle(
    fontSize: 16,
    fontWeight: FontWeight.w500,
    color: RottaColors.onBackground,
  );

  static const TextStyle bodySmall = TextStyle(
    fontSize: 14,
    color: RottaColors.onBackground,
  );

  static const TextStyle caption = TextStyle(
    fontSize: 12,
    color: RottaColors.onBackgroundVariant,
  );

  static const TextStyle label = TextStyle(
    fontSize: 12,
    fontWeight: FontWeight.w600,
    color: RottaColors.onBackground,
    letterSpacing: 0.5,
  );

  // New subtitleBold style used by service level and other cards
  static const TextStyle subtitleBold = TextStyle(
    fontSize: 16,
    fontWeight: FontWeight.bold,
    color: RottaColors.onBackground,
  );
}
