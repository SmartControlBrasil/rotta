import uuid
from django.db import models


class IntelligenceAssessmentRecord(models.Model):
    """Immutable historical record of an intelligence assessment snapshot.

    Each record captures the full state of features, risk analysis, and recommendations
    produced for an operation at a specific point in time. Records are never updated;
    new assessments create new records.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization_id = models.UUIDField(db_index=True)
    operation_id = models.UUIDField(db_index=True)

    assessed_at = models.DateTimeField()
    reference_time = models.DateTimeField()

    risk_score = models.FloatField()
    risk_level = models.CharField(max_length=10)

    model_name = models.CharField(max_length=100)
    model_version = models.CharField(max_length=20)
    feature_schema_version = models.CharField(max_length=20)
    recommendation_policy_version = models.CharField(max_length=20)

    context_fingerprint = models.CharField(max_length=64, db_index=True)

    feature_payload = models.JSONField()
    risk_payload = models.JSONField()
    recommendation_payload = models.JSONField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "intelligence"
        db_table = "intelligence_assessment_record"
        ordering = ["-assessed_at"]
        indexes = [
            models.Index(fields=["organization_id", "assessed_at"], name="idx_intel_org_assessed"),
            models.Index(fields=["operation_id", "assessed_at"], name="idx_intel_op_assessed"),
            models.Index(fields=["operation_id", "context_fingerprint"], name="idx_intel_op_fingerprint"),
        ]

    def __str__(self):
        return f"Assessment {self.id} | Op {self.operation_id} | {self.risk_level} ({self.risk_score})"
