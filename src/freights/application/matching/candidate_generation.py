from __future__ import annotations

from dataclasses import dataclass

from src.carriers.infrastructure.django.models import CarrierProfile
from src.drivers.infrastructure.django.models import Driver
from src.freights.domain.offer_enums import FreightOfferAudience
from src.freights.infrastructure.django.models import FreightOffer
from src.vehicles.infrastructure.django.models import Vehicle


@dataclass(frozen=True)
class CandidateSpec:
    carrier: CarrierProfile | None = None
    driver: Driver | None = None
    vehicle: Vehicle | None = None


def iter_candidate_specs(*, offer: FreightOffer) -> list[CandidateSpec]:
    audience = offer.audience
    specs: list[CandidateSpec] = []
    seen: set[tuple] = set()

    def add_spec(spec: CandidateSpec) -> None:
        key = (
            spec.carrier.id if spec.carrier else None,
            spec.driver.id if spec.driver else None,
            spec.vehicle.id if spec.vehicle else None,
        )
        if key in seen:
            return
        seen.add(key)
        specs.append(spec)

    target_carrier_ids = {target.carrier_id for target in offer.targets.all() if target.carrier_id}
    target_driver_ids = {target.driver_id for target in offer.targets.all() if target.driver_id}

    include_carriers = audience in {
        FreightOfferAudience.CARRIERS.value,
        FreightOfferAudience.BOTH.value,
        FreightOfferAudience.PRIVATE.value,
    }
    include_drivers = audience in {
        FreightOfferAudience.DRIVERS.value,
        FreightOfferAudience.BOTH.value,
        FreightOfferAudience.PRIVATE.value,
    }

    if include_carriers:
        carriers = CarrierProfile.objects.filter(
            tenant=offer.organization,
            status="ACTIVE",
        ).prefetch_related(
            "documents",
            "driver_links__driver__documents",
            "vehicle_links__vehicle__documents",
            "vehicle_links__vehicle__refrigeration_profile",
        )
        if audience == FreightOfferAudience.PRIVATE.value:
            carriers = carriers.filter(id__in=target_carrier_ids)
        for carrier in carriers:
            add_spec(CandidateSpec(carrier=carrier))
            active_driver_links = [link for link in carrier.driver_links.all() if link.active]
            active_vehicle_links = [link for link in carrier.vehicle_links.all() if link.active]
            for driver_link in active_driver_links:
                for vehicle_link in active_vehicle_links:
                    add_spec(
                        CandidateSpec(
                            carrier=carrier,
                            driver=driver_link.driver,
                            vehicle=vehicle_link.vehicle,
                        )
                    )

    if include_drivers:
        drivers = Driver.objects.filter(
            organization=offer.organization,
            status="ACTIVE",
        ).prefetch_related(
            "documents",
            "vehicle_assignments__vehicle__documents",
            "vehicle_assignments__vehicle__refrigeration_profile",
        )
        if audience == FreightOfferAudience.PRIVATE.value:
            drivers = drivers.filter(id__in=target_driver_ids)
        for driver in drivers:
            active_assignments = [
                assignment
                for assignment in driver.vehicle_assignments.all()
                if assignment.active
            ]
            for assignment in active_assignments:
                add_spec(CandidateSpec(driver=driver, vehicle=assignment.vehicle))

    return specs
