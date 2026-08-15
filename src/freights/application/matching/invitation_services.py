from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from src.audit.infrastructure.django.services import record_audit_event
from src.freights.application.matching.events import record_marketplace_event
from src.freights.domain.matching_enums import (
    FreightOfferInvitationStatus,
    MarketplaceEventType,
    MatchEligibilityStatus,
)
from src.freights.infrastructure.django.models import (
    FreightMatchCandidate,
    FreightOfferInvitation,
)
from src.identity.domain.enums import PermissionCode
from src.shared.interfaces.backoffice.authorization import user_has_backoffice_permission


def _ensure_can_invite(actor) -> None:
    if not user_has_backoffice_permission(actor, PermissionCode.FREIGHT_MATCHING_INVITE):
        raise ValidationError({"permission": "Sem permissão para convidar candidatos."})


@transaction.atomic
def invite_match_candidate(
    *,
    candidate: FreightMatchCandidate,
    actor,
    expires_at=None,
) -> FreightOfferInvitation:
    _ensure_can_invite(actor)
    if candidate.eligibility_status != MatchEligibilityStatus.ELIGIBLE.value:
        raise ValidationError({"candidate": "Somente candidatos elegíveis podem ser convidados."})

    invite_carrier = candidate.carrier if candidate.carrier_id and not candidate.driver_id else None
    invite_driver = candidate.driver if candidate.driver_id else None
    if candidate.driver_id:
        invite_carrier = None
        invite_driver = candidate.driver
    elif candidate.carrier_id:
        invite_carrier = candidate.carrier
        invite_driver = None
    else:
        raise ValidationError({"candidate": "Candidato sem entidade convidável."})

    entity_filter = {"carrier": invite_carrier, "driver": invite_driver}

    existing = FreightOfferInvitation.objects.filter(
        offer=candidate.offer,
        status__in=[
            FreightOfferInvitationStatus.PENDING.value,
            FreightOfferInvitationStatus.SENT.value,
            FreightOfferInvitationStatus.VIEWED.value,
        ],
        **entity_filter,
    ).exists()
    if existing:
        raise ValidationError({"invitation": "Já existe convite ativo para esta entidade."})

    invitation = FreightOfferInvitation.objects.create(
        offer=candidate.offer,
        organization=candidate.organization,
        match_candidate=candidate,
        carrier=invite_carrier,
        driver=invite_driver,
        status=FreightOfferInvitationStatus.SENT.value,
        sent_at=timezone.now(),
        expires_at=expires_at or candidate.offer.expires_at,
        created_by=actor,
    )
    record_audit_event(
        action="freight_candidate_invited",
        actor=actor,
        organization=candidate.organization,
        target=candidate.offer,
        metadata={
            "candidate_id": str(candidate.id),
            "invitation_id": str(invitation.id),
            "rank_position": candidate.rank_position,
            "total_score": str(candidate.total_score) if candidate.total_score else "",
        },
    )
    record_marketplace_event(
        offer=candidate.offer,
        event_type=MarketplaceEventType.OFFER_INVITED,
        actor=actor,
        carrier=candidate.carrier,
        driver=candidate.driver,
        metadata={"invitation_id": str(invitation.id), "candidate_id": str(candidate.id)},
    )
    return invitation


@transaction.atomic
def cancel_freight_offer_invitation(*, invitation: FreightOfferInvitation, actor) -> FreightOfferInvitation:
    _ensure_can_invite(actor)
    if invitation.status in {
        FreightOfferInvitationStatus.CANCELLED.value,
        FreightOfferInvitationStatus.EXPIRED.value,
        FreightOfferInvitationStatus.DECLINED.value,
    }:
        raise ValidationError({"status": "Convite não pode ser cancelado neste estado."})
    invitation.status = FreightOfferInvitationStatus.CANCELLED.value
    invitation.cancelled_by = actor
    invitation.cancelled_at = timezone.now()
    invitation.save(update_fields=["status", "cancelled_by", "cancelled_at", "updated_at"])
    record_audit_event(
        action="freight_invitation_cancelled",
        actor=actor,
        organization=invitation.organization,
        target=invitation.offer,
        metadata={"invitation_id": str(invitation.id)},
    )
    return invitation
