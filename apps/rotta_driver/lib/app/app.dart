import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:rotta_driver/features/authentication/presentation/login_screen.dart';
import 'package:rotta_driver/features/operations/presentation/operations_list_screen.dart';
import 'package:rotta_driver/app/splash_screen.dart';
import 'package:rotta_driver/design_system/rotta_theme.dart';
import 'package:rotta_driver/features/operations/presentation/providers/tracking_provider.dart';

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => TrackingProvider()),
      ],
      child: MaterialApp(
        title: 'Rotta Driver',
        theme: RottaTheme.lightTheme,
        initialRoute: '/',
        routes: {
          '/': (context) => const SplashScreen(),
          '/login': (context) => const LoginScreen(),
          '/operations': (context) => const OperationsListScreen(),
        },
      ),
    );
  }
}
