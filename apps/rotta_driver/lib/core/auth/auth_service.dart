import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:rotta_driver/core/config/config.dart';

class AuthService {
  AuthService._privateConstructor();
  static final AuthService instance = AuthService._privateConstructor();

  final _storage = const FlutterSecureStorage();
  static const _accessTokenKey = 'access_token';
  static const _refreshTokenKey = 'refresh_token';
  static const _expiresAtKey = 'expires_at'; // epoch seconds

  Future<String?> getAccessToken() async => await _storage.read(key: _accessTokenKey);

  Future<bool> isAuthenticated() async {
    final token = await _storage.read(key: _accessTokenKey);
    final expiresStr = await _storage.read(key: _expiresAtKey);
    if (token == null || expiresStr == null) return false;
    final expiresAt = int.tryParse(expiresStr) ?? 0;
    return DateTime.now().millisecondsSinceEpoch ~/ 1000 < expiresAt;
  }

  Future<void> login(String username, String password) async {
    final url = Uri.parse('${Config.baseUrl}/api/v1/auth/token/');
    final response = await http.post(
      url,
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'username': username,
        'password': password,
      }),
    );
    if (response.statusCode != 200) {
      throw Exception('Login failed');
    }
    final data = jsonDecode(response.body);
    await _storage.write(key: _accessTokenKey, value: data['access_token']);
    await _storage.write(key: _refreshTokenKey, value: data['refresh_token']);
    final expiresIn = data['expires_in'] as int;
    final expiresAt = (DateTime.now().millisecondsSinceEpoch ~/ 1000) + expiresIn;
    await _storage.write(key: _expiresAtKey, value: expiresAt.toString());
  }

  Future<void> logout() async {
    final token = await _storage.read(key: _accessTokenKey);
    if (token != null) {
      final url = Uri.parse('${Config.baseUrl}/api/v1/auth/token/revoke/');
      await http.post(url, headers: {'Authorization': 'Bearer $token'});
    }
    await _storage.deleteAll();
  }

  // Simple refresh implementation
  Future<void> refresh() async {
    final refreshToken = await _storage.read(key: _refreshTokenKey);
    if (refreshToken == null) throw Exception('No refresh token');
    final url = Uri.parse('${Config.baseUrl}/api/v1/auth/token/refresh/');
    final response = await http.post(
      url,
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'refresh_token': refreshToken}),
    );
    if (response.statusCode != 200) throw Exception('Refresh failed');
    final data = jsonDecode(response.body);
    await _storage.write(key: _accessTokenKey, value: data['access_token']);
    final expiresIn = data['expires_in'] as int;
    final expiresAt = (DateTime.now().millisecondsSinceEpoch ~/ 1000) + expiresIn;
    await _storage.write(key: _expiresAtKey, value: expiresAt.toString());
  }
}
