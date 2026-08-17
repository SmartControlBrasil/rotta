// Smoke test for the Rotta Driver app
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/material.dart';
import 'package:rotta_driver/app/app.dart';
import 'package:rotta_driver/core/config/config.dart';

void main() {
  testWidgets('App initializes and shows splash screen', (WidgetTester tester) async {
    // Ensure configuration is loaded.
    await Config.load();
    // Build the app.
    await tester.pumpWidget(const MyApp());
    // Advance a short duration to allow splash init.
    await tester.pump(const Duration(milliseconds: 500));
    // Verify that the splash screen displays a CircularProgressIndicator.
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
  });
}
