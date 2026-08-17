import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:rotta_driver/core/config/config.dart';
import 'package:rotta_driver/core/auth/auth_service.dart';

class ApiClient {
  final http.Client _client;

  ApiClient({http.Client? client}) : _client = client ?? http.Client();

  Future<http.Response> _sendAuthorized(http.Request request) async {
    final token = await AuthService.instance.getAccessToken();
    if (token != null) {
      request.headers['Authorization'] = 'Bearer $token';
    }
    final streamed = await _client.send(request);
    final response = await http.Response.fromStream(streamed);
    if (response.statusCode == 401) {
      // Attempt token refresh and retry once
      try {
        await AuthService.instance.refresh();
        final newToken = await AuthService.instance.getAccessToken();
        if (newToken != null) {
          request.headers['Authorization'] = 'Bearer $newToken';
          final retried = await _client.send(request);
          return await http.Response.fromStream(retried);
        } else {
          // Refresh failed or did not return a token – clear session
          await AuthService.instance.logout();
        }
      } catch (e) {
        // On any exception during refresh, clear session
        await AuthService.instance.logout();
      }
    }
    return response;
  }

  Future<http.Response> get(String path, {Map<String, String>? queryParameters}) async {
    final uri = Uri.parse('${Config.baseUrl}$path').replace(queryParameters: queryParameters);
    final request = http.Request('GET', uri);
    return _sendAuthorized(request);
  }

  Future<http.Response> post(String path, {dynamic body}) async {
    final uri = Uri.parse('${Config.baseUrl}$path');
    final request = http.Request('POST', uri);
    request.headers['Content-Type'] = 'application/json';
    if (body != null) {
      request.body = jsonEncode(body);
    }
    return _sendAuthorized(request);
  }
}
