from __future__ import annotations

from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models as django_models
from django.db.models import Count, Prefetch, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.dateparse import parse_date
from django.views.generic import DetailView, TemplateView, View

from src.audit.infrastructure.django.models import AuditLog
from src.carriers.infrastructure.django.models import CarrierProfile
from src.drivers.infrastructure.django.models import Driver
from src.freights.application.matching.constants import MATCHING_ALGORITHM_VERSION
from src.freights.application.matching.invitation_services import invite_match_candidate
from src.freights.application.matching.services import (
    generate_match_candidates_for_offer,
    get_current_match_candidates,
)
from src.freights.application.offer_services import (
    FreightOfferData,
    add_freight_offer_target,
    cancel_freight_offer,
    create_freight_offer,
    get_offer_with_expiration_applied,
    mark_freight_offer_ready,
    pause_freight_offer,
    publish_freight_offer,
    remove_freight_offer_target,
    resume_freight_offer,
    update_freight_offer_draft,
)
from src.freights.domain.enums import FreightCargoProfile, FreightRequestStatus
from src.freights.domain.offer_enums import FreightOfferAudience, FreightOfferStatus
from src.freights.domain.offer_state_machine import QUOTE_STATUSES_ELIGIBLE_FOR_OFFER
from src.freights.infrastructure.django.models import (
    FreightOfferInterest,
    FreightOfferInvitation,
    FreightOfferSelection,
    FreightOfferTarget,
    FreightQuote,
)
from src.identity.domain.enums import PermissionCode

from .authorization import (
    scoped_carrier_queryset,
    scoped_driver_queryset,
    scoped_freight_match_candidate_queryset,
    scoped_freight_offer_queryset,
    scoped_freight_quote_queryset,
    scoped_freight_request_queryset,
    scoped_user_queryset,
    user_has_backoffice_permission,
)
from .views import BackofficeContextMixin, BackofficePermissionMixin, FilteredListView

User = get_user_model()

OFFER_STATUS_LABELS = {
    FreightOfferStatus.DRAFT.value: "Rascunho",
    FreightOfferStatus.READY.value: "Pronta",
    FreightOfferStatus.PUBLISHED.value: "Publicada",
    FreightOfferStatus.PAUSED.value: "Pausada",
    FreightOfferStatus.EXPIRED.value: "Expirada",
    FreightOfferStatus.CANCELLED.value: "Cancelada",
    FreightOfferStatus.CLOSED.value: "Encerrada",
}

AUDIENCE_LABELS = {
    FreightOfferAudience.CARRIERS.value: "Transportadoras",
    FreightOfferAudience.DRIVERS.value: "Motoristas",
    FreightOfferAudience.BOTH.value: "Transportadoras e motoristas",
    FreightOfferAudience.PRIVATE.value: "Privada",
}


def user_can_view_offer_margin(user) -> bool:
    return user_has_backoffice_permission(user, PermissionCode.FREIGHT_OFFERS_VIEW_MARGIN)


def _offer_queryset(user):
    return (
        scoped_freight_offer_queryset(user, PermissionCode.FREIGHT_OFFERS_VIEW)
        .select_related(
            "freight_request",
            "freight_request__customer",
            "freight_quote",
            "organization",
            "owner",
            "created_by",
        )
        .prefetch_related(
            Prefetch(
                "targets", queryset=FreightOfferTarget.objects.select_related("carrier", "driver")
            )
        )
    )


class FreightOfferForm(forms.Form):
    freight_quote = forms.ModelChoiceField(
        queryset=FreightQuote.objects.none(),
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    offer_amount = forms.DecimalField(
        min_value=Decimal("0"),
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
    )
    audience = forms.ChoiceField(
        choices=[(item.value, AUDIENCE_LABELS[item.value]) for item in FreightOfferAudience],
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    expires_at = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"class": "form-control", "type": "datetime-local"}),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"],
    )
    internal_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    )
    owner = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    def __init__(self, *args, user=None, freight_request=None, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user and freight_request:
            self.fields["freight_quote"].queryset = (
                scoped_freight_quote_queryset(user, PermissionCode.FREIGHT_QUOTES_VIEW)
                .filter(
                    freight_request=freight_request,
                    status__in=QUOTE_STATUSES_ELIGIBLE_FOR_OFFER,
                )
                .order_by("-version")
            )
        if user:
            self.fields["owner"].queryset = scoped_user_queryset(
                user, PermissionCode.USERS_VIEW
            ).order_by("email")
        if instance:
            self.fields["freight_quote"].initial = instance.freight_quote_id
            self.fields["offer_amount"].initial = instance.offer_amount
            self.fields["audience"].initial = instance.audience
            self.fields["expires_at"].initial = instance.expires_at
            self.fields["internal_notes"].initial = instance.internal_notes
            self.fields["owner"].initial = instance.owner_id


class FreightOfferTargetForm(forms.Form):
    carrier = forms.ModelChoiceField(
        queryset=CarrierProfile.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    driver = forms.ModelChoiceField(
        queryset=Driver.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    def __init__(self, *args, user=None, offer=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user and offer:
            self.fields["carrier"].queryset = scoped_carrier_queryset(
                user, PermissionCode.CARRIERS_VIEW
            ).filter(tenant=offer.organization)
            self.fields["driver"].queryset = scoped_driver_queryset(
                user, PermissionCode.DRIVERS_VIEW
            ).filter(organization=offer.organization)


class FreightOfferListView(FilteredListView):
    template_name = "backoffice/pages/freight_offers/list.html"
    context_object_name = "freight_offers"
    permission_code = PermissionCode.FREIGHT_OFFERS_VIEW
    active_menu = "freight_offers"
    page_title = "Ofertas de Frete"
    breadcrumbs = (
        ("Dashboard", reverse_lazy("backoffice:dashboard")),
        ("Ofertas de Frete", None),
    )

    def get_queryset(self):
        queryset = _offer_queryset(self.request.user)
        query = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        audience = self.request.GET.get("audience", "").strip()
        cargo_profile = self.request.GET.get("cargo_profile", "").strip()
        customer_id = self.request.GET.get("customer", "").strip()
        origin_state = self.request.GET.get("origin_state", "").strip()
        destination_state = self.request.GET.get("destination_state", "").strip()
        owner_id = self.request.GET.get("owner", "").strip()
        expires_before = parse_date(self.request.GET.get("expires_before", "").strip() or "")

        if query:
            queryset = queryset.filter(
                django_models.Q(reference_code__icontains=query)
                | django_models.Q(freight_request__reference_code__icontains=query)
                | django_models.Q(freight_request__customer__legal_name__icontains=query)
                | django_models.Q(premises_snapshot__pickup__city__icontains=query)
                | django_models.Q(premises_snapshot__delivery__city__icontains=query)
            )
        if status:
            queryset = queryset.filter(status=status)
        if audience:
            queryset = queryset.filter(audience=audience)
        if cargo_profile:
            queryset = queryset.filter(premises_snapshot__cargo_profile=cargo_profile)
        if customer_id:
            queryset = queryset.filter(freight_request__customer_id=customer_id)
        if origin_state:
            queryset = queryset.filter(premises_snapshot__pickup__state=origin_state)
        if destination_state:
            queryset = queryset.filter(premises_snapshot__delivery__state=destination_state)
        if owner_id:
            queryset = queryset.filter(owner_id=owner_id)
        if expires_before:
            queryset = queryset.filter(expires_at__date__lte=expires_before)
        return queryset.order_by("-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        base_qs = scoped_freight_offer_queryset(
            self.request.user, PermissionCode.FREIGHT_OFFERS_VIEW
        )
        stats = base_qs.aggregate(
            total=Count("id"),
            drafts=Count("id", filter=Q(status=FreightOfferStatus.DRAFT.value)),
            ready=Count("id", filter=Q(status=FreightOfferStatus.READY.value)),
            published=Count("id", filter=Q(status=FreightOfferStatus.PUBLISHED.value)),
            paused=Count("id", filter=Q(status=FreightOfferStatus.PAUSED.value)),
            expired=Count("id", filter=Q(status=FreightOfferStatus.EXPIRED.value)),
            cancelled=Count("id", filter=Q(status=FreightOfferStatus.CANCELLED.value)),
            refrigerated=Count(
                "id",
                filter=Q(
                    premises_snapshot__cargo_profile=FreightCargoProfile.REFRIGERATED_CARGO.value
                ),
            ),
        )
        context["kpis"] = stats
        context["can_view_margin"] = user_can_view_offer_margin(self.request.user)
        if context["can_view_margin"]:
            context["offered_total"] = base_qs.aggregate(total=Sum("offer_amount"))["total"] or 0
        context["status_labels"] = OFFER_STATUS_LABELS
        context["audience_labels"] = AUDIENCE_LABELS
        context["statuses"] = [status.value for status in FreightOfferStatus]
        context["audiences"] = [audience.value for audience in FreightOfferAudience]
        context["owners"] = scoped_user_queryset(
            self.request.user, PermissionCode.USERS_VIEW
        ).order_by("email")
        return context


class FreightOfferDetailView(BackofficePermissionMixin, BackofficeContextMixin, DetailView):
    template_name = "backoffice/pages/freight_offers/detail.html"
    context_object_name = "offer"
    permission_code = PermissionCode.FREIGHT_OFFERS_VIEW
    active_menu = "freight_offers"
    page_title = "Detalhe da Oferta"

    def get_queryset(self):
        return _offer_queryset(self.request.user)

    def get_object(self, queryset=None):
        offer = super().get_object(queryset)
        return get_offer_with_expiration_applied(offer, actor=self.request.user)

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Ofertas de Frete", reverse_lazy("backoffice:freight_offers")),
            (self.object.reference_code, None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        offer = self.object
        context["status_labels"] = OFFER_STATUS_LABELS
        context["audience_labels"] = AUDIENCE_LABELS
        context["can_view_margin"] = user_can_view_offer_margin(self.request.user)
        context["can_edit"] = (
            offer.status == FreightOfferStatus.DRAFT.value
            and user_has_backoffice_permission(
                self.request.user, PermissionCode.FREIGHT_OFFERS_UPDATE
            )
        )
        context["can_ready"] = (
            offer.status == FreightOfferStatus.DRAFT.value
            and user_has_backoffice_permission(
                self.request.user, PermissionCode.FREIGHT_OFFERS_UPDATE
            )
        )
        context["can_publish"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_OFFERS_PUBLISH
        )
        context["can_pause"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_OFFERS_PAUSE
        )
        context["can_cancel"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_OFFERS_CANCEL
        )
        context["can_manage_targets"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_OFFERS_MANAGE_TARGETS
        )
        context["target_form"] = FreightOfferTargetForm(user=self.request.user, offer=offer)
        context["audit_logs"] = AuditLog.objects.filter(target_id=str(offer.id)).select_related(
            "actor", "organization"
        )[:12]
        generation = offer.match_generations.filter(is_current=True).first()
        candidates = get_current_match_candidates(offer) if generation else []
        candidate_list = list(candidates[:100])
        context["match_generation"] = generation
        context["match_candidates"] = candidate_list
        context["matching_summary"] = {
            "total": generation.candidate_count if generation else 0,
            "eligible": generation.eligible_count if generation else 0,
            "ineligible": generation.ineligible_count if generation else 0,
            "invited": offer.invitations.exclude(
                status__in=["CANCELLED", "EXPIRED", "DECLINED"]
            ).count(),
            "algorithm_version": generation.algorithm_version
            if generation
            else MATCHING_ALGORITHM_VERSION,
            "generated_at": generation.created_at if generation else None,
        }
        context["can_view_matching"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_MATCHING_VIEW
        )
        context["can_generate_matching"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_MATCHING_GENERATE
        )
        context["can_invite_matching"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_MATCHING_INVITE
        )
        context["can_view_matching_explanation"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_MATCHING_VIEW_EXPLANATION
        )
        context["matching_ready"] = offer.status in {
            FreightOfferStatus.PUBLISHED.value,
            FreightOfferStatus.PAUSED.value,
        }

        # Marketplace Interest & Selection context
        from src.freights.application.marketplace_services import (
            apply_selection_expiration_if_needed,
        )

        active_selection = offer.selections.filter(
            status__in=["PENDING_CONFIRMATION", "CONFIRMED"]
        ).first()
        if active_selection:
            active_selection = apply_selection_expiration_if_needed(active_selection)
            if active_selection.status not in ["PENDING_CONFIRMATION", "CONFIRMED"]:
                active_selection = None

        context["active_selection"] = active_selection
        context["interests"] = offer.interests.select_related(
            "carrier", "driver", "vehicle", "match_candidate"
        ).order_by("-expressed_at")

        context["can_view_interests"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_MARKETPLACE_INTEREST_VIEW
        )
        context["can_view_selection"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_MARKETPLACE_SELECTION_VIEW
        )
        context["can_select"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_MARKETPLACE_SELECT
        )
        context["can_cancel_selection"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_MARKETPLACE_CANCEL_SELECTION
        )
        return context


class FreightOfferCreateView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/freight_offers/form.html"
    permission_code = PermissionCode.FREIGHT_OFFERS_CREATE
    active_menu = "freight_offers"
    page_title = "Nova Oferta de Frete"

    def get_freight_request(self):
        return get_object_or_404(
            scoped_freight_request_queryset(
                self.request.user, PermissionCode.FREIGHT_REQUESTS_VIEW
            ).select_related("customer", "organization", "cargo"),
            pk=self.kwargs["request_pk"],
        )

    def get_breadcrumbs(self):
        freight_request = self.get_freight_request()
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Solicitações de Transporte", reverse_lazy("backoffice:freight_requests")),
            (
                freight_request.reference_code,
                reverse_lazy("backoffice:freight_request_detail", args=[freight_request.id]),
            ),
            ("Nova Oferta", None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        freight_request = self.get_freight_request()
        context["freight_request"] = freight_request
        context["can_create_offer"] = (
            freight_request.status == FreightRequestStatus.READY_TO_PUBLISH.value
        )
        if "form" not in context:
            context["form"] = FreightOfferForm(
                user=self.request.user,
                freight_request=freight_request,
            )
        return context

    def post(self, request, *args, **kwargs):
        freight_request = self.get_freight_request()
        if freight_request.status != FreightRequestStatus.READY_TO_PUBLISH.value:
            raise PermissionDenied
        form = FreightOfferForm(request.POST, user=request.user, freight_request=freight_request)
        if form.is_valid():
            try:
                offer = create_freight_offer(
                    data=FreightOfferData(
                        freight_request=freight_request,
                        freight_quote=form.cleaned_data["freight_quote"],
                        created_by=request.user,
                        owner=form.cleaned_data.get("owner") or request.user,
                        offer_amount=form.cleaned_data["offer_amount"],
                        audience=FreightOfferAudience(form.cleaned_data["audience"]),
                        expires_at=form.cleaned_data.get("expires_at"),
                        internal_notes=form.cleaned_data.get("internal_notes", ""),
                    ),
                    actor=request.user,
                )
                return redirect("backoffice:freight_offer_detail", pk=offer.pk)
            except ValidationError as exc:
                form.add_error(None, exc)
        return render(request, self.template_name, self.get_context_data(form=form))


class FreightOfferUpdateView(FreightOfferCreateView):
    permission_code = PermissionCode.FREIGHT_OFFERS_UPDATE
    page_title = "Editar Oferta"

    def get_offer(self):
        return get_object_or_404(_offer_queryset(self.request.user), pk=self.kwargs["pk"])

    def get_freight_request(self):
        return self.get_offer().freight_request

    def dispatch(self, request, *args, **kwargs):
        offer = get_object_or_404(_offer_queryset(request.user), pk=kwargs["pk"])
        if offer.status != FreightOfferStatus.DRAFT.value:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        offer = self.get_offer()
        context["offer"] = offer
        context["is_edit"] = True
        if "form" not in context:
            context["form"] = FreightOfferForm(
                user=self.request.user,
                freight_request=offer.freight_request,
                instance=offer,
            )
        return context

    def post(self, request, *args, **kwargs):
        offer = self.get_offer()
        form = FreightOfferForm(
            request.POST,
            user=request.user,
            freight_request=offer.freight_request,
            instance=offer,
        )
        if form.is_valid():
            try:
                update_freight_offer_draft(
                    offer,
                    actor=request.user,
                    offer_amount=form.cleaned_data["offer_amount"],
                    audience=FreightOfferAudience(form.cleaned_data["audience"]),
                    expires_at=form.cleaned_data.get("expires_at"),
                    internal_notes=form.cleaned_data.get("internal_notes", ""),
                    owner=form.cleaned_data.get("owner"),
                )
                return redirect("backoffice:freight_offer_detail", pk=offer.pk)
            except ValidationError as exc:
                form.add_error(None, exc)
        return render(request, self.template_name, self.get_context_data(form=form))


class FreightOfferReadyView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_OFFERS_UPDATE
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        offer = get_object_or_404(_offer_queryset(request.user), pk=kwargs["pk"])
        try:
            mark_freight_offer_ready(offer, actor=request.user)
        except ValidationError:
            pass
        return redirect("backoffice:freight_offer_detail", pk=offer.pk)


class FreightOfferPublishView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_OFFERS_PUBLISH
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        offer = get_object_or_404(_offer_queryset(request.user), pk=kwargs["pk"])
        try:
            publish_freight_offer(offer, actor=request.user)
        except ValidationError:
            pass
        return redirect("backoffice:freight_offer_detail", pk=offer.pk)


class FreightOfferPauseView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_OFFERS_PAUSE
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        offer = get_object_or_404(_offer_queryset(request.user), pk=kwargs["pk"])
        try:
            pause_freight_offer(offer, actor=request.user)
        except ValidationError:
            pass
        return redirect("backoffice:freight_offer_detail", pk=offer.pk)


class FreightOfferResumeView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_OFFERS_PAUSE
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        offer = get_object_or_404(_offer_queryset(request.user), pk=kwargs["pk"])
        try:
            resume_freight_offer(offer, actor=request.user)
        except ValidationError:
            pass
        return redirect("backoffice:freight_offer_detail", pk=offer.pk)


class FreightOfferCancelView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_OFFERS_CANCEL
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        offer = get_object_or_404(_offer_queryset(request.user), pk=kwargs["pk"])
        try:
            cancel_freight_offer(
                offer,
                reason=request.POST.get("cancellation_reason", ""),
                actor=request.user,
            )
        except ValidationError:
            pass
        return redirect("backoffice:freight_offer_detail", pk=offer.pk)


class FreightOfferAddTargetView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_OFFERS_MANAGE_TARGETS
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        offer = get_object_or_404(_offer_queryset(request.user), pk=kwargs["pk"])
        form = FreightOfferTargetForm(request.POST, user=request.user, offer=offer)
        if form.is_valid():
            try:
                add_freight_offer_target(
                    offer,
                    carrier=form.cleaned_data.get("carrier"),
                    driver=form.cleaned_data.get("driver"),
                    actor=request.user,
                )
            except ValidationError:
                pass
        return redirect("backoffice:freight_offer_detail", pk=offer.pk)


class FreightOfferRemoveTargetView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_OFFERS_MANAGE_TARGETS
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        offer = get_object_or_404(_offer_queryset(request.user), pk=kwargs["pk"])
        target = get_object_or_404(FreightOfferTarget, pk=kwargs["target_pk"], offer=offer)
        try:
            remove_freight_offer_target(target, actor=request.user)
        except ValidationError:
            pass
        return redirect("backoffice:freight_offer_detail", pk=offer.pk)


class FreightOfferMatchingGenerateView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_MATCHING_GENERATE
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        offer = get_object_or_404(_offer_queryset(request.user), pk=kwargs["pk"])
        try:
            generate_match_candidates_for_offer(offer, actor=request.user, regenerate=False)
        except ValidationError:
            pass
        return redirect("backoffice:freight_offer_detail", pk=offer.pk)


class FreightOfferMatchingRegenerateView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_MATCHING_GENERATE
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        offer = get_object_or_404(_offer_queryset(request.user), pk=kwargs["pk"])
        try:
            generate_match_candidates_for_offer(offer, actor=request.user, regenerate=True)
        except ValidationError:
            pass
        return redirect("backoffice:freight_offer_detail", pk=offer.pk)


class FreightOfferMatchingInviteView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_MATCHING_INVITE
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        offer = get_object_or_404(_offer_queryset(request.user), pk=kwargs["pk"])
        candidate = get_object_or_404(
            scoped_freight_match_candidate_queryset(
                request.user, PermissionCode.FREIGHT_MATCHING_VIEW
            ),
            pk=kwargs["candidate_pk"],
            offer=offer,
        )
        try:
            invite_match_candidate(candidate=candidate, actor=request.user)
        except ValidationError:
            pass
        return redirect("backoffice:freight_offer_detail", pk=offer.pk)


class FreightOfferSimulateInterestView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_MARKETPLACE_SELECT
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        offer = get_object_or_404(_offer_queryset(request.user), pk=kwargs["pk"])
        carrier_id = request.POST.get("carrier_id")
        driver_id = request.POST.get("driver_id")
        vehicle_id = request.POST.get("vehicle_id")
        invitation_id = request.POST.get("invitation_id")
        notes = request.POST.get("notes", "Interesse simulado via backoffice.")

        carrier = CarrierProfile.objects.filter(pk=carrier_id).first() if carrier_id else None
        driver = Driver.objects.filter(pk=driver_id).first() if driver_id else None
        from src.vehicles.infrastructure.django.models import Vehicle

        vehicle = Vehicle.objects.filter(pk=vehicle_id).first() if vehicle_id else None
        invitation = (
            FreightOfferInvitation.objects.filter(pk=invitation_id).first()
            if invitation_id
            else None
        )

        from src.freights.application.marketplace_services import express_interest_in_offer

        try:
            express_interest_in_offer(
                offer=offer,
                carrier=carrier,
                driver=driver,
                vehicle=vehicle,
                invitation=invitation,
                notes=notes,
                actor=request.user,
            )
        except ValidationError:
            pass
        return redirect("backoffice:freight_offer_detail", pk=offer.pk)


class FreightOfferWithdrawInterestView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_MARKETPLACE_SELECT
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        interest = get_object_or_404(FreightOfferInterest, pk=kwargs["interest_pk"])
        from src.freights.application.marketplace_services import withdraw_interest

        try:
            withdraw_interest(interest, actor=request.user)
        except ValidationError:
            pass
        return redirect("backoffice:freight_offer_detail", pk=interest.offer_id)


class FreightOfferSelectCandidateView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_MARKETPLACE_SELECT
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        interest = get_object_or_404(FreightOfferInterest, pk=kwargs["interest_pk"])
        from src.freights.application.marketplace_services import select_interested_candidate

        try:
            select_interested_candidate(interest, actor=request.user)
        except ValidationError:
            pass
        return redirect("backoffice:freight_offer_detail", pk=interest.offer_id)


class FreightOfferCancelSelectionView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_MARKETPLACE_CANCEL_SELECTION
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        selection = get_object_or_404(FreightOfferSelection, pk=kwargs["selection_pk"])
        reason = request.POST.get("reason", "Cancelamento via backoffice.")
        from src.freights.application.marketplace_services import cancel_selection

        try:
            cancel_selection(selection, reason=reason, actor=request.user)
        except ValidationError:
            pass
        return redirect("backoffice:freight_offer_detail", pk=selection.offer_id)


class FreightOfferConfirmSelectionView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_MARKETPLACE_SELECT
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        selection = get_object_or_404(FreightOfferSelection, pk=kwargs["selection_pk"])
        from src.freights.application.marketplace_services import confirm_selection

        try:
            confirm_selection(selection, actor=request.user)
        except ValidationError:
            pass
        return redirect("backoffice:freight_offer_detail", pk=selection.offer_id)


class FreightOfferDeclineSelectionView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_MARKETPLACE_SELECT
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        selection = get_object_or_404(FreightOfferSelection, pk=kwargs["selection_pk"])
        reason_str = request.POST.get("reason", "OTHER")
        from src.freights.domain.matching_enums import SelectionDeclineReason

        try:
            reason = SelectionDeclineReason(reason_str)
        except ValueError:
            reason = SelectionDeclineReason.OTHER

        from src.freights.application.marketplace_services import decline_selection

        try:
            decline_selection(selection, reason=reason, actor=request.user)
        except ValidationError:
            pass
        return redirect("backoffice:freight_offer_detail", pk=selection.offer_id)
