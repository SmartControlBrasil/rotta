import datetime
from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_date
from src.freights.application.route_services import GenerateDueContractedRouteOperationsService


class Command(BaseCommand):
    help = "Process contracted routes to generate occurrences and materialize operations."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            help="Target date for the run in YYYY-MM-DD format (defaults to today)."
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simulate the generation without saving changes to the database."
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Limit the number of occurrences to create/materialize."
        )

    def handle(self, *args, **options):
        # Parse date
        target_date = None
        if options["date"]:
            target_date = parse_date(options["date"])
            if not target_date:
                self.stderr.write(self.style.ERROR(f"Format de data inválido: {options['date']}. Use YYYY-MM-DD."))
                return

        dry_run = options["dry_run"]
        limit = options["limit"]

        self.stdout.write(self.style.NOTICE(f"Iniciando runner do scheduler de rotas contratadas (dry_run={dry_run}, target_date={target_date or 'hoje'})..."))

        service = GenerateDueContractedRouteOperationsService()
        try:
            results = service.execute(target_date=target_date, dry_run=dry_run, limit=limit)

            # Imprimir Resumo
            self.stdout.write(self.style.SUCCESS("Runner do scheduler executado com sucesso!"))
            self.stdout.write(f"Rotas ativas avaliadas: {results['routes_evaluated']}")
            self.stdout.write(f"Ocorrências planejadas criadas: {results['occurrences_created']}")
            self.stdout.write(f"Falhas na criação de ocorrências: {results['occurrences_failed_creation']}")
            self.stdout.write(f"Ocorrências processadas para materialização: {results['occurrences_processed']}")
            self.stdout.write(f"Operações de frete materializadas: {results['operations_created']}")
            self.stdout.write(f"Já materializadas anteriormente (ignoradas): {results['already_existing']}")
            self.stdout.write(f"Falhas na materialização: {results['operations_failed']}")

            if results["details"]:
                self.stdout.write(self.style.NOTICE("\nDetalhes do processamento:"))
                for detail in results["details"]:
                    self.stdout.write(f"- {detail}")
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Erro crítico no processamento de rotas: {str(e)}"))
            raise e
