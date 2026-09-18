import sys
from datetime import datetime, timezone
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

from src.organizations.infrastructure.django.models import Organization
from src.intelligence.infrastructure.django.repositories import DjangoIntelligenceSnapshotRepository
from src.intelligence.infrastructure.django.query_services import DjangoOperationResultContextQueryService
from src.intelligence.application.dataset_services import BuildOperationalRiskDatasetService
from src.intelligence.application.evaluation_services import EvaluateRuleBasedBaselineService


class Command(BaseCommand):
    help = "Generate a dataset quality and baseline evaluation report for a given organization."

    def add_arguments(self, parser):
        parser.add_argument("--organization", type=str, required=True, help="UUID of the Organization")
        parser.add_argument("--start-date", type=str, required=False, help="Start date (YYYY-MM-DD)")
        parser.add_argument("--end-date", type=str, required=False, help="End date (YYYY-MM-DD)")

    def handle(self, *args, **options):
        org_id = options["organization"]
        start_str = options.get("start_date")
        end_str = options.get("end_date")

        start_date = datetime.strptime(start_str, "%Y-%m-%d").replace(tzinfo=timezone.utc) if start_str else datetime.min.replace(tzinfo=timezone.utc)
        end_date = datetime.strptime(end_str, "%Y-%m-%d").replace(tzinfo=timezone.utc) if end_str else datetime.max.replace(tzinfo=timezone.utc)

        # Get system superuser or admin for query execution
        User = get_user_model()
        actor = User.objects.filter(is_superuser=True).first()
        if not actor:
            self.stdout.write(self.style.ERROR("No superuser found to run the command."))
            sys.exit(1)

        try:
            Organization.objects.get(id=org_id)
        except Organization.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Organization with ID {org_id} does not exist."))
            sys.exit(1)

        repo = DjangoIntelligenceSnapshotRepository()
        port = DjangoOperationResultContextQueryService()
        builder = BuildOperationalRiskDatasetService(repo, port)
        evaluator = EvaluateRuleBasedBaselineService()

        # 1. Fetch records
        try:
            records = builder.build_dataset(org_id, actor, start_date, end_date)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to generate dataset records: {str(e)}"))
            sys.exit(1)

        # 2. Quality analysis
        quality = builder.generate_quality_report(records)

        # 3. Evaluator analysis
        evaluation = evaluator.evaluate(records)

        # 4. Print results
        self.stdout.write("=================================================================")
        self.stdout.write(self.style.SUCCESS(f"AI Core Dataset Report | Org: {org_id}"))
        self.stdout.write(f"Period: {start_str or 'All'} to {end_str or 'All'}")
        self.stdout.write("=================================================================")
        self.stdout.write(f"Total Snapshots:          {quality.total_records}")
        self.stdout.write(f"Complete Records (y):     {quality.complete_records}")
        self.stdout.write(f"Partial Records:          {quality.partial_records}")
        self.stdout.write(f"Ineligible Records:       {quality.ineligible_records}")
        self.stdout.write(f"Missing Tracking Rate:    {quality.missing_tracking_rate * 100:.2f}%")
        self.stdout.write("-----------------------------------------------------------------")
        self.stdout.write("Label Distributions (Ground Truth):")
        self.stdout.write(f"  SLA Breached labels:    {quality.records_with_sla_label}")
        self.stdout.write(f"  Thermal Excursion:      {quality.records_with_thermal_label}")
        self.stdout.write(f"  Critical Incident:      {quality.records_with_incident_label}")
        self.stdout.write("-----------------------------------------------------------------")
        self.stdout.write("Baseline Rule Engine Evaluation (Confusion Matrix):")

        self.stdout.write("  SLA Breach Prediction:")
        self.stdout.write(f"    TP: {evaluation.sla_evaluation.tp} | FP: {evaluation.sla_evaluation.fp}")
        self.stdout.write(f"    TN: {evaluation.sla_evaluation.tn} | FN: {evaluation.sla_evaluation.fn}")
        p_sla = f"{evaluation.sla_evaluation.precision * 100:.2f}%" if evaluation.sla_evaluation.precision is not None else "N/A"
        r_sla = f"{evaluation.sla_evaluation.recall * 100:.2f}%" if evaluation.sla_evaluation.recall is not None else "N/A"
        self.stdout.write(f"    Precision: {p_sla} | Recall: {r_sla}")

        self.stdout.write("  Thermal Anomaly Prediction:")
        self.stdout.write(f"    TP: {evaluation.thermal_evaluation.tp} | FP: {evaluation.thermal_evaluation.fp}")
        self.stdout.write(f"    TN: {evaluation.thermal_evaluation.tn} | FN: {evaluation.thermal_evaluation.fn}")
        p_therm = f"{evaluation.thermal_evaluation.precision * 100:.2f}%" if evaluation.thermal_evaluation.precision is not None else "N/A"
        r_therm = f"{evaluation.thermal_evaluation.recall * 100:.2f}%" if evaluation.thermal_evaluation.recall is not None else "N/A"
        self.stdout.write(f"    Precision: {p_therm} | Recall: {r_therm}")

        self.stdout.write("-----------------------------------------------------------------")
        self.stdout.write(f"Global False Positive Rate: {evaluation.false_positive_rate * 100:.2f}%")
        self.stdout.write(f"Global False Negative Rate: {evaluation.false_negative_rate * 100:.2f}%")
        self.stdout.write("=================================================================")
