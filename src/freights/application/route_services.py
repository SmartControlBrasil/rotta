import datetime
from django.db import transaction, IntegrityError
from django.utils import timezone
from django.core.exceptions import ValidationError

from src.freights.infrastructure.django.models import (
    ContractedRoute,
    ContractedRouteOccurrence,
    ContractedRouteStop,
    FreightOperation,
    FreightOperationStop,
)
from src.freights.domain.enums import (
    ContractedRouteStatus,
    ContractedRouteOccurrenceStatus,
    OperationSource,
    OperationStatus,
    OperationEventType,
    OperationEventOrigin,
)
from src.identity.domain.enums import PermissionCode
from src.audit.infrastructure.django.services import record_audit_event

WEEKDAY_MAP = {
    0: "MON",
    1: "TUE",
    2: "WED",
    3: "THU",
    4: "FRI",
    5: "SAT",
    6: "SUN",
}

def check_user_permission_for_route_or_occurrence(actor, permission_code: str, organization_id) -> bool:
    """Helper to check if an actor has backoffice permission in a specific organization."""
    from src.shared.interfaces.backoffice.authorization import permission_grant_for
    from src.shared.domain.enums import AccessScope

    grant = permission_grant_for(actor, permission_code)
    if not grant.allowed:
        return False
    if grant.scope == AccessScope.ALL:
        return True

    for m in grant.memberships:
        if m.organization_id == organization_id:
            return True
    return False


def create_contracted_route_occurrence(
    *,
    route_id: str,
    occurrence_date: datetime.date,
    driver_id: str | None = None,
    vehicle_id: str | None = None,
    actor,
) -> ContractedRouteOccurrence:
    """Create a planned ContractedRouteOccurrence for a specific date.

    Validates route is ACTIVE, date falls within validity window, weekday is allowed,
    actor has appropriate organization permission, and occurrence doesn't already exist.
    """
    try:
        route = ContractedRoute.objects.get(id=route_id)
    except ContractedRoute.DoesNotExist:
        raise ValidationError({"route": "Rota contratada não encontrada."})

    # Authorization Check
    if not check_user_permission_for_route_or_occurrence(actor, PermissionCode.CONTRACTED_ROUTES_MANAGE.value, route.organization_id):
        raise ValidationError({"actor": "Sem permissão para gerenciar rotas contratadas nesta organização."})

    # 1. Active check
    if route.status != ContractedRouteStatus.ACTIVE.value:
        raise ValidationError({"route": "Apenas rotas ativas podem gerar ocorrências operacionais."})

    # 2. Validity period check
    if occurrence_date < route.valid_from or occurrence_date > route.valid_until:
        raise ValidationError({"occurrence_date": "Data da ocorrência fora do período de vigência da rota."})

    # 3. Weekday compatibility check
    weekday_str = WEEKDAY_MAP[occurrence_date.weekday()]
    allowed_weekdays = route.weekdays.values_list("day", flat=True)
    if weekday_str not in allowed_weekdays:
        raise ValidationError({"occurrence_date": f"Rota não opera em um(a) {weekday_str}."})

    # 4. Uniqueness check & Creation (with concurrency fallback)
    try:
        return ContractedRouteOccurrence.objects.get(
            contracted_route=route,
            occurrence_date=occurrence_date,
        )
    except ContractedRouteOccurrence.DoesNotExist:
        pass

    # Override or default preferred driver/vehicle
    effective_driver = driver_id or (route.preferred_driver_id if route.preferred_driver else None)
    effective_vehicle = vehicle_id or (route.preferred_vehicle_id if route.preferred_vehicle else None)

    occurrence = ContractedRouteOccurrence(
        organization=route.organization,
        contracted_route=route,
        occurrence_date=occurrence_date,
        driver_id=effective_driver,
        vehicle_id=effective_vehicle,
        status=ContractedRouteOccurrenceStatus.PLANNED.value,
    )
    try:
        # Trigger model clean to enforce preferred driver/vehicle organizational checks,
        # excluding uniqueness checks to let them be enforced at the database level.
        occurrence.full_clean(exclude=["contracted_route", "occurrence_date"])
        with transaction.atomic():
            occurrence.save()
            return occurrence
    except ValidationError as e:
        # Inspect if this is a uniqueness/duplicate validation error on contracted_route/occurrence_date
        is_unique_error = False
        if hasattr(e, "message_dict"):
            for field, messages in e.message_dict.items():
                for msg in messages:
                    msg_lower = msg.lower()
                    if "já existe" in msg_lower or "already exists" in msg_lower or "unique" in msg_lower:
                        is_unique_error = True

        if is_unique_error:
            try:
                return ContractedRouteOccurrence.objects.get(
                    contracted_route=route,
                    occurrence_date=occurrence_date,
                )
            except ContractedRouteOccurrence.DoesNotExist:
                raise e
        else:
            raise e
    except IntegrityError as e:
        # Check if occurrence was concurrently created by another process
        try:
            return ContractedRouteOccurrence.objects.get(
                contracted_route=route,
                occurrence_date=occurrence_date,
            )
        except ContractedRouteOccurrence.DoesNotExist:
            raise e


def materialize_contracted_route_occurrence(
    *,
    occurrence_id: str,
    actor,
) -> FreightOperation:
    """Materialize a ContractedRouteOccurrence into an active FreightOperation.

    This copies stop templates to operational stops (FreightOperationStop).
    This operation is idempotent and thread-safe.
    """
    from src.freights.application.operation_services import _create_event

    with transaction.atomic():
        try:
            occurrence = (
                ContractedRouteOccurrence.objects.select_for_update()
                .select_related("contracted_route__carrier")
                .get(id=occurrence_id)
            )
        except ContractedRouteOccurrence.DoesNotExist:
            raise ValidationError({"occurrence": "Ocorrência não encontrada."})

        # Authorization Check
        if not check_user_permission_for_route_or_occurrence(actor, PermissionCode.FREIGHT_OPERATIONS_CREATE.value, occurrence.organization_id):
            raise ValidationError({"actor": "Sem permissão para materializar operações de frete nesta organização."})

        # Idempotency check: if already materialized, return the linked operation
        if occurrence.status == ContractedRouteOccurrenceStatus.MATERIALIZED.value and occurrence.operation:
            return occurrence.operation

        if occurrence.status != ContractedRouteOccurrenceStatus.PLANNED.value:
            raise ValidationError({"occurrence": "Apenas ocorrências planejadas (PLANNED) podem ser materializadas."})

        # Resolve effective driver / vehicle
        route = occurrence.contracted_route
        effective_driver = occurrence.driver or route.preferred_driver
        effective_vehicle = occurrence.vehicle or route.preferred_vehicle

        # Create the FreightOperation
        operation = FreightOperation.objects.create(
            organization=occurrence.organization,
            source_type=OperationSource.CONTRACTED_ROUTE,
            selection=None,
            carrier=route.carrier,
            driver=effective_driver,
            vehicle=effective_vehicle,
            status=OperationStatus.ASSIGNED.value,
            assigned_at=timezone.now(),
            load_type=route.load_type,
            temperature_min_c=route.temperature_min_c,
            temperature_max_c=route.temperature_max_c,
        )

        # Copy stops
        for stop in route.stops.all().order_by("sequence"):
            FreightOperationStop.objects.create(
                organization=operation.organization,
                operation=operation,
                sequence=stop.sequence,
                stop_type=stop.stop_type,
                status="PENDING",
                postal_code=stop.postal_code,
                street=stop.street,
                number=stop.number,
                complement=stop.complement,
                district=stop.district,
                city=stop.city,
                state=stop.state,
                country=stop.country,
                latitude=stop.latitude,
                longitude=stop.longitude,
                instructions=stop.instructions,
                scheduled_date=occurrence.occurrence_date,
                window_start=stop.window_start,
                window_end=stop.window_end,
            )

        # Link occurrence to operation and advance status
        occurrence.status = ContractedRouteOccurrenceStatus.MATERIALIZED.value
        occurrence.operation = operation
        occurrence.save()

        # Record operational created event
        _create_event(
            operation=operation,
            event_type=OperationEventType.OPERATION_CREATED,
            actor=actor,
            origin=OperationEventOrigin.SYSTEM,
        )

        # Audit logging
        record_audit_event(
            action="contracted_route_occurrence_materialized",
            actor=actor,
            organization=operation.organization,
            target=occurrence,
            after={"operation_id": str(operation.id)},
        )

        from src.intelligence.application.collection_services import CollectOperationIntelligenceService
        transaction.on_commit(lambda: CollectOperationIntelligenceService.trigger_for_operation(
            operation_id=str(operation.id),
            event_type="OPERATION_CREATED",
            actor=actor
        ))

    return operation


class GenerateDueContractedRouteOperationsService:
    """Service to automatically generate occurrences and materialize operations
    from ContractedRoute configuration.
    """
    def __init__(self, actor=None):
        self.actor = actor

    def execute(
        self,
        target_date: datetime.date | None = None,
        dry_run: bool = False,
        limit: int | None = None
    ) -> dict:
        """Runs the generation process:
        1. Identification of active routes that should operate on target_date.
        2. Creation of planned occurrences (ContractedRouteOccurrence) if they don't exist yet.
        3. Materialization of due planned occurrences into active FreightOperations.
        """
        from django.db import transaction, models
        from django.db.models import Q, F
        from django.contrib.auth import get_user_model

        # Resolve target_date
        if target_date is None:
            target_date = timezone.localdate()

        # Resolve system user actor if not provided
        system_user = self.actor
        if system_user is None:
            User = get_user_model()
            system_user, created = User.objects.get_or_create(
                username="system",
                defaults={
                    "is_superuser": True,
                    "is_staff": True,
                    "email": "system@rotta116.com.br",
                }
            )
            if created:
                system_user.set_unusable_password()
                system_user.save()

        # Find active routes that cover target_date and operating on its weekday
        # 1. Weekday map
        weekday_str = WEEKDAY_MAP[target_date.weekday()]

        # 2. Query routes
        routes = ContractedRoute.objects.filter(
            status=ContractedRouteStatus.ACTIVE.value,
            valid_from__lte=target_date,
            valid_until__gte=target_date,
            weekdays__day=weekday_str
        ).distinct()

        results = {
            "routes_evaluated": routes.count(),
            "occurrences_created": 0,
            "occurrences_failed_creation": 0,
            "occurrences_processed": 0,
            "operations_created": 0,
            "already_existing": 0,
            "operations_failed": 0,
            "details": []
        }

        # Step 1: Create occurrences for active routes on target_date (if dry_run is False)
        planned_occ_ids = []

        for route in routes:
            # Check limit
            if limit is not None and len(planned_occ_ids) >= limit:
                break

            occ_exists = ContractedRouteOccurrence.objects.filter(
                contracted_route=route,
                occurrence_date=target_date
            ).exists()

            if not occ_exists:
                if dry_run:
                    results["occurrences_created"] += 1
                    results["details"].append(f"[Dry Run] Planned occurrence would be created for route '{route.name}' on {target_date}")
                else:
                    try:
                        occ = create_contracted_route_occurrence(
                            route_id=str(route.id),
                            occurrence_date=target_date,
                            actor=system_user
                        )
                        results["occurrences_created"] += 1
                        planned_occ_ids.append(occ.id)
                    except Exception as e:
                        results["occurrences_failed_creation"] += 1
                        results["details"].append(f"Failed to create occurrence for route '{route.name}': {str(e)}")
            else:
                occ = ContractedRouteOccurrence.objects.get(
                    contracted_route=route,
                    occurrence_date=target_date
                )
                planned_occ_ids.append(occ.id)

        # Step 2: Query planned occurrences due for materialization
        # An occurrence is due if it is planned, occurrence_date <= target_date, and route is active.
        due_occurrences = ContractedRouteOccurrence.objects.filter(
            status=ContractedRouteOccurrenceStatus.PLANNED.value,
            operation__isnull=True,
            occurrence_date__lte=target_date,
            contracted_route__status=ContractedRouteStatus.ACTIVE.value,
            occurrence_date__gte=F("contracted_route__valid_from"),
        ).filter(
            occurrence_date__lte=F("contracted_route__valid_until"),
        ).select_related("contracted_route").order_by("occurrence_date", "created_at")

        # Materialization processing
        for occ in due_occurrences:
            # Check limit
            if limit is not None and results["operations_created"] >= limit:
                break

            results["occurrences_processed"] += 1

            if dry_run:
                results["operations_created"] += 1
                results["details"].append(f"[Dry Run] Operation would be materialized for occurrence {occ.id} ({occ.occurrence_date})")
            else:
                try:
                    with transaction.atomic():
                        # Refetch with select_for_update to handle concurrent runners
                        locked_occ = ContractedRouteOccurrence.objects.select_for_update().get(id=occ.id)

                        # Idempotency check: if already materialized in another thread/runner
                        if locked_occ.status == ContractedRouteOccurrenceStatus.MATERIALIZED.value and locked_occ.operation_id:
                            results["already_existing"] += 1
                            results["details"].append(f"Occurrence {occ.id} already materialized concurrently.")
                            continue

                        # Materialize
                        op = materialize_contracted_route_occurrence(
                            occurrence_id=str(locked_occ.id),
                            actor=system_user
                        )
                        results["operations_created"] += 1
                        results["details"].append(f"Materialized operation {op.id} for occurrence {locked_occ.id}")
                except Exception as e:
                    results["operations_failed"] += 1
                    results["details"].append(f"Failed to materialize occurrence {occ.id}: {str(e)}")

        return results
