import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError, PermissionDenied
from django.utils import timezone
from django.db import transaction

from src.identity.infrastructure.django.models import User
from src.freights.infrastructure.django.models import FreightOperation, TrackingSession, LocationPoint, ProofOfDelivery, ThermalReading, ThermalExcursion
from src.freights.domain.enums import OperationStatus, TrackingSessionStatus, ThermalExcursionStatus, ThermalReadingValidity
from src.shared.interfaces.api.v1.auth import (
    generate_access_token,
    generate_refresh_token,
    validate_refresh_token,
    revoke_token,
    mobile_auth_required,
)

from src.freights.application.operation_services import (
    change_operation_status,
    report_operation_incident,
    record_proof_of_delivery,
    record_thermal_reading,
)
from src.freights.application.tracking_services import (
    start_tracking_session,
    record_location_point,
    end_tracking_session,
)
from src.freights.application.sla_service import SLAService, SLAState


def error_response(code: str, message: str, status_code: int = 400) -> JsonResponse:
    return JsonResponse({
        "error": {
            "code": code,
            "message": message
        }
    }, status=status_code)


def parse_json_body(request):
    try:
        return json.loads(request.body)
    except json.JSONDecodeError:
        return None


@csrf_exempt
def login_view(request):
    if request.method != "POST":
        return error_response("method_not_allowed", "Apenas método POST é suportado.", 405)
    
    body = parse_json_body(request)
    if body is None:
        return error_response("bad_request", "Corpo da requisição deve ser um JSON válido.", 400)
        
    username = body.get("username")
    password = body.get("password")
    
    if not username or not password:
        return error_response("bad_request", "Parâmetros 'username' e 'password' são obrigatórios.", 400)
        
    if "@" in username:
        try:
            user = User.objects.get(email=username)
            username = user.username
        except User.DoesNotExist:
            pass
            
    user = authenticate(request, username=username, password=password)
    if not user or not user.is_active:
        return error_response("unauthorized", "Credenciais inválidas.", 401)
        
    access = generate_access_token(user)
    refresh = generate_refresh_token(user)
    
    return JsonResponse({
        "access_token": access,
        "refresh_token": refresh,
        "expires_in": 900
    }, status=200)


@csrf_exempt
def token_refresh_view(request):
    if request.method != "POST":
        return error_response("method_not_allowed", "Apenas método POST é suportado.", 405)
        
    body = parse_json_body(request)
    if body is None:
        return error_response("bad_request", "Corpo da requisição deve ser um JSON válido.", 400)
        
    refresh_token = body.get("refresh_token")
    if not refresh_token:
        return error_response("bad_request", "O campo 'refresh_token' é obrigatório.", 400)
        
    user = validate_refresh_token(refresh_token)
    if not user:
        return error_response("unauthorized", "Refresh token inválido ou expirado.", 401)
        
    access = generate_access_token(user)
    return JsonResponse({
        "access_token": access,
        "expires_in": 900
    }, status=200)


@csrf_exempt
@mobile_auth_required
def token_revoke_view(request):
    if request.method != "POST":
        return error_response("method_not_allowed", "Apenas método POST é suportado.", 405)
        
    # Revoke current access token
    revoke_token(request.auth_token, duration=900)
    
    # Optionally revoke refresh token from body
    body = parse_json_body(request)
    if body:
        refresh_token = body.get("refresh_token")
        if refresh_token:
            revoke_token(refresh_token, duration=86400 * 30)
            
    return JsonResponse({"success": True}, status=200)


@csrf_exempt
@mobile_auth_required
def me_view(request):
    if request.method != "GET":
        return error_response("method_not_allowed", "Apenas método GET é suportado.", 405)
        
    user = request.user
    driver = request.driver
    
    from src.shared.interfaces.backoffice.authorization import user_has_backoffice_permission
    from src.identity.domain.enums import PermissionCode
    
    capabilities = []
    mobile_perms = [
        PermissionCode.TRACKING_VIEW,
        PermissionCode.TRACKING_START,
        PermissionCode.TRACKING_RECORD,
        PermissionCode.TRACKING_END,
        PermissionCode.FREIGHT_OPERATIONS_VIEW,
        PermissionCode.FREIGHT_OPERATIONS_CHANGE_STATUS,
        PermissionCode.FREIGHT_OPERATIONS_REPORT_INCIDENT,
        PermissionCode.FREIGHT_OPERATIONS_RECORD_POD,
        PermissionCode.FREIGHT_OPERATIONS_CANCEL,
    ]
    for perm in mobile_perms:
        if user_has_backoffice_permission(user, perm.value):
            capabilities.append(perm.value)
            
    return JsonResponse({
        "id": str(user.id),
        "username": user.username,
        "email": user.email,
        "driver": {
            "id": str(driver.id),
            "full_name": driver.full_name,
            "document": driver.document,
        },
        "organization": {
            "id": str(driver.organization.id),
            "name": driver.organization.name,
        },
        "capabilities": capabilities
    }, status=200)


@csrf_exempt
@mobile_auth_required
def driver_operations_view(request):
    if request.method != "GET":
        return error_response("method_not_allowed", "Apenas método GET é suportado.", 405)
        
    driver = request.driver
    operations = FreightOperation.objects.filter(driver=driver)\
        .select_related("selection__offer__freight_request")\
        .prefetch_related("selection__offer__freight_request__stops")\
        .order_by("-assigned_at")
    
    # Pagination
    try:
        page = int(request.GET.get("page", 1))
        page_size = int(request.GET.get("page_size", 10))
        if page < 1:
            page = 1
        if page_size < 1 or page_size > 50:
            page_size = 10
    except ValueError:
        page = 1
        page_size = 10

    total_count = operations.count()
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    paginated_ops = operations[start_idx:end_idx]

    base_url = request.build_absolute_uri(request.path)
    next_url = None
    if end_idx < total_count:
        next_url = f"{base_url}?page={page + 1}&page_size={page_size}"
    previous_url = None
    if page > 1:
        previous_url = f"{base_url}?page={page - 1}&page_size={page_size}"
    
    results = []
    for op in paginated_ops:
        offer = op.selection.offer if op.selection else None
        freight_request = offer.freight_request if offer else None
        stops = list(freight_request.stops.all()) if freight_request else []
        stops.sort(key=lambda s: (s.sequence, s.stop_type))
        
        origin_city = stops[0].city if stops else None
        destination_city = stops[-1].city if len(stops) > 1 else None
        
        sla_res = SLAService.compute(op)
        service_level_state = sla_res.state.value if sla_res.state != SLAState.UNKNOWN else None

        results.append({
            "id": str(op.id),
            "status": op.status,
            "reference_code": offer.reference_code if offer else None,
            "assigned_at": op.assigned_at.isoformat() if op.assigned_at else None,
            "origin": origin_city,
            "destination": destination_city,
            "load_type": op.load_type,
            "service_level_state": service_level_state,
        })
        
    return JsonResponse({
        "count": total_count,
        "next": next_url,
        "previous": previous_url,
        "results": results
    }, status=200)


@csrf_exempt
@mobile_auth_required
def driver_operation_detail_view(request, uuid):
    if request.method != "GET":
        return error_response("method_not_allowed", "Apenas método GET é suportado.", 405)
        
    driver = request.driver
    try:
        op = FreightOperation.objects.select_related(
            "carrier",
            "driver",
            "vehicle",
            "selection__offer__freight_request__cargo",
        ).prefetch_related(
            "selection__offer__freight_request__stops",
            "tracking_sessions",
            "events__actor",
            "thermal_readings",
            "thermal_excursions",
        ).get(id=uuid, driver=driver)
    except (FreightOperation.DoesNotExist, ValidationError):
        return error_response("not_found", "Operação não encontrada.", 404)
        
    stops = []
    if op.selection.offer and op.selection.offer.freight_request:
        for stop in op.selection.offer.freight_request.stops.all().order_by("sequence"):
            stops.append({
                "sequence": stop.sequence,
                "stop_type": stop.stop_type,
                "city": stop.city,
                "state": stop.state,
                "street": stop.street,
                "number": stop.number,
                "scheduled_date": stop.scheduled_date.isoformat() if stop.scheduled_date else None,
                "window_start": stop.window_start.strftime("%H:%M") if stop.window_start else None,
                "window_end": stop.window_end.strftime("%H:%M") if stop.window_end else None,
            })
            
    origin = stops[0] if stops else None
    destination = stops[-1] if len(stops) > 1 else None
    
    cargo_data = None
    if op.selection.offer and op.selection.offer.freight_request and hasattr(op.selection.offer.freight_request, 'cargo'):
        cargo = op.selection.offer.freight_request.cargo
        cargo_data = {
            "description": cargo.description,
            "cargo_type": cargo.cargo_type,
            "cargo_profile": cargo.cargo_profile,
            "weight_kg": float(cargo.weight_kg) if cargo.weight_kg else None,
            "volume_m3": float(cargo.volume_m3) if cargo.volume_m3 else None,
            "temperature_control": {
                "min_c": float(cargo.temperature_min_c) if cargo.temperature_min_c else None,
                "max_c": float(cargo.temperature_max_c) if cargo.temperature_max_c else None,
                "target_c": float(cargo.target_temperature_c) if cargo.target_temperature_c else None,
            }
        }
        
    active_session = op.tracking_sessions.filter(status=TrackingSessionStatus.ACTIVE.value).first()
    tracking_data = {
        "has_active_session": active_session is not None,
        "active_session_id": str(active_session.id) if active_session else None,
    }
    
    has_pod = ProofOfDelivery.objects.filter(operation=op).exists()
    pod_data = {
        "status": "SUBMITTED" if has_pod else "PENDING"
    }

    # Timeline ordered deterministicamente por: occurred_at, recorded_at, id
    timeline_events = op.events.all().select_related("actor").order_by("occurred_at", "received_at", "id")
    timeline = []
    for event in timeline_events:
        timeline.append({
            "id": str(event.id),
            "event_type": event.event_type,
            "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
            "recorded_at": event.received_at.isoformat() if event.received_at else None,
            "actor": {
                "id": str(event.actor.id),
                "username": event.actor.username,
            } if event.actor else None,
            "source": event.origin,
            "metadata": event.metadata,
        })

    # SLA Service computation
    sla_res = SLAService.compute(op)
    if sla_res.planned_deadline is not None:
        service_level = {
            "state": sla_res.state.value,
            "planned_deadline": sla_res.planned_deadline.isoformat(),
            "computed_delay_minutes": sla_res.computed_delay_minutes,
        }
    else:
        service_level = None

    # Thermal summary
    readings = list(op.thermal_readings.all())
    if readings:
        readings.sort(key=lambda r: r.sensor_timestamp, reverse=True)
        latest_reading = readings[0]
        within_range = None
        if cargo_data and cargo_data.get("temperature_control"):
            min_c = cargo_data["temperature_control"]["min_c"]
            max_c = cargo_data["temperature_control"]["max_c"]
            temp = float(latest_reading.temperature_c)
            if min_c is not None and max_c is not None:
                within_range = (min_c <= temp <= max_c)
            elif min_c is not None:
                within_range = (temp >= min_c)
            elif max_c is not None:
                within_range = (temp <= max_c)

        active_ex = next((ex for ex in op.thermal_excursions.all() if ex.status == ThermalExcursionStatus.ACTIVE.value), None)

        thermal_summary = {
            "latest_temperature_c": float(latest_reading.temperature_c),
            "latest_sensor_timestamp": latest_reading.sensor_timestamp.isoformat(),
            "validity": latest_reading.is_valid,
            "quality": (latest_reading.metadata.get("quality") if latest_reading.metadata else None) or latest_reading.quality,
            "within_range": within_range,
            "active_excursion": active_ex is not None,
            "active_excursion_direction": active_ex.direction if active_ex else None,
            "excursion_started_at": active_ex.started_at.isoformat() if active_ex else None,
        }
    else:
        thermal_summary = None
    
    return JsonResponse({
        "id": str(op.id),
        "status": op.status,
        "reference_code": op.selection.offer.reference_code if op.selection.offer else None,
        "carrier": {
            "id": str(op.carrier.id),
            "trade_name": op.carrier.trade_name,
        },
        "driver": {
            "id": str(op.driver.id),
            "full_name": op.driver.full_name,
        },
        "vehicle": {
            "id": str(op.vehicle.id) if op.vehicle else None,
            "plate": op.vehicle.plate if op.vehicle else None,
        },
        "origin": origin,
        "destination": destination,
        "stops": stops,
        "cargo": cargo_data,
        "tracking": tracking_data,
        "pod": pod_data,
        "load_type": op.load_type,
        "eta": op.eta.isoformat() if op.eta else None,
        "delay_minutes": op.delay_minutes,
        "service_level": service_level,
        "timeline": timeline,
        "thermal_summary": thermal_summary,
    }, status=200)


@csrf_exempt
@mobile_auth_required
def advance_operation_status_view(request, uuid):
    if request.method != "POST":
        return error_response("method_not_allowed", "Apenas método POST é suportado.", 405)
        
    body = parse_json_body(request)
    if body is None:
        return error_response("bad_request", "Corpo da requisição deve ser um JSON válido.", 400)
        
    next_status_str = body.get("next_status")
    client_event_id = body.get("client_event_id")
    
    if not next_status_str:
        return error_response("bad_request", "O campo 'next_status' é obrigatório.", 400)
        
    driver = request.driver
    try:
        op = FreightOperation.objects.get(id=uuid, driver=driver)
    except (FreightOperation.DoesNotExist, ValidationError):
        return error_response("not_found", "Operação não encontrada.", 404)
        
    try:
        next_status = OperationStatus(next_status_str)
    except ValueError:
        return error_response("bad_request", f"Status '{next_status_str}' inválido.", 400)
        
    try:
        updated_op = change_operation_status(
            operation_id=op.id,
            new_status=next_status,
            actor=request.user,
            client_event_id=client_event_id,
            driver_only=True
        )
    except ValidationError as e:
        message = str(e.message_dict) if hasattr(e, "message_dict") else str(e)
        return error_response("conflict", f"Conflito de transição: {message}", 409)
        
    return JsonResponse({
        "id": str(updated_op.id),
        "status": updated_op.status,
    }, status=200)


@csrf_exempt
@mobile_auth_required
def report_incident_view(request, uuid):
    if request.method != "POST":
        return error_response("method_not_allowed", "Apenas método POST é suportado.", 405)
        
    body = parse_json_body(request)
    if body is None:
        return error_response("bad_request", "Corpo da requisição deve ser um JSON válido.", 400)
        
    description = body.get("description")
    client_event_id = body.get("client_event_id")
    
    if not description:
        return error_response("bad_request", "O campo 'description' é obrigatório.", 400)
        
    driver = request.driver
    try:
        op = FreightOperation.objects.get(id=uuid, driver=driver)
    except (FreightOperation.DoesNotExist, ValidationError):
        return error_response("not_found", "Operação não encontrada.", 404)
        
    try:
        event = report_operation_incident(
            operation_id=op.id,
            description=description,
            actor=request.user,
            client_event_id=client_event_id,
            driver_only=True
        )
    except ValidationError as e:
        return error_response("conflict", f"Conflito ao registrar incidente: {e}", 409)
        
    return JsonResponse({
        "id": str(event.id),
        "event_type": event.event_type,
        "occurred_at": event.created_at.isoformat() if hasattr(event, "created_at") else None,
    }, status=201)


@csrf_exempt
@mobile_auth_required
def record_pod_view(request, uuid):
    if request.method != "POST":
        return error_response("method_not_allowed", "Apenas método POST é suportado.", 405)
        
    body = parse_json_body(request)
    if body is None:
        return error_response("bad_request", "Corpo da requisição deve ser um JSON válido.", 400)
        
    receiver_name = body.get("receiver_name")
    delivered_at_str = body.get("delivered_at")
    latitude = body.get("latitude")
    longitude = body.get("longitude")
    notes = body.get("notes", "")
    
    if not receiver_name or not delivered_at_str:
        return error_response("bad_request", "Parâmetros 'receiver_name' e 'delivered_at' são obrigatórios.", 400)
        
    try:
        delivered_at = timezone.datetime.fromisoformat(delivered_at_str)
    except ValueError:
        return error_response("bad_request", "Formato de 'delivered_at' inválido (deve ser ISO 8601).", 400)
        
    driver = request.driver
    try:
        op = FreightOperation.objects.get(id=uuid, driver=driver)
    except (FreightOperation.DoesNotExist, ValidationError):
        return error_response("not_found", "Operação não encontrada.", 404)
        
    try:
        pod = record_proof_of_delivery(
            operation_id=op.id,
            receiver_name=receiver_name,
            delivered_at=delivered_at,
            latitude=float(latitude) if latitude is not None else None,
            longitude=float(longitude) if longitude is not None else None,
            notes=notes,
            actor=request.user,
            driver_only=True
        )
    except ValidationError as e:
        message = str(e.message_dict) if hasattr(e, "message_dict") else str(e)
        return error_response("conflict", f"Conflito ao registrar POD: {message}", 409)
        
    return JsonResponse({
        "id": str(pod.id),
        "status": "SUBMITTED",
        "receiver_name": pod.receiver_name,
        "delivered_at": pod.delivered_at.isoformat() if pod.delivered_at else None,
    }, status=201)


@csrf_exempt
@mobile_auth_required
def start_tracking_view(request, uuid):
    if request.method != "POST":
        return error_response("method_not_allowed", "Apenas método POST é suportado.", 405)
        
    body = parse_json_body(request) or {}
    source = body.get("source", "mobile")
    device_metadata = body.get("device_metadata", {})
    client_event_id = body.get("client_event_id")
    
    driver = request.driver
    try:
        op = FreightOperation.objects.get(id=uuid, driver=driver)
    except (FreightOperation.DoesNotExist, ValidationError):
        return error_response("not_found", "Operação não encontrada.", 404)
        
    try:
        session = start_tracking_session(
            actor=request.user,
            operation_id=op.id,
            source=source,
            device_metadata=device_metadata,
            client_event_id=client_event_id
        )
    except ValidationError as e:
        message = str(e.message_dict) if hasattr(e, "message_dict") else str(e)
        return error_response("conflict", f"Conflito ao iniciar tracking: {message}", 409)
    except PermissionDenied as e:
        return error_response("forbidden", str(e), 403)
        
    return JsonResponse({
        "tracking_session_id": str(session.id),
        "status": session.status,
        "started_at": session.started_at.isoformat(),
    }, status=201)


@csrf_exempt
@mobile_auth_required
def record_location_view(request, session_uuid):
    if request.method != "POST":
        return error_response("method_not_allowed", "Apenas método POST é suportado.", 405)
        
    body = parse_json_body(request)
    if body is None:
        return error_response("bad_request", "Corpo da requisição deve ser um JSON válido.", 400)
        
    latitude = body.get("latitude")
    longitude = body.get("longitude")
    accuracy_m = body.get("accuracy_m")
    speed_kph = body.get("speed_kph")
    heading_deg = body.get("heading_deg")
    altitude_m = body.get("altitude_m")
    recorded_at_str = body.get("recorded_at")
    sequence = body.get("sequence")
    client_event_id = body.get("client_event_id")
    metadata = body.get("metadata", {})
    
    if latitude is None or longitude is None or accuracy_m is None:
        return error_response("bad_request", "Parâmetros 'latitude', 'longitude' e 'accuracy_m' são obrigatórios.", 400)
        
    recorded_at = None
    if recorded_at_str:
        try:
            recorded_at = timezone.datetime.fromisoformat(recorded_at_str)
            if recorded_at > timezone.now() + timezone.timedelta(minutes=15):
                return error_response("bad_request", "recorded_at não pode ser no futuro.", 400)
        except ValueError:
            return error_response("bad_request", "Formato de 'recorded_at' inválido (deve ser ISO 8601).", 400)
            
    driver = request.driver
    try:
        session = TrackingSession.objects.get(id=session_uuid, driver=driver)
    except (TrackingSession.DoesNotExist, ValidationError):
        return error_response("not_found", "Sessão de rastreamento não encontrada.", 404)
        
    try:
        point = record_location_point(
            actor=request.user,
            tracking_session_id=session.id,
            latitude=latitude,
            longitude=longitude,
            accuracy_m=accuracy_m,
            speed_kph=speed_kph,
            heading_deg=heading_deg,
            altitude_m=altitude_m,
            recorded_at=recorded_at,
            sequence=sequence,
            client_event_id=client_event_id,
            metadata=metadata
        )
    except ValidationError as e:
        message = str(e.message_dict) if hasattr(e, "message_dict") else str(e)
        return error_response("conflict", f"Erro de validação ou conflito: {message}", 409)
    except PermissionDenied as e:
        return error_response("forbidden", str(e), 403)
        
    return JsonResponse({
        "id": str(point.id),
        "sequence": point.sequence,
        "recorded_at": point.recorded_at.isoformat(),
        "received_at": point.received_at.isoformat(),
    }, status=201)


@csrf_exempt
@mobile_auth_required
def record_location_batch_view(request, session_uuid):
    if request.method != "POST":
        return error_response("method_not_allowed", "Apenas método POST é suportado.", 405)
        
    body = parse_json_body(request)
    if body is None or not isinstance(body, list):
        return error_response("bad_request", "Corpo da requisição deve ser uma lista JSON válida.", 400)
        
    if len(body) > 100:
        return error_response("bad_request", "Tamanho do lote excede o limite máximo de 100 pontos.", 400)
        
    driver = request.driver
    try:
        session = TrackingSession.objects.get(id=session_uuid, driver=driver)
    except (TrackingSession.DoesNotExist, ValidationError):
        return error_response("not_found", "Sessão de rastreamento não encontrada.", 404)
        
    results = []
    try:
        with transaction.atomic():
            for idx, pt in enumerate(body):
                latitude = pt.get("latitude")
                longitude = pt.get("longitude")
                accuracy_m = pt.get("accuracy_m")
                speed_kph = pt.get("speed_kph")
                heading_deg = pt.get("heading_deg")
                altitude_m = pt.get("altitude_m")
                recorded_at_str = pt.get("recorded_at")
                sequence = pt.get("sequence")
                client_event_id = pt.get("client_event_id")
                metadata = pt.get("metadata", {})
                
                if latitude is None or longitude is None or accuracy_m is None:
                    raise ValidationError(f"Ponto no índice {idx} com parâmetros obrigatórios ausentes.")
                    
                recorded_at = None
                if recorded_at_str:
                    try:
                        recorded_at = timezone.datetime.fromisoformat(recorded_at_str)
                        if recorded_at > timezone.now() + timezone.timedelta(minutes=15):
                            raise ValidationError(f"Ponto no índice {idx} com recorded_at no futuro.")
                    except ValueError:
                        raise ValidationError(f"Ponto no índice {idx} com recorded_at inválido.")
                        
                point = record_location_point(
                    actor=request.user,
                    tracking_session_id=session.id,
                    latitude=latitude,
                    longitude=longitude,
                    accuracy_m=accuracy_m,
                    speed_kph=speed_kph,
                    heading_deg=heading_deg,
                    altitude_m=altitude_m,
                    recorded_at=recorded_at,
                    sequence=sequence,
                    client_event_id=client_event_id,
                    metadata=metadata
                )
                results.append({
                    "id": str(point.id),
                    "sequence": point.sequence,
                    "client_event_id": point.client_event_id,
                })
    except ValidationError as e:
        message = str(e.message_dict) if hasattr(e, "message_dict") else str(e)
        return error_response("conflict", f"Erro no processamento do lote: {message}", 409)
    except PermissionDenied as e:
        return error_response("forbidden", str(e), 403)
        
    return JsonResponse({
        "success": True,
        "processed_count": len(results),
        "results": results
    }, status=201)


@csrf_exempt
@mobile_auth_required
def end_tracking_view(request, session_uuid):
    if request.method != "POST":
        return error_response("method_not_allowed", "Apenas método POST é suportado.", 405)
        
    driver = request.driver
    try:
        session = TrackingSession.objects.get(id=session_uuid, driver=driver)
    except (TrackingSession.DoesNotExist, ValidationError):
        return error_response("not_found", "Sessão de rastreamento não encontrada.", 404)
        
    try:
        session = end_tracking_session(
            actor=request.user,
            tracking_session_id=session.id
        )
    except ValidationError as e:
        message = str(e.message_dict) if hasattr(e, "message_dict") else str(e)
        return error_response("conflict", f"Conflito ao encerrar tracking: {message}", 409)
    except PermissionDenied as e:
        return error_response("forbidden", str(e), 403)
        
    return JsonResponse({
        "session_id": str(session.id),
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        "status": session.status,
    }, status=200)


@csrf_exempt
@mobile_auth_required
def record_thermal_reading_view(request, uuid):
    if request.method != "POST":
        return error_response("method_not_allowed", "Apenas método POST é suportado.", 405)
        
    body = parse_json_body(request)
    if body is None:
        return error_response("bad_request", "Corpo da requisição deve ser um JSON válido.", 400)
        
    sensor_id = body.get("sensor_id")
    sensor_timestamp_str = body.get("sensor_timestamp")
    temperature_c_val = body.get("temperature_c")
    quality = body.get("quality", "VALID")
    validity = body.get("validity", "VALID")
    client_event_id = body.get("client_event_id")
    metadata = body.get("metadata", {})
    
    if not sensor_id or not sensor_timestamp_str or temperature_c_val is None:
        return error_response("bad_request", "Parâmetros 'sensor_id', 'sensor_timestamp' e 'temperature_c' são obrigatórios.", 400)
        
    try:
        sensor_timestamp = timezone.datetime.fromisoformat(sensor_timestamp_str)
    except ValueError:
        return error_response("bad_request", "Formato de 'sensor_timestamp' inválido (deve ser ISO 8601).", 400)
        
    try:
        from decimal import Decimal
        temperature_c = Decimal(str(temperature_c_val))
    except (ValueError, TypeError):
        return error_response("bad_request", "Formato de 'temperature_c' inválido.", 400)
        
    driver = request.driver
    try:
        # Check permission (operation exists and belongs to the driver)
        op = FreightOperation.objects.get(id=uuid, driver=driver)
    except (FreightOperation.DoesNotExist, ValidationError):
        return error_response("not_found", "Operação não encontrada.", 404)
        
    try:
        reading, duplicate = record_thermal_reading(
            operation_id=op.id,
            device_id=sensor_id,
            sensor_timestamp=sensor_timestamp,
            temperature_c=temperature_c,
            quality=quality,
            validity=validity,
            client_event_id=client_event_id,
            metadata=metadata,
            actor=request.user,
            driver_only=True
        )
    except ValidationError as e:
        message = str(e.message_dict) if hasattr(e, "message_dict") else str(e)
        return error_response("conflict", f"Erro de validação: {message}", 409)
        
    # Check if within range
    within_range = None
    cargo_data = None
    if op.selection.offer and op.selection.offer.freight_request and hasattr(op.selection.offer.freight_request, 'cargo'):
        cargo = op.selection.offer.freight_request.cargo
        min_c = cargo.temperature_min_c
        max_c = cargo.temperature_max_c
        temp_val = float(reading.temperature_c)
        if min_c is not None and max_c is not None:
            within_range = (min_c <= temp_val <= max_c)
        elif min_c is not None:
            within_range = (temp_val >= min_c)
        elif max_c is not None:
            within_range = (temp_val <= max_c)
            
    # Check active excursion
    active_ex = ThermalExcursion.objects.filter(
        operation=op,
        sensor_id=sensor_id,
        status=ThermalExcursionStatus.ACTIVE.value
    ).first()
    
    active_excursion_data = None
    if active_ex:
        active_excursion_data = {
            "id": str(active_ex.id),
            "direction": active_ex.direction,
            "started_at": active_ex.started_at.isoformat(),
            "min_observed": float(active_ex.min_observed),
            "max_observed": float(active_ex.max_observed),
        }

    return JsonResponse({
        "reading_id": str(reading.id),
        "created": not duplicate,
        "duplicate": duplicate,
        "temperature_c": float(reading.temperature_c),
        "validity": reading.validity,
        "within_range": within_range,
        "active_excursion": active_excursion_data,
    }, status=201 if not duplicate else 200)
