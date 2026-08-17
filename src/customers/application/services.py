from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from src.audit.infrastructure.django.services import record_audit_event
from src.customers.domain.enums import CustomerStatus, CustomerType
from src.customers.infrastructure.django.models import Customer
from src.organizations.infrastructure.django.models import BusinessUnit, Organization


@dataclass(frozen=True)
class CustomerData:
    organization: Organization
    customer_type: CustomerType
    legal_name: str
    document_number: str
    email: str
    trade_name: str = ""
    state_registration: str = ""
    municipal_registration: str = ""
    phone: str = ""
    mobile_phone: str = ""
    postal_code: str = ""
    street: str = ""
    number: str = ""
    complement: str = ""
    district: str = ""
    city: str = ""
    state: str = ""
    country: str = "BR"
    status: CustomerStatus = CustomerStatus.PROSPECT
    business_unit: BusinessUnit | None = None
    owner: Any | None = None


@transaction.atomic
def register_customer(*, data: CustomerData, actor=None) -> Customer:
    customer = Customer(
        organization=data.organization,
        customer_type=data.customer_type,
        legal_name=data.legal_name,
        trade_name=data.trade_name,
        document_number=data.document_number,
        state_registration=data.state_registration,
        municipal_registration=data.municipal_registration,
        email=data.email,
        phone=data.phone,
        mobile_phone=data.mobile_phone,
        postal_code=data.postal_code,
        street=data.street,
        number=data.number,
        complement=data.complement,
        district=data.district,
        city=data.city,
        state=data.state,
        country=data.country,
        status=data.status,
        business_unit=data.business_unit,
        owner=data.owner,
    )
    customer.full_clean()
    customer.save()
    record_audit_event(
        action="customer_created",
        actor=actor,
        organization=customer.organization,
        target=customer,
        after=_customer_audit_payload(customer),
    )
    return customer


@transaction.atomic
def update_customer(customer: Customer, *, actor=None, **changes) -> Customer:
    before = _customer_audit_payload(customer)
    allowed_fields = {
        "legal_name",
        "trade_name",
        "document_number",
        "state_registration",
        "municipal_registration",
        "email",
        "phone",
        "mobile_phone",
        "postal_code",
        "street",
        "number",
        "complement",
        "district",
        "city",
        "state",
        "country",
        "business_unit",
    }
    for field, value in changes.items():
        if field not in allowed_fields:
            raise ValidationError({field: "Campo não pode ser atualizado por este caso de uso."})
        setattr(customer, field, value)
    customer.full_clean()
    customer.save()
    record_audit_event(
        action="customer_updated",
        actor=actor,
        organization=customer.organization,
        target=customer,
        before=before,
        after=_customer_audit_payload(customer),
    )
    return customer


@transaction.atomic
def change_customer_status(customer: Customer, *, status: CustomerStatus, actor=None) -> Customer:
    before = _customer_audit_payload(customer)
    customer.status = status
    customer.full_clean()
    customer.save(update_fields=["status", "updated_at"])
    record_audit_event(
        action="customer_status_changed",
        actor=actor,
        organization=customer.organization,
        target=customer,
        before=before,
        after=_customer_audit_payload(customer),
        metadata={"status": str(status)},
    )
    return customer


@transaction.atomic
def assign_customer_owner(customer: Customer, *, owner: Any, actor=None) -> Customer:
    before = _customer_audit_payload(customer)
    customer.owner = owner
    customer.full_clean()
    customer.save(update_fields=["owner", "updated_at"])
    record_audit_event(
        action="customer_owner_changed",
        actor=actor,
        organization=customer.organization,
        target=customer,
        before=before,
        after=_customer_audit_payload(customer),
        metadata={"owner_id": str(owner.id) if owner else ""},
    )
    return customer


def _customer_audit_payload(customer: Customer) -> dict[str, Any]:
    return {
        "id": str(customer.id),
        "customer_type": str(customer.customer_type),
        "legal_name": customer.legal_name,
        "trade_name": customer.trade_name,
        "document_number": "[REDACTED]" if customer.document_number else "",
        "state_registration": customer.state_registration,
        "municipal_registration": customer.municipal_registration,
        "email": "[REDACTED]" if customer.email else "",
        "phone": "[REDACTED]" if customer.phone else "",
        "mobile_phone": "[REDACTED]" if customer.mobile_phone else "",
        "status": str(customer.status),
        "organization_id": str(customer.organization_id),
        "business_unit_id": str(customer.business_unit_id) if customer.business_unit_id else "",
        "owner_id": str(customer.owner_id) if customer.owner_id else "",
    }


def _parse_simplified_address(address_data, stop_type, sequence, default_date=None):
    from src.freights.application.services import StopData
    from src.freights.domain.enums import FreightStopType
    
    if isinstance(address_data, str):
        parts = [p.strip() for p in address_data.split("-")]
        city = ""
        state = ""
        if len(parts) >= 2:
            city = parts[0]
            state = parts[1][:2].upper()
        else:
            city = address_data
        return StopData(
            stop_type=stop_type,
            sequence=sequence,
            city=city,
            state=state,
            scheduled_date=default_date
        )
    elif isinstance(address_data, dict):
        return StopData(
            stop_type=stop_type,
            sequence=sequence,
            postal_code=address_data.get("postal_code", ""),
            street=address_data.get("street", ""),
            number=address_data.get("number", ""),
            complement=address_data.get("complement", ""),
            district=address_data.get("district", ""),
            city=address_data.get("city", ""),
            state=address_data.get("state", "").upper() if address_data.get("state") else "",
            scheduled_date=address_data.get("scheduled_date") or default_date,
            window_start=address_data.get("window_start"),
            window_end=address_data.get("window_end"),
        )
    else:
        raise ValidationError({"address": "Formato de endereço inválido."})


@transaction.atomic
def create_customer_freight_request(
    *,
    actor: Any,
    customer: Customer,
    payload: dict[str, Any],
) -> Any:
    from decimal import Decimal
    from django.utils import timezone
    from django.core.exceptions import PermissionDenied
    from src.organizations.infrastructure.django.models import Membership
    from src.freights.application.services import (
        CargoData,
        FreightRequestData,
        create_freight_request
    )
    from src.freights.domain.enums import FreightStopType, FreightCargoProfile, FreightCargoType
    
    # 1. Validate active membership
    membership = Membership.objects.filter(
        user=actor,
        organization=customer.organization,
        status="ACTIVE"
    ).first()
    if not membership:
        raise PermissionDenied("Usuário sem vínculo ativo com a organização do cliente.")
        
    # 2. Parse scheduled date / service type
    service_type = payload.get("service_type", "ON_DEMAND")
    when = payload.get("when")
    
    scheduled_date = timezone.localdate()
    if service_type == "SCHEDULED":
        if not when:
            raise ValidationError({"when": "Data de agendamento é obrigatória para serviços agendados."})
        
        if isinstance(when, str):
            from django.utils.dateparse import parse_date
            parsed = parse_date(when)
            if not parsed:
                from django.utils.dateparse import parse_datetime
                dt = parse_datetime(when)
                parsed = dt.date() if dt else None
            if not parsed:
                raise ValidationError({"when": "Formato de data inválido. Use AAAA-MM-DD."})
            scheduled_date = parsed
        elif isinstance(when, (timezone.datetime, timezone.datetime.date)):
            scheduled_date = when.date() if isinstance(when, timezone.datetime) else when
            
        if scheduled_date < timezone.localdate():
            raise ValidationError({"when": "A data de agendamento não pode ser no passado."})
            
    # 3. Parse cargo
    cargo_payload = payload.get("cargo", {})
    refrigerated = cargo_payload.get("refrigerated", False)
    profile = FreightCargoProfile.REFRIGERATED_CARGO if refrigerated else FreightCargoProfile.DRY_CARGO
    
    weight_kg = cargo_payload.get("weight_kg") or cargo_payload.get("approx_weight_kg")
    if weight_kg is not None:
        try:
            weight_kg = Decimal(str(weight_kg))
        except (ValueError, TypeError):
            raise ValidationError({"weight_kg": "Peso inválido."})
            
    volume_m3 = cargo_payload.get("volume_m3")
    if volume_m3 is not None:
        try:
            volume_m3 = Decimal(str(volume_m3))
        except (ValueError, TypeError):
            raise ValidationError({"volume_m3": "Volume inválido."})
            
    cargo_data = CargoData(
        description=cargo_payload.get("description", "Carga Geral"),
        cargo_type=FreightCargoType.GENERAL_CARGO,
        cargo_profile=profile,
        weight_kg=weight_kg,
        volume_m3=volume_m3,
    )
    
    # 4. Parse stops
    origin_stop = _parse_simplified_address(payload.get("origin"), FreightStopType.PICKUP, 1, scheduled_date)
    dest_stop = _parse_simplified_address(payload.get("destination"), FreightStopType.DELIVERY, 2, scheduled_date)
    
    # 5. Build freight request DTO
    req_data = FreightRequestData(
        organization=customer.organization,
        customer=customer,
        created_by=actor,
        owner=actor,
        instructions=payload.get("notes") or "",
        handling_requirements=payload.get("contact") or "",
        stops=(origin_stop, dest_stop),
        cargo=cargo_data,
    )
    
    # 6. Execute backend creation service
    return create_freight_request(data=req_data, actor=actor)
