from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, List
from src.intelligence.domain.models import OperationContext, RiskAssessment, Recommendation, IntelligenceSnapshot, OperationResultContext
from src.intelligence.domain.features import OperationFeatures

class OperationContextPort(ABC):
    @abstractmethod
    def get_context(self, operation_id: str, actor) -> OperationContext:
        """Load context for a specific operation, enforcing tenant isolation and access controls.

        Args:
            operation_id: The ID of the FreightOperation.
            actor: The user requesting the data.

        Returns:
            An OperationContext populated with all execution and snapshot details.

        Raises:
            ValidationError/PermissionError: If tenant isolation checks or access checks fail.
        """
        pass

class RiskModelPort(ABC):
    @abstractmethod
    def predict(self, features: OperationFeatures) -> RiskAssessment:
        """Execute risk score inference.

        Args:
            features: OperationFeatures data vector.

        Returns:
            A RiskAssessment structured prediction.
        """
        pass

class IntelligenceSnapshotRepositoryPort(ABC):
    @abstractmethod
    def save(self, snapshot: IntelligenceSnapshot) -> IntelligenceSnapshot:
        """Persist an immutable intelligence assessment snapshot."""
        pass

    @abstractmethod
    def find_by_fingerprint(self, operation_id: str, context_fingerprint: str) -> Optional[IntelligenceSnapshot]:
        """Find an existing snapshot by operation and context fingerprint (idempotency check)."""
        pass

    @abstractmethod
    def latest_for_operation(self, operation_id: str, organization_id: str) -> Optional[IntelligenceSnapshot]:
        """Return the most recent assessment for a given operation."""
        pass

    @abstractmethod
    def history_for_operation(self, operation_id: str, organization_id: str) -> List[IntelligenceSnapshot]:
        """Return all assessments for a given operation, ordered by assessed_at descending."""
        pass

    @abstractmethod
    def find_by_date_range(
        self,
        organization_id: str,
        start_date: datetime,
        end_date: datetime,
        actor,
    ) -> List[IntelligenceSnapshot]:
        """Find snapshots within a date range for a specific organization, validating access."""
        pass


class OperationResultContextPort(ABC):
    @abstractmethod
    def get_result_context(self, operation_id: str, actor) -> OperationResultContext:
        """Load final outcome/result context for an operation, enforcing tenant isolation."""
        pass
