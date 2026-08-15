from __future__ import annotations

from src.carriers.domain.enums import CarrierCargoProfile, CarrierStatus
from src.carriers.infrastructure.django.models import CarrierProfile
from src.compliance.application.evaluation import evaluate_entity_compliance
from src.compliance.domain.enums import ComplianceStatus, EntityType
from src.drivers.domain.enums import DriverStatus
from src.drivers.infrastructure.django.models import Driver
from src.freights.domain.enums import FreightCargoProfile
from src.freights.infrastructure.django.models import FreightOffer


def is_carrier_eligible_for_offer(*, offer: FreightOffer, carrier: CarrierProfile) -> bool:
    if carrier.tenant_id != offer.organization_id:
        return False
    if carrier.status != CarrierStatus.ACTIVE.value:
        return False
    compliance = evaluate_entity_compliance(
        entity_type=EntityType.CARRIER,
        documents=carrier.documents.all(),
    )
    if compliance.status != ComplianceStatus.COMPLIANT:
        return False
    cargo_profile = offer.premises_snapshot.get("cargo_profile", "")
    if cargo_profile == FreightCargoProfile.REFRIGERATED_CARGO.value:
        if carrier.cargo_profile not in {
            CarrierCargoProfile.REFRIGERATED_CARGO.value,
            CarrierCargoProfile.BOTH.value,
        }:
            return False
    return True


def is_driver_eligible_for_offer(*, offer: FreightOffer, driver: Driver) -> bool:
    if driver.organization_id != offer.organization_id:
        return False
    if driver.status != DriverStatus.ACTIVE.value:
        return False
    compliance = evaluate_entity_compliance(
        entity_type=EntityType.DRIVER,
        documents=driver.documents.all(),
    )
    if compliance.status != ComplianceStatus.COMPLIANT:
        return False
    return True


def is_entity_eligible_for_offer(
    *,
    offer: FreightOffer,
    carrier: CarrierProfile | None = None,
    driver: Driver | None = None,
) -> bool:
    if carrier is not None and driver is not None:
        return False
    if carrier is not None:
        return is_carrier_eligible_for_offer(offer=offer, carrier=carrier)
    if driver is not None:
        return is_driver_eligible_for_offer(offer=offer, driver=driver)
    return False
