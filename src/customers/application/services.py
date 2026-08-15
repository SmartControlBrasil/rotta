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
