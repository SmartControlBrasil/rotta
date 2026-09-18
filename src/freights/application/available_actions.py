from typing import List, Optional
from src.freights.infrastructure.django.models import FreightOperation, FreightOperationStop, ProofOfDelivery
from src.freights.domain.enums import OperationStatus, FreightStopType

class CalculateDriverAvailableActionsService:
    """Pure application policy service to compute available actions for the driver on an operation."""

    @staticmethod
    def get_available_actions(operation: FreightOperation) -> List[str]:
        actions = []
        status = operation.status

        # Terminal statuses cannot have any action
        if status in [OperationStatus.DELIVERED.value, OperationStatus.CANCELLED.value]:
            return actions

        # Basic tracking and incident reporting are always available for active operations
        actions.append("REPORT_INCIDENT")

        has_active_session = operation.tracking_sessions.filter(status="ACTIVE").exists()
        if not has_active_session:
            actions.append("START_TRACKING")
        else:
            actions.append("END_TRACKING")

        # 1. Macro operation status actions
        if status == OperationStatus.ASSIGNED.value:
            actions.append("START_OPERATION")
        elif status == OperationStatus.DRIVER_EN_ROUTE_TO_PICKUP.value:
            actions.append("ARRIVE_PICKUP")
        elif status == OperationStatus.ARRIVED_AT_PICKUP.value:
            actions.append("START_LOADING")
        elif status == OperationStatus.LOADING.value:
            actions.append("START_TRANSIT")
        elif status == OperationStatus.IN_TRANSIT.value:
            actions.append("ARRIVE_DELIVERY")
        elif status == OperationStatus.ARRIVED_AT_DELIVERY.value:
            actions.append("START_UNLOADING")
        elif status == OperationStatus.UNLOADING.value:
            # COMPLETE_OPERATION is only allowed if all delivery stops are completed/cancelled and have PODs
            pending_deliveries = operation.stops.filter(
                stop_type=FreightStopType.DELIVERY.value
            ).exclude(status__in=["COMPLETED", "CANCELLED"])

            all_pods_exist = True
            completed_deliveries = operation.stops.filter(
                stop_type=FreightStopType.DELIVERY.value,
                status="COMPLETED"
            )
            for stop in completed_deliveries:
                if not ProofOfDelivery.objects.filter(stop=stop).exists():
                    all_pods_exist = False
                    break

            if not pending_deliveries.exists() and all_pods_exist:
                actions.append("COMPLETE_OPERATION")

        # 2. Stop-level actions (only available after operation is started, i.e., not ASSIGNED)
        if status != OperationStatus.ASSIGNED.value:
            next_stop = CalculateDriverAvailableActionsService.get_next_stop(operation)
            if next_stop:
                if next_stop.status == "PENDING":
                    # Can arrive at next stop if:
                    # 1. All previous stops by sequence are completed/cancelled
                    # 2. If it is a DELIVERY stop, all its cargo lots have their pickup stops completed
                    previous_ok = True
                    prev_stops = operation.stops.filter(sequence__lt=next_stop.sequence)
                    for prev in prev_stops:
                        if prev.status not in ["COMPLETED", "CANCELLED"]:
                            previous_ok = False
                            break

                    cargo_ok = True
                    if next_stop.stop_type == FreightStopType.DELIVERY.value:
                        lots = operation.cargo_lots.filter(delivery_stop=next_stop)
                        for lot in lots:
                            if lot.pickup_stop.status != "COMPLETED":
                                cargo_ok = False
                                break

                    if previous_ok and cargo_ok:
                        actions.append("ARRIVE_STOP")

                elif next_stop.status == "ARRIVED":
                    # If PICKUP, can complete stop directly
                    if next_stop.stop_type == FreightStopType.PICKUP.value:
                        actions.append("COMPLETE_STOP")
                    elif next_stop.stop_type == FreightStopType.DELIVERY.value:
                        # If DELIVERY, requires a POD first
                        has_pod = ProofOfDelivery.objects.filter(stop=next_stop).exists()
                        if not has_pod:
                            actions.append("SUBMIT_POD")
                        else:
                            actions.append("COMPLETE_STOP")

        return actions

    @staticmethod
    def get_next_stop(operation: FreightOperation) -> Optional[FreightOperationStop]:
        """Return the next operational stop to be handled by the driver (first non-completed by sequence)."""
        return operation.stops.exclude(
            status__in=["COMPLETED", "CANCELLED"]
        ).order_by("sequence").first()
