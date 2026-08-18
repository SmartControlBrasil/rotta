from __future__ import annotations

from typing import Any, TypedDict, List, Optional
from django.core.exceptions import ValidationError
from django.db import transaction

from src.audit.infrastructure.django.services import record_audit_event
from src.drivers.infrastructure.django.models import (
    Driver,
    DriverPreference,
    DriverRegionPreference,
    DriverRegionPreferenceType,
)


class RegionData(TypedDict):
    city: str
    state: str


class DriverPreferencesData(TypedDict, total=False):
    base_city: str
    base_state: str
    base_postal_code: str
    base_latitude: Optional[float]
    base_longitude: Optional[float]
    preferred_radius_km: Optional[int]
    preferred_regions: List[RegionData]
    avoided_regions: List[RegionData]


def get_driver_preferences(driver: Driver) -> dict[str, Any]:
    """Retrieve driver preferences including preferred and avoided regions."""
    pref, _ = DriverPreference.objects.get_or_create(driver=driver)
    
    preferred_regions = list(
        driver.region_preferences.filter(preference_type=DriverRegionPreferenceType.PREFER)
        .values("city", "state")
    )
    avoided_regions = list(
        driver.region_preferences.filter(preference_type=DriverRegionPreferenceType.AVOID)
        .values("city", "state")
    )
    
    return {
        "base_city": pref.base_city,
        "base_state": pref.base_state,
        "base_postal_code": pref.base_postal_code,
        "base_latitude": float(pref.base_latitude) if pref.base_latitude is not None else None,
        "base_longitude": float(pref.base_longitude) if pref.base_longitude is not None else None,
        "preferred_radius_km": pref.preferred_radius_km,
        "preferred_regions": preferred_regions,
        "avoided_regions": avoided_regions,
    }


@transaction.atomic
def update_driver_preferences(
    driver: Driver,
    data: DriverPreferencesData,
    actor=None,
) -> DriverPreference:
    """Update driver preferences and associated preferred/avoided regions."""
    pref, _ = DriverPreference.objects.select_for_update().get_or_create(driver=driver)
    before = get_driver_preferences(driver)

    # 1. Update basic fields if they are in data
    from decimal import Decimal, ROUND_HALF_UP
    if "base_city" in data:
        pref.base_city = data["base_city"] or ""
    if "base_state" in data:
        pref.base_state = data["base_state"] or ""
    if "base_postal_code" in data:
        pref.base_postal_code = data["base_postal_code"] or ""
    if "base_latitude" in data:
        lat = data["base_latitude"]
        pref.base_latitude = Decimal(str(lat)).quantize(Decimal("1.000000"), rounding=ROUND_HALF_UP) if lat is not None else None
    if "base_longitude" in data:
        lon = data["base_longitude"]
        pref.base_longitude = Decimal(str(lon)).quantize(Decimal("1.000000"), rounding=ROUND_HALF_UP) if lon is not None else None
    if "preferred_radius_km" in data:
        pref.preferred_radius_km = data["preferred_radius_km"]

    # Validate preference model fields
    pref.full_clean()
    pref.save()

    # 2. Update preferred regions
    if "preferred_regions" in data:
        driver.region_preferences.filter(preference_type=DriverRegionPreferenceType.PREFER).delete()
        for reg in data["preferred_regions"]:
            city = reg.get("city")
            state = reg.get("state")
            if not city or not state:
                raise ValidationError({"preferred_regions": "Cidade e estado são obrigatórios."})
            
            region_pref = DriverRegionPreference(
                driver=driver,
                city=city,
                state=state,
                preference_type=DriverRegionPreferenceType.PREFER,
            )
            region_pref.full_clean()
            region_pref.save()

    # 3. Update avoided regions
    if "avoided_regions" in data:
        driver.region_preferences.filter(preference_type=DriverRegionPreferenceType.AVOID).delete()
        for reg in data["avoided_regions"]:
            city = reg.get("city")
            state = reg.get("state")
            if not city or not state:
                raise ValidationError({"avoided_regions": "Cidade e estado são obrigatórios."})
            
            region_pref = DriverRegionPreference(
                driver=driver,
                city=city,
                state=state,
                preference_type=DriverRegionPreferenceType.AVOID,
            )
            region_pref.full_clean()
            region_pref.save()

    # Get updated payload
    after = get_driver_preferences(driver)

    # 4. Record Audit Log
    record_audit_event(
        action="driver_preferences_updated",
        actor=actor,
        organization=driver.organization,
        target=driver,
        before=before,
        after=after,
    )

    return pref
