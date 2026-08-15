from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from src.carriers.domain.enums import CarrierCargoProfile, CarrierStatus
from src.carriers.infrastructure.django.models import CarrierProfile
from src.compliance.application.evaluation import evaluate_entity_compliance
from src.compliance.domain.enums import ComplianceStatus, EntityType
from src.drivers.domain.enums import DriverAvailabilityStatus, DriverStatus
from src.drivers.infrastructure.django.models import Driver
from src.freights.domain.enums import FreightCargoProfile
from src.freights.domain.matching_enums import (
    MatchEligibilityReasonCode,
    MatchEligibilityStatus,
)
from src.freights.domain.offer_enums import FreightOfferAudience
from src.freights.infrastructure.django.models import FreightOffer
from src.vehicles.domain.enums import VehicleCargoProfile, VehicleOperationalStatus, VehicleStatus
from src.vehicles.infrastructure.django.models import RefrigerationProfile, Vehicle


@dataclass(frozen=True)
class EligibilityReason:
    code: MatchEligibilityReasonCode
    blocking: bool
    message: str = ""


@dataclass
class EligibilityResult:
    status: MatchEligibilityStatus
    reasons: list[EligibilityReason] = field(default_factory=list)

    def add(self, *, code: MatchEligibilityReasonCode, blocking: bool, message: str = "") -> None:
        self.reasons.append(EligibilityReason(code=code, blocking=blocking, message=message))
        if blocking and self.status != MatchEligibilityStatus.INELIGIBLE:
            self.status = MatchEligibilityStatus.INELIGIBLE

    def to_json(self) -> list[dict]:
        return [
            {"code": reason.code.value, "blocking": reason.blocking, "message": reason.message}
            for reason in self.reasons
        ]


def _snapshot_decimal(value: str | None) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def validate_candidate_shape(
    *,
    carrier: CarrierProfile | None,
    driver: Driver | None,
    vehicle: Vehicle | None,
) -> EligibilityResult:
    result = EligibilityResult(status=MatchEligibilityStatus.UNKNOWN)
    if carrier and not driver and not vehicle:
        result.status = MatchEligibilityStatus.ELIGIBLE
        return result
    if driver and vehicle and not carrier:
        result.status = MatchEligibilityStatus.ELIGIBLE
        return result
    if carrier and driver and vehicle:
        result.status = MatchEligibilityStatus.ELIGIBLE
        return result
    result.add(
        code=MatchEligibilityReasonCode.INVALID_CANDIDATE_SHAPE,
        blocking=True,
        message="Combinação carrier/driver/vehicle inválida.",
    )
    return result


def evaluate_private_target_access(
    *,
    offer: FreightOffer,
    carrier: CarrierProfile | None,
    driver: Driver | None,
    target_carrier_ids: set,
    target_driver_ids: set,
) -> EligibilityResult:
    result = EligibilityResult(status=MatchEligibilityStatus.ELIGIBLE)
    if offer.audience != FreightOfferAudience.PRIVATE.value:
        return result
    if carrier and carrier.id in target_carrier_ids:
        return result
    if driver and driver.id in target_driver_ids:
        return result
    result.add(
        code=MatchEligibilityReasonCode.PRIVATE_TARGET_NOT_ALLOWED,
        blocking=True,
        message="Entidade fora dos targets privados da oferta.",
    )
    return result


def evaluate_carrier_eligibility(*, offer: FreightOffer, carrier: CarrierProfile) -> EligibilityResult:
    result = EligibilityResult(status=MatchEligibilityStatus.ELIGIBLE)
    if carrier.tenant_id != offer.organization_id:
        result.add(
            code=MatchEligibilityReasonCode.OUT_OF_SCOPE,
            blocking=True,
            message="Transportadora fora do tenant.",
        )
        return result
    # Only carriers with status ACTIVE are eligible
    if carrier.status != CarrierStatus.ACTIVE.value:
        result.add(
            code=MatchEligibilityReasonCode.ENTITY_INACTIVE,
            blocking=True,
            message="Transportadora inativa.",
        )
    compliance = evaluate_entity_compliance(
        entity_type=EntityType.CARRIER,
        documents=carrier.documents.all(),
    )
    if compliance.status != ComplianceStatus.COMPLIANT:
        result.add(
            code=MatchEligibilityReasonCode.COMPLIANCE_NOT_COMPLIANT,
            blocking=True,
            message=str(compliance.status.value),
        )
    cargo_profile = offer.premises_snapshot.get("cargo_profile", "")
    if cargo_profile == FreightCargoProfile.REFRIGERATED_CARGO.value:
        if carrier.cargo_profile not in {
            CarrierCargoProfile.REFRIGERATED_CARGO.value,
            CarrierCargoProfile.BOTH.value,
        }:
            result.add(
                code=MatchEligibilityReasonCode.CARGO_PROFILE_INCOMPATIBLE,
                blocking=True,
                message="Transportadora sem perfil refrigerado.",
            )
    return result


def evaluate_driver_eligibility(*, offer: FreightOffer, driver: Driver) -> EligibilityResult:
    result = EligibilityResult(status=MatchEligibilityStatus.ELIGIBLE)
    if driver.organization_id != offer.organization_id:
        result.add(
            code=MatchEligibilityReasonCode.OUT_OF_SCOPE,
            blocking=True,
            message="Motorista fora do tenant.",
        )
        return result
    if driver.status != DriverStatus.ACTIVE.value:
        result.add(
            code=MatchEligibilityReasonCode.ENTITY_INACTIVE,
            blocking=True,
            message="Motorista inativo.",
        )
    compliance = evaluate_entity_compliance(
        entity_type=EntityType.DRIVER,
        documents=driver.documents.all(),
    )
    if compliance.status != ComplianceStatus.COMPLIANT:
        result.add(
            code=MatchEligibilityReasonCode.COMPLIANCE_NOT_COMPLIANT,
            blocking=True,
            message=str(compliance.status.value),
        )
    if driver.availability_status not in {
        DriverAvailabilityStatus.AVAILABLE.value,
        DriverAvailabilityStatus.PAUSED.value,
    }:
        result.add(
            code=MatchEligibilityReasonCode.NOT_AVAILABLE,
            blocking=False,
            message=f"availability={driver.availability_status}",
        )
    return result


def evaluate_vehicle_eligibility(
    *,
    offer: FreightOffer,
    vehicle: Vehicle,
    refrigeration: RefrigerationProfile | None = None,
) -> EligibilityResult:
    result = EligibilityResult(status=MatchEligibilityStatus.ELIGIBLE)
    if vehicle.organization_id != offer.organization_id:
        result.add(
            code=MatchEligibilityReasonCode.OUT_OF_SCOPE,
            blocking=True,
            message="Veículo fora do tenant.",
        )
        return result
    if vehicle.status != VehicleStatus.ACTIVE.value:
        result.add(
            code=MatchEligibilityReasonCode.ENTITY_INACTIVE,
            blocking=True,
            message="Veículo inativo.",
        )
    if vehicle.operational_status not in {
        VehicleOperationalStatus.AVAILABLE.value,
        VehicleOperationalStatus.ASSIGNED.value,
    }:
        result.add(
            code=MatchEligibilityReasonCode.NOT_AVAILABLE,
            blocking=False,
            message=f"operational_status={vehicle.operational_status}",
        )
    compliance = evaluate_entity_compliance(
        entity_type=EntityType.VEHICLE,
        documents=vehicle.documents.all(),
    )
    if compliance.status != ComplianceStatus.COMPLIANT:
        result.add(
            code=MatchEligibilityReasonCode.COMPLIANCE_NOT_COMPLIANT,
            blocking=True,
            message=str(compliance.status.value),
        )

    snapshot = offer.premises_snapshot
    required_type = snapshot.get("vehicle_type_required") or ""
    if required_type and vehicle.vehicle_type != required_type:
        result.add(
            code=MatchEligibilityReasonCode.VEHICLE_TYPE_INCOMPATIBLE,
            blocking=True,
            message=f"required={required_type} actual={vehicle.vehicle_type}",
        )
    required_body = snapshot.get("body_type_required") or ""
    if required_body and vehicle.body_type and vehicle.body_type != required_body:
        result.add(
            code=MatchEligibilityReasonCode.BODY_TYPE_INCOMPATIBLE,
            blocking=True,
            message=f"required={required_body} actual={vehicle.body_type}",
        )

    cargo_profile = snapshot.get("cargo_profile", "")
    if cargo_profile == FreightCargoProfile.REFRIGERATED_CARGO.value:
        if vehicle.cargo_profile not in {
            VehicleCargoProfile.REFRIGERATED_CARGO.value,
            VehicleCargoProfile.BOTH.value,
        } and not vehicle.refrigerated:
            result.add(
                code=MatchEligibilityReasonCode.CARGO_PROFILE_INCOMPATIBLE,
                blocking=True,
                message="Veículo sem capacidade refrigerada.",
            )
        temp_min = _snapshot_decimal(snapshot.get("temperature_min_c"))
        temp_max = _snapshot_decimal(snapshot.get("temperature_max_c"))
        if temp_min is not None and temp_max is not None:
            if not refrigeration and not vehicle.refrigerated:
                result.add(
                    code=MatchEligibilityReasonCode.TEMPERATURE_RANGE_INCOMPATIBLE,
                    blocking=True,
                    message="Sem perfil térmico do veículo.",
                )
            elif refrigeration:
                if (
                    refrigeration.temperature_max_c < temp_min
                    or refrigeration.temperature_min_c > temp_max
                ):
                    result.add(
                        code=MatchEligibilityReasonCode.TEMPERATURE_RANGE_INCOMPATIBLE,
                        blocking=True,
                        message="Faixa térmica do veículo incompatível com a carga.",
                    )
    elif cargo_profile == FreightCargoProfile.DRY_CARGO.value:
        if vehicle.cargo_profile == VehicleCargoProfile.REFRIGERATED_CARGO.value:
            result.add(
                code=MatchEligibilityReasonCode.CARGO_PROFILE_INCOMPATIBLE,
                blocking=False,
                message="Veículo exclusivamente refrigerado para carga seca.",
            )

    weight = _snapshot_decimal(snapshot.get("weight_kg"))
    if weight is not None and vehicle.capacity_weight_kg is not None:
        if vehicle.capacity_weight_kg < weight:
            result.add(
                code=MatchEligibilityReasonCode.NO_COMPATIBLE_VEHICLE,
                blocking=True,
                message="Capacidade de peso insuficiente.",
            )
    return result


def merge_eligibility_results(*results: EligibilityResult) -> EligibilityResult:
    merged = EligibilityResult(status=MatchEligibilityStatus.ELIGIBLE)
    for item in results:
        for reason in item.reasons:
            merged.add(code=reason.code, blocking=reason.blocking, message=reason.message)
    if merged.status != MatchEligibilityStatus.INELIGIBLE and any(
        result.status == MatchEligibilityStatus.UNKNOWN for result in results
    ):
        merged.status = MatchEligibilityStatus.UNKNOWN
    return merged


def load_private_target_ids(offer: FreightOffer) -> tuple[set, set]:
    if offer.audience != FreightOfferAudience.PRIVATE.value:
        return set(), set()
    targets = offer.targets.all()
    return (
        {target.carrier_id for target in targets if target.carrier_id},
        {target.driver_id for target in targets if target.driver_id},
    )
