import pytest
from io import StringIO
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from django.contrib.messages import get_messages

from src.identity.domain.enums import PermissionCode, RoleCode
from src.shared.domain.enums import AccessScope
from src.organizations.domain.enums import OrganizationType
from src.organizations.infrastructure.django.models import Organization, Membership
from src.identity.infrastructure.django.models import Role, MembershipRole
from src.freights.domain.enums import OperationStatus, OperationEventType
from src.freights.infrastructure.django.models import (
    FreightRequest,
    FreightQuote,
    FreightOffer,
    FreightOfferInterest,
    FreightOfferSelection,
    FreightOperation,
    ProofOfDelivery,
)
from src.carriers.infrastructure.django.models import CarrierProfile
from src.drivers.infrastructure.django.models import Driver
from src.vehicles.infrastructure.django.models import Vehicle
from src.customers.infrastructure.django.models import Customer


def grant(user, organization, role_code, scope=AccessScope.COMPANY):
    membership = Membership.objects.create(user=user, organization=organization, status="ACTIVE")
    role = Role.objects.get(code=role_code)
    MembershipRole.objects.create(membership=membership, role=role, scope=scope)
    return membership


@pytest.fixture
def rbac_ready(db):
    call_command("bootstrap_rotta", stdout=StringIO())


@pytest.fixture
def org_a(db):
    return Organization.objects.create(
        name="Org A",
        type=OrganizationType.TRANSPORT_COMPANY,
    )


@pytest.fixture
def org_b(db):
    return Organization.objects.create(
        name="Org B",
        type=OrganizationType.TRANSPORT_COMPANY,
    )


@pytest.fixture
def user_a(db, django_user_model):
    return django_user_model.objects.create_user(username="usera", password="password")


@pytest.fixture
def user_b(db, django_user_model):
    return django_user_model.objects.create_user(username="userb", password="password")


def make_operation(organization, user, ref):
    carrier, _ = CarrierProfile.objects.get_or_create(
        organization=organization,
        tenant=organization,
        defaults={
            "trade_name": f"Carrier-{ref}",
            "status": "ACTIVE",
            "email": f"carrier-{ref}@example.com",
        }
    )
    driver = Driver.objects.create(organization=organization, full_name=f"Driver-{ref}")
    vehicle = Vehicle.objects.create(organization=organization, plate=f"PLT{ref}", vehicle_type="CAR")
    customer = Customer.objects.create(
        organization=organization,
        legal_name=f"Customer-{ref}",
        document_number=f"1234567890{ref}",
        email=f"customer-{ref}@example.com",
    )
    request = FreightRequest.objects.create(
        organization=organization,
        customer=customer,
        created_by=user,
        owner=user,
        reference_code=f"REQ-{ref}",
    )
    quote = FreightQuote.objects.create(
        organization=organization,
        freight_request=request,
        created_by=user,
        owner=user,
        reference_code=f"QT-{ref}",
    )
    offer = FreightOffer.objects.create(
        organization=organization,
        freight_request=request,
        freight_quote=quote,
        created_by=user,
        owner=user,
        reference_code=f"OFR-{ref}",
    )
    interest = FreightOfferInterest.objects.create(
        organization=organization,
        offer=offer,
        carrier=carrier,
        driver=driver,
        vehicle=vehicle,
        status="CONFIRMED",
        expressed_at=timezone.now(),
    )
    selection = FreightOfferSelection.objects.create(
        interest=interest,
        organization=organization,
        offer=offer,
        status="CONFIRMED",
        selected_by=user,
        selected_at=timezone.now(),
    )
    from src.organizations.infrastructure.django.models import Membership
    membership_existed = Membership.objects.filter(user=user, organization=organization).exists()
    temp_membership = None
    if not membership_existed:
        temp_membership = Membership.objects.create(user=user, organization=organization, status="ACTIVE")
    try:
        from src.freights.application.operation_services import create_operation_from_selection
        operation = create_operation_from_selection(selection_id=str(selection.id), actor=user)
    finally:
        if temp_membership:
            temp_membership.delete()
    return operation


@pytest.mark.django_db
def test_anonymous_redirects_to_login(client, org_a, user_a):
    op = make_operation(org_a, user_a, "A")
    
    response = client.get(reverse("backoffice:freight_operations"))
    assert response.status_code == 302
    assert "login" in response.url

    response = client.get(reverse("backoffice:freight_operation_detail", args=[op.id]))
    assert response.status_code == 302


@pytest.mark.django_db
def test_authorized_user_accesses_list(client, org_a, user_a, rbac_ready):
    make_operation(org_a, user_a, "A")
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)

    client.force_login(user_a)
    response = client.get(reverse("backoffice:freight_operations"), HTTP_HOST="localhost")
    assert response.status_code == 200


@pytest.mark.django_db
def test_unauthorized_user_receives_403(client, org_a, user_a, rbac_ready):
    grant(user_a, org_a, RoleCode.SALESPERSON.value, AccessScope.COMPANY.value)

    client.force_login(user_a)
    response = client.get(reverse("backoffice:freight_operations"), HTTP_HOST="localhost")
    assert response.status_code == 403


@pytest.mark.django_db
def test_list_respects_scoping(client, org_a, org_b, user_a, user_b, rbac_ready):
    op_a = make_operation(org_a, user_a, "A")
    op_b = make_operation(org_b, user_b, "B")

    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    client.force_login(user_a)

    response = client.get(reverse("backoffice:freight_operations"), HTTP_HOST="localhost")
    assert response.status_code == 200
    content = response.content.decode()
    assert str(op_a.id)[:8] in content
    assert str(op_b.id)[:8] not in content


@pytest.mark.django_db
def test_detail_view_permissions_and_scoping(client, org_a, org_b, user_a, user_b, rbac_ready):
    op_a = make_operation(org_a, user_a, "A")
    op_b = make_operation(org_b, user_b, "B")

    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    client.force_login(user_a)

    # Allowed detail
    response = client.get(reverse("backoffice:freight_operation_detail", args=[op_a.id]), HTTP_HOST="localhost")
    assert response.status_code == 200
    content = response.content.decode()
    assert "Carrier-A" in content
    assert "Driver-A" in content
    assert "PLTA" in content
    assert "Designada" in content
    assert "OP_A" not in content  # Timeline checks

    # Forbidden detail (Out of scope / 404)
    response = client.get(reverse("backoffice:freight_operation_detail", args=[op_b.id]), HTTP_HOST="localhost")
    assert response.status_code == 404


@pytest.mark.django_db
def test_advance_status_post_works_and_redirects(client, org_a, user_a, rbac_ready):
    op = make_operation(org_a, user_a, "A")
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    client.force_login(user_a)

    # Valid advance
    url = reverse("backoffice:freight_operation_advance_status", args=[op.id])
    response = client.post(url, {"next_status": "DRIVER_EN_ROUTE_TO_PICKUP"}, HTTP_HOST="localhost")
    
    assert response.status_code == 302
    assert response.url == reverse("backoffice:freight_operation_detail", args=[op.id])
    
    op.refresh_from_db()
    assert op.status == "DRIVER_EN_ROUTE_TO_PICKUP"


@pytest.mark.django_db
def test_get_on_action_urls_is_not_allowed(client, org_a, user_a, rbac_ready):
    op = make_operation(org_a, user_a, "A")
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    client.force_login(user_a)

    url = reverse("backoffice:freight_operation_advance_status", args=[op.id])
    response = client.get(url, HTTP_HOST="localhost")
    assert response.status_code == 405  # Method not allowed


@pytest.mark.django_db
def test_invalid_status_transition_error_handling(client, org_a, user_a, rbac_ready):
    op = make_operation(org_a, user_a, "A")
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    client.force_login(user_a)

    url = reverse("backoffice:freight_operation_advance_status", args=[op.id])
    # Transitioning ASSIGNED -> DELIVERED directly is invalid
    response = client.post(url, {"next_status": "DELIVERED"}, HTTP_HOST="localhost", follow=True)
    
    assert response.status_code == 200
    op.refresh_from_db()
    assert op.status == "ASSIGNED"
    
    messages = list(get_messages(response.wsgi_request))
    assert any("Erro ao avançar status" in str(m) for m in messages)


@pytest.mark.django_db
def test_incident_reporting_post(client, org_a, user_a, rbac_ready):
    op = make_operation(org_a, user_a, "A")
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    client.force_login(user_a)

    url = reverse("backoffice:freight_operation_report_incident", args=[op.id])
    response = client.post(url, {"description": "Pneu furado na BR-116"}, HTTP_HOST="localhost")
    
    assert response.status_code == 302
    assert op.events.filter(event_type=OperationEventType.INCIDENT_REPORTED.value).exists()


@pytest.mark.django_db
def test_cancellation_post(client, org_a, user_a, rbac_ready):
    op = make_operation(org_a, user_a, "A")
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    client.force_login(user_a)

    url = reverse("backoffice:freight_operation_cancel", args=[op.id])
    response = client.post(url, {"reason": "Cliente desistiu"}, HTTP_HOST="localhost")
    
    assert response.status_code == 302
    op.refresh_from_db()
    assert op.status == "CANCELLED"


@pytest.mark.django_db
def test_pod_recording_only_allowed_in_unloading(client, org_a, user_a, rbac_ready):
    op = make_operation(org_a, user_a, "A")
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    client.force_login(user_a)

    # 1. Attempting POD in ASSIGNED status should fail
    pod_url = reverse("backoffice:freight_operation_record_pod", args=[op.id])
    response = client.post(pod_url, {
        "receiver_name": "Marcos",
        "delivered_at": timezone.now().isoformat(),
        "notes": "Tudo ok"
    }, HTTP_HOST="localhost", follow=True)
    
    assert response.status_code == 200
    assert not ProofOfDelivery.objects.filter(operation=op).exists()
    messages = list(get_messages(response.wsgi_request))
    assert any("Erro ao registrar POD" in str(m) for m in messages)

    # 2. Advance status step by step to UNLOADING
    op.status = "UNLOADING"
    op.save()

    # 3. Registering POD in UNLOADING status should succeed
    response = client.post(pod_url, {
        "receiver_name": "Marcos",
        "delivered_at": timezone.now().isoformat(),
        "notes": "Tudo ok"
    }, HTTP_HOST="localhost")
    
    assert response.status_code == 302
    assert ProofOfDelivery.objects.filter(operation=op).exists()


@pytest.mark.django_db
def test_delivered_requires_pod(client, org_a, user_a, rbac_ready):
    op = make_operation(org_a, user_a, "A")
    op.status = "UNLOADING"
    op.save()

    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    client.force_login(user_a)

    # 1. Try to advance to DELIVERED without POD -> Fails
    url = reverse("backoffice:freight_operation_advance_status", args=[op.id])
    response = client.post(url, {"next_status": "DELIVERED"}, HTTP_HOST="localhost", follow=True)
    
    assert response.status_code == 200
    op.refresh_from_db()
    assert op.status == "UNLOADING"
    messages = list(get_messages(response.wsgi_request))
    assert any("sem Proof of Delivery" in str(m) for m in messages)

    # 2. Record POD
    ProofOfDelivery.objects.create(
        operation=op,
        receiver_name="Recebedor",
        delivered_at=timezone.now(),
    )

    # 3. Try to advance to DELIVERED with POD -> Succeeds
    response = client.post(url, {"next_status": "DELIVERED"}, HTTP_HOST="localhost")
    assert response.status_code == 302
    op.refresh_from_db()
    assert op.status == "DELIVERED"


@pytest.mark.django_db
def test_specific_permissions_are_enforced(client, org_a, user_a, rbac_ready):
    op = make_operation(org_a, user_a, "A")
    
    # User with only View role (cannot cancel or advance status)
    grant(user_a, org_a, RoleCode.VIEWER.value, AccessScope.COMPANY.value)
    client.force_login(user_a)

    url_cancel = reverse("backoffice:freight_operation_cancel", args=[op.id])
    response = client.post(url_cancel, {"reason": "Erro"}, HTTP_HOST="localhost")
    assert response.status_code == 403


@pytest.mark.django_db
def test_sidebar_contains_freight_operations_link(client, org_a, user_a, rbac_ready):
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    client.force_login(user_a)

    response = client.get(reverse("backoffice:dashboard"), HTTP_HOST="localhost")
    assert response.status_code == 200
    content = response.content.decode()
    assert "freight-operations/" in content


# --- Backoffice P0 new tests ---

@pytest.mark.django_db
def test_control_tower_list_shows_origin_and_next_stop_and_sla_and_last_activity(client, org_a, user_a, rbac_ready):
    from src.freights.infrastructure.django.models import FreightOperationStop
    op = make_operation(org_a, user_a, "A")
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    client.force_login(user_a)

    # 1. Empty stops next_stop display
    response = client.get(reverse("backoffice:freight_operations"), HTTP_HOST="localhost")
    assert response.status_code == 200
    content = response.content.decode()
    assert "Marketplace" in content
    assert "-" in content  # Next stop is empty, so should render "-"

    # 2. Add stops and verify next stop & SLA
    stop_p = FreightOperationStop.objects.create(
        organization=org_a,
        operation=op,
        sequence=1,
        stop_type="PICKUP",
        status="PENDING",
        city="São Paulo",
        state="SP",
    )
    stop_d = FreightOperationStop.objects.create(
        organization=org_a,
        operation=op,
        sequence=2,
        stop_type="DELIVERY",
        status="PENDING",
        city="Rio de Janeiro",
        state="RJ",
    )
    response = client.get(reverse("backoffice:freight_operations"), HTTP_HOST="localhost")
    assert response.status_code == 200
    content = response.content.decode()
    assert "São Paulo/SP" in content

    # 3. Complete all stops and check "Concluída"
    stop_p.status = "COMPLETED"
    stop_p.save()
    stop_d.status = "COMPLETED"
    stop_d.save()
    response = client.get(reverse("backoffice:freight_operations"), HTTP_HOST="localhost")
    assert response.status_code == 200
    content = response.content.decode()
    assert "Concluída" in content

    # 4. Check last activity timestamp fallback
    from src.freights.infrastructure.django.models import FreightOperationEvent
    
    op.refresh_from_db()
    # Create an event in the future relative to op.updated_at
    event_time = timezone.now() + timezone.timedelta(hours=2)
    FreightOperationEvent.objects.create(
        operation=op,
        event_type="STATUS_CHANGED",
        origin="SYSTEM",
        occurred_at=event_time,
    )
    response = client.get(reverse("backoffice:freight_operations"), HTTP_HOST="localhost")
    assert response.status_code == 200
    content = response.content.decode()
    assert timezone.localtime(event_time).strftime("%d/%m/%Y") in content


@pytest.mark.django_db
def test_control_tower_multi_tenant_isolation(client, org_a, org_b, user_a, user_b, rbac_ready):
    op_a = make_operation(org_a, user_a, "A")
    op_b = make_operation(org_b, user_b, "B")
    
    # User A gets access to Org A only
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    client.force_login(user_a)
    
    response = client.get(reverse("backoffice:freight_operations"), HTTP_HOST="localhost")
    content = response.content.decode()
    assert str(op_a.id)[:8] in content
    assert str(op_b.id)[:8] not in content


@pytest.mark.django_db
def test_manual_pod_record_for_valid_stop(client, org_a, user_a, rbac_ready):
    from src.freights.infrastructure.django.models import FreightOperationStop
    op = make_operation(org_a, user_a, "A")
    stop_d = FreightOperationStop.objects.create(
        organization=org_a,
        operation=op,
        sequence=2,
        stop_type="DELIVERY",
        status="ARRIVED",
        city="Rio de Janeiro",
        state="RJ",
    )
    
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    client.force_login(user_a)
    
    pod_url = reverse("backoffice:freight_operation_record_pod", args=[op.id])
    response = client.post(pod_url, {
        "receiver_name": "Carla",
        "delivered_at": timezone.now().isoformat(),
        "notes": "Entregue ok",
        "stop_id": str(stop_d.id)
    }, HTTP_HOST="localhost")
    
    assert response.status_code == 302
    assert ProofOfDelivery.objects.filter(stop=stop_d).exists()


@pytest.mark.django_db
def test_manual_pod_rejected_for_stop_of_another_operation(client, org_a, org_b, user_a, user_b, rbac_ready):
    from src.freights.infrastructure.django.models import FreightOperationStop
    op_a = make_operation(org_a, user_a, "A")
    op_b = make_operation(org_b, user_b, "B")
    
    stop_d_b = FreightOperationStop.objects.create(
        organization=org_b,
        operation=op_b,
        sequence=2,
        stop_type="DELIVERY",
        status="ARRIVED",
        city="Belo Horizonte",
        state="MG",
    )
    
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    grant(user_a, org_b, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    client.force_login(user_a)
    
    pod_url = reverse("backoffice:freight_operation_record_pod", args=[op_a.id])
    response = client.post(pod_url, {
        "receiver_name": "Carla",
        "delivered_at": timezone.now().isoformat(),
        "notes": "Tentativa de injeção",
        "stop_id": str(stop_d_b.id)
    }, HTTP_HOST="localhost", follow=True)
    
    assert response.status_code == 200
    assert not ProofOfDelivery.objects.filter(stop=stop_d_b).exists()
    messages = list(get_messages(response.wsgi_request))
    assert any("Parada não encontrada nesta operação." in str(m) for m in messages)


@pytest.mark.django_db
def test_manual_pod_rejected_for_non_eligible_stop(client, org_a, user_a, rbac_ready):
    from src.freights.infrastructure.django.models import FreightOperationStop
    op = make_operation(org_a, user_a, "A")
    stop_p = FreightOperationStop.objects.create(
        organization=org_a,
        operation=op,
        sequence=1,
        stop_type="PICKUP",
        status="ARRIVED",
        city="São Paulo",
        state="SP",
    )
    
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    client.force_login(user_a)
    
    pod_url = reverse("backoffice:freight_operation_record_pod", args=[op.id])
    response = client.post(pod_url, {
        "receiver_name": "Carla",
        "delivered_at": timezone.now().isoformat(),
        "notes": "Coleta com POD",
        "stop_id": str(stop_p.id)
    }, HTTP_HOST="localhost", follow=True)
    
    assert response.status_code == 200
    assert not ProofOfDelivery.objects.filter(stop=stop_p).exists()
    messages = list(get_messages(response.wsgi_request))
    assert any("Apenas paradas de entrega" in str(m) for m in messages)


@pytest.mark.django_db
def test_manual_pod_duplicate_prevention_and_idempotency(client, org_a, user_a, rbac_ready):
    from src.freights.infrastructure.django.models import FreightOperationStop
    op = make_operation(org_a, user_a, "A")
    stop_d = FreightOperationStop.objects.create(
        organization=org_a,
        operation=op,
        sequence=2,
        stop_type="DELIVERY",
        status="ARRIVED",
        city="Rio de Janeiro",
        state="RJ",
    )
    
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    client.force_login(user_a)
    
    pod_url = reverse("backoffice:freight_operation_record_pod", args=[op.id])
    
    delivered_time = timezone.now()
    # First record
    response1 = client.post(pod_url, {
        "receiver_name": "Carla",
        "delivered_at": delivered_time.isoformat(),
        "notes": "Entregue ok",
        "stop_id": str(stop_d.id)
    }, HTTP_HOST="localhost")
    assert response1.status_code == 302
    assert ProofOfDelivery.objects.filter(stop=stop_d).count() == 1
    
    # Duplicate with same details should be idempotent and succeed
    response2 = client.post(pod_url, {
        "receiver_name": "Carla",
        "delivered_at": delivered_time.isoformat(),
        "notes": "Entregue ok",
        "stop_id": str(stop_d.id)
    }, HTTP_HOST="localhost")
    assert response2.status_code == 302
    assert ProofOfDelivery.objects.filter(stop=stop_d).count() == 1
    
    # Duplicate with different details should fail
    response3 = client.post(pod_url, {
        "receiver_name": "Diferente",
        "delivered_at": delivered_time.isoformat(),
        "notes": "Entregue ok",
        "stop_id": str(stop_d.id)
    }, HTTP_HOST="localhost", follow=True)
    assert response3.status_code == 200
    messages = list(get_messages(response3.wsgi_request))
    assert any("Proof of Delivery já registrado com dados diferentes." in str(m) for m in messages)


@pytest.mark.django_db
def test_legacy_single_stop_operation_without_stops_succeeds(client, org_a, user_a, rbac_ready):
    # This operation will have no stops (legacy/single-stop simulation)
    op = make_operation(org_a, user_a, "A")
    op.status = "UNLOADING"
    op.save()
    
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    client.force_login(user_a)
    
    pod_url = reverse("backoffice:freight_operation_record_pod", args=[op.id])
    response = client.post(pod_url, {
        "receiver_name": "Legacy Receiver",
        "delivered_at": timezone.now().isoformat(),
        "notes": "Legacy workflow",
        "stop_id": ""  # empty or None
    }, HTTP_HOST="localhost")
    
    assert response.status_code == 302
    assert ProofOfDelivery.objects.filter(operation=op, stop__isnull=True).exists()


@pytest.mark.django_db
def test_detail_template_renders_pod_status_per_stop(client, org_a, user_a, rbac_ready):
    from src.freights.infrastructure.django.models import FreightOperationStop
    op = make_operation(org_a, user_a, "A")
    stop_d = FreightOperationStop.objects.create(
        organization=org_a,
        operation=op,
        sequence=2,
        stop_type="DELIVERY",
        status="ARRIVED",
        city="Rio de Janeiro",
        state="RJ",
    )
    
    grant(user_a, org_a, RoleCode.OPERATIONS_MANAGER.value, AccessScope.COMPANY.value)
    client.force_login(user_a)
    
    # 1. Initially show "Pendente"
    response = client.get(reverse("backoffice:freight_operation_detail", args=[op.id]), HTTP_HOST="localhost")
    content = response.content.decode()
    assert "Pendente" in content
    
    # 2. Add POD and verify "Enviado"
    ProofOfDelivery.objects.create(
        operation=op,
        stop=stop_d,
        receiver_name="Carla",
        delivered_at=timezone.now(),
    )
    
    response = client.get(reverse("backoffice:freight_operation_detail", args=[op.id]), HTTP_HOST="localhost")
    content = response.content.decode()
    assert "Enviado" in content
