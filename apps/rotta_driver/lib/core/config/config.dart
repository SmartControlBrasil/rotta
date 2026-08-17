
import 'package:flutter/foundation.dart';

class Config {
  static late String baseUrl;

  // Load configuration. Currently uses a compile‑time constant, but can be expanded
  // to read from a local JSON file or environment variables.
  static Future<void> load() async {
    // In Flutter, you can pass --dart-define=API_BASE_URL=... at build time.
    // For development we fall back to the Android emulator host.
    const defaultUrl = 'http://10.0.2.2:8000';
    baseUrl = const String.fromEnvironment('API_BASE_URL', defaultValue: defaultUrl);
    if (kDebugMode) {
      debugPrint('Config loaded: baseUrl=$baseUrl');
    }
  }
}
