import 'package:flutter/material.dart';
import 'package:rotta_driver/core/auth/auth_service.dart';
import 'package:rotta_driver/core/config/config.dart';

class SplashScreen extends StatefulWidget {
  const SplashScreen({Key? key}) : super(key: key);

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> {
  @override
  void initState() {
    super.initState();
    _init();
  }

  Future<void> _init() async {
    await Config.load();
    final loggedIn = await AuthService.instance.isAuthenticated();
    // small delay for UX
    await Future.delayed(const Duration(milliseconds: 500));
    if (loggedIn) {
      Navigator.of(context).pushReplacementNamed('/operations');
    } else {
      Navigator.of(context).pushReplacementNamed('/login');
    }
  }

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      body: Center(
        child: CircularProgressIndicator(),
      ),
    );
  }
}
