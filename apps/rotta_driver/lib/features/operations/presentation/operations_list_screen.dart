// Operations List Screen
import 'package:flutter/material.dart';
import 'package:rotta_driver/design_system/rotta_spacing.dart';
import 'package:rotta_driver/design_system/widgets/rotta_card.dart';
import 'package:rotta_driver/design_system/widgets/rotta_status_badge.dart';
import 'package:rotta_driver/core/api/api_client.dart';
import 'package:rotta_driver/features/operations/data/models.dart';
import 'package:rotta_driver/design_system/widgets/rotta_info_row.dart';
import 'package:rotta_driver/design_system/widgets/rotta_loading.dart';
import 'package:rotta_driver/design_system/widgets/rotta_error_state.dart';
import 'package:rotta_driver/design_system/widgets/rotta_empty_state.dart';
import 'package:rotta_driver/features/operations/data/operations_repository.dart';
import 'operation_detail_screen.dart';

class OperationsListScreen extends StatefulWidget {
  const OperationsListScreen({Key? key}) : super(key: key);
  @override
  State<OperationsListScreen> createState() => _OperationsListScreenState();
}

class _OperationsListScreenState extends State<OperationsListScreen> {
  final repo = OperationsRepository(client: ApiClient());
  late Future<List<OperationSummary>> _future;

  @override
  void initState() {
    super.initState();
    _future = repo.listOperations();
  }

  Future<void> _refresh() async {
    setState(() => _future = repo.listOperations());
    await _future;
  }

  Widget _buildCard(OperationSummary op) {
    return RottaCard(
      onTap: () => Navigator.push(
        context,
        MaterialPageRoute(builder: (_) => OperationDetailScreen(id: op.id)),
      ).then((_) => _refresh()),
      child: Padding(
        padding: const EdgeInsets.all(RottaSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            RottaInfoRow(label: 'Referência', value: op.referenceCode ?? '-'),
            const SizedBox(height: RottaSpacing.sm),
            Row(
              children: [
                RottaStatusBadge(status: op.status),
                if (op.loadType != null) ...[
                  const SizedBox(width: RottaSpacing.sm),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: RottaSpacing.sm, vertical: RottaSpacing.xs),
                    decoration: BoxDecoration(
                      color: Colors.grey.shade200,
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Text(
                      op.loadType!,
                      style: const TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: Colors.black54),
                    ),
                  ),
                ],
                if (op.serviceLevelState != null) ...[
                  const SizedBox(width: RottaSpacing.sm),
                  RottaStatusBadge(status: op.serviceLevelState!),
                ],
              ],
            ),
            const SizedBox(height: RottaSpacing.sm),
            Row(
              children: [
                Expanded(child: RottaInfoRow(label: 'Origem', value: op.origin ?? '-')),
                const Icon(Icons.arrow_downward, size: 16, color: Color(0xFF777777)),
                Expanded(child: RottaInfoRow(label: 'Destino', value: op.destination ?? '-')),
              ],
            ),
            if (op.assignedAt != null) ...[
              const SizedBox(height: RottaSpacing.sm),
              RottaInfoRow(label: 'Data atribuída', value: op.assignedAt!),
            ],
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Minhas operações')),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: FutureBuilder<List<OperationSummary>>(
          future: _future,
          builder: (context, snapshot) {
            if (snapshot.connectionState == ConnectionState.waiting) {
              return const Center(child: RottaLoading());
            }
            if (snapshot.hasError) {
              return RottaErrorState(message: 'Erro ao carregar operações', onRetry: _refresh);
            }
            final ops = snapshot.data ?? [];
            if (ops.isEmpty) {
              return const RottaEmptyState(message: 'Nenhuma operação encontrada');
            }
            return ListView.builder(
              padding: const EdgeInsets.all(RottaSpacing.md),
              itemCount: ops.length,
              itemBuilder: (_, i) => _buildCard(ops[i]),
            );
          },
        ),
      ),
    );
  }
}
