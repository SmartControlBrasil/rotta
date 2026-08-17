import 'package:flutter/material.dart';
import 'package:rotta_driver/core/config/config.dart';
import 'package:rotta_driver/app/app.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Config.load();
  runApp(const MyApp());
}
