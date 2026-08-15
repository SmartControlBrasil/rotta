from __future__ import annotations

from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models as django_models
from django.db.models import Count, Prefetch, Q, Sum
from django.forms import formset_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.dateparse import parse_date
from django.views.generic import DetailView, TemplateView, View

from src.audit.infrastructure.django.models import AuditLog
from src.freights.application.quote_services import (
    ChargeData,
    FreightQuoteData,
    approve_freight_quote,
    cancel_freight_quote,
    create_freight_quote,
    get_quote_with_expiration_applied,
    reject_freight_quote,
    revise_freight_quote,
    send_freight_quote,
    submit_freight_quote_for_review,
    update_freight_quote_draft,
)
from src.freights.domain.quote_enums import (
    FreightPricingMethod,
    FreightQuoteChargeType,
    FreightQuoteStatus,
)
from src.freights.domain.quote_state_machine import REQUEST_STATUSES_ALLOWING_QUOTE_CREATION
from src.freights.infrastructure.django.models import (
    FreightQuote,
    FreightQuoteCharge,
    FreightRequest,
)
from src.identity.domain.enums import PermissionCode

from .authorization import (
    scoped_freight_offer_queryset,
    scoped_freight_quote_queryset,
    scoped_freight_request_queryset,
    scoped_user_queryset,
    user_has_backoffice_permission,
)
from .views import BackofficeContextMixin, BackofficePermissionMixin, FilteredListView

User = get_user_model()

QUOTE_STATUS_LABELS = {
    FreightQuoteStatus.DRAFT.value: "Rascunho",
    FreightQuoteStatus.UNDER_REVIEW.value: "Em análise",
    FreightQuoteStatus.APPROVED.value: "Aprovada",
    FreightQuoteStatus.SENT.value: "Enviada",
    FreightQuoteStatus.REJECTED.value: "Rejeitada",
    FreightQuoteStatus.EXPIRED.value: "Vencida",
    FreightQuoteStatus.CANCELLED.value: "Cancelada",
    FreightQuoteStatus.SUPERSEDED.value: "Substituída",
}

CHARGE_TYPE_LABELS = {
    FreightQuoteChargeType.BASE_FREIGHT.value: "Frete base",
    FreightQuoteChargeType.TOLL.value: "Pedágio",
    FreightQuoteChargeType.REFRIGERATION_SURCHARGE.value: "Adicional refrigerado",
    FreightQuoteChargeType.INSURANCE.value: "Seguro",
    FreightQuoteChargeType.LOADING_UNLOADING.value: "Carga/descarga",
    FreightQuoteChargeType.DAILY_RATE.value: "Diária",
    FreightQuoteChargeType.DEMURRAGE.value: "Estadia",
    FreightQuoteChargeType.ADMIN_FEE.value: "Taxa administrativa",
    FreightQuoteChargeType.DISCOUNT.value: "Desconto",
    FreightQuoteChargeType.OTHER.value: "Outro",
}


def user_can_view_quote_margin(user) -> bool:
    return user_has_backoffice_permission(user, PermissionCode.FREIGHT_QUOTES_VIEW_MARGIN)


def _quote_queryset(user):
    return (
        scoped_freight_quote_queryset(user, PermissionCode.FREIGHT_QUOTES_VIEW)
        .select_related(
            "freight_request",
            "freight_request__customer",
            "organization",
            "owner",
            "created_by",
            "revision_of",
        )
        .prefetch_related(
            Prefetch("charges", queryset=FreightQuoteCharge.objects.order_by("sequence")),
            "revisions",
        )
    )


class QuoteChargeForm(forms.Form):
    charge_type = forms.ChoiceField(
        choices=[(item.value, item.value) for item in FreightQuoteChargeType],
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    description = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    quantity = forms.DecimalField(
        initial=Decimal("1"),
        min_value=Decimal("0"),
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.001"}),
    )
    unit_amount = forms.DecimalField(
        min_value=Decimal("0"),
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
    )
    DELETE = forms.BooleanField(required=False, widget=forms.CheckboxInput())


QuoteChargeFormSet = formset_factory(QuoteChargeForm, extra=1, can_delete=True)


class FreightQuoteHeaderForm(forms.Form):
    valid_until = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    tax_amount = forms.DecimalField(
        required=False,
        initial=Decimal("0"),
        min_value=Decimal("0"),
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
    )
    estimated_cost = forms.DecimalField(
        required=False,
        min_value=Decimal("0"),
        widget=forms.NumberInput(attrs={"class": "form-control margin-field", "step": "0.01"}),
    )
    estimated_distance_km = forms.DecimalField(
        required=False,
        min_value=Decimal("0"),
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
    )
    customer_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
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

    def __init__(self, *args, user=None, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields["owner"].queryset = scoped_user_queryset(
                user, PermissionCode.USERS_VIEW
            ).order_by("email")
        if instance:
            self.fields["valid_until"].initial = instance.valid_until
            self.fields["tax_amount"].initial = instance.tax_amount
            self.fields["estimated_cost"].initial = instance.estimated_cost
            self.fields["estimated_distance_km"].initial = instance.estimated_distance_km
            self.fields["customer_notes"].initial = instance.customer_notes
            self.fields["internal_notes"].initial = instance.internal_notes
            self.fields["owner"].initial = instance.owner_id
        if user and not user_can_view_quote_margin(user):
            self.fields["estimated_cost"].disabled = True


def _charges_from_formset(formset) -> tuple[ChargeData, ...]:
    charges = []
    for index, form in enumerate(formset, start=1):
        if not form.cleaned_data or form.cleaned_data.get("DELETE"):
            continue
        charge_type = FreightQuoteChargeType(form.cleaned_data["charge_type"])
        charges.append(
            ChargeData(
                charge_type=charge_type,
                description=form.cleaned_data.get("description", ""),
                quantity=form.cleaned_data["quantity"],
                unit_amount=form.cleaned_data["unit_amount"],
                is_discount=charge_type == FreightQuoteChargeType.DISCOUNT,
                sequence=index,
            )
        )
    return tuple(charges)


def _initial_charge_formset(quote: FreightQuote | None):
    if not quote:
        return QuoteChargeFormSet(
            initial=[
                {
                    "charge_type": FreightQuoteChargeType.BASE_FREIGHT.value,
                    "quantity": Decimal("1"),
                    "unit_amount": Decimal("0"),
                }
            ]
        )
    initial = [
        {
            "charge_type": charge.charge_type,
            "description": charge.description,
            "quantity": charge.quantity,
            "unit_amount": charge.unit_amount,
        }
        for charge in quote.charges.all()
    ]
    return QuoteChargeFormSet(initial=initial or None)


def _build_quote_data(
    *,
    freight_request: FreightRequest,
    created_by,
    header_form: FreightQuoteHeaderForm,
    charges: tuple[ChargeData, ...],
) -> FreightQuoteData:
    cleaned = header_form.cleaned_data
    estimated_cost = cleaned.get("estimated_cost")
    return FreightQuoteData(
        freight_request=freight_request,
        created_by=created_by,
        owner=cleaned.get("owner") or created_by,
        pricing_method=FreightPricingMethod.MANUAL,
        valid_until=cleaned.get("valid_until"),
        estimated_cost=estimated_cost,
        estimated_distance_km=cleaned.get("estimated_distance_km"),
        tax_amount=cleaned.get("tax_amount") or Decimal("0"),
        internal_notes=cleaned.get("internal_notes", ""),
        customer_notes=cleaned.get("customer_notes", ""),
        charges=charges,
    )


class FreightQuoteListView(FilteredListView):
    template_name = "backoffice/pages/freight_quotes/list.html"
    context_object_name = "freight_quotes"
    permission_code = PermissionCode.FREIGHT_QUOTES_VIEW
    active_menu = "freight_quotes"
    page_title = "Cotações de Frete"
    breadcrumbs = (
        ("Dashboard", reverse_lazy("backoffice:dashboard")),
        ("Cotações de Frete", None),
    )

    def get_queryset(self):
        queryset = _quote_queryset(self.request.user)
        query = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "").strip()
        owner_id = self.request.GET.get("owner", "").strip()
        created_from = parse_date(self.request.GET.get("created_from", "").strip() or "")
        valid_until = parse_date(self.request.GET.get("valid_until", "").strip() or "")

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
        if owner_id:
            queryset = queryset.filter(owner_id=owner_id)
        if created_from:
            queryset = queryset.filter(created_at__date__gte=created_from)
        if valid_until:
            queryset = queryset.filter(valid_until=valid_until)
        return queryset.order_by("-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        base_qs = scoped_freight_quote_queryset(
            self.request.user, PermissionCode.FREIGHT_QUOTES_VIEW
        )
        stats = base_qs.aggregate(
            total=Count("id"),
            drafts=Count("id", filter=Q(status=FreightQuoteStatus.DRAFT.value)),
            under_review=Count("id", filter=Q(status=FreightQuoteStatus.UNDER_REVIEW.value)),
            approved=Count("id", filter=Q(status=FreightQuoteStatus.APPROVED.value)),
            sent=Count("id", filter=Q(status=FreightQuoteStatus.SENT.value)),
            expired=Count("id", filter=Q(status=FreightQuoteStatus.EXPIRED.value)),
        )
        context["kpis"] = stats
        context["can_view_values"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_QUOTES_VIEW
        )
        context["can_view_margin"] = user_can_view_quote_margin(self.request.user)
        if context["can_view_margin"]:
            context["quoted_total"] = base_qs.aggregate(total=Sum("total_amount"))["total"] or 0
        context["status_labels"] = QUOTE_STATUS_LABELS
        context["statuses"] = [
            FreightQuoteStatus.DRAFT,
            FreightQuoteStatus.UNDER_REVIEW,
            FreightQuoteStatus.APPROVED,
            FreightQuoteStatus.SENT,
            FreightQuoteStatus.REJECTED,
            FreightQuoteStatus.EXPIRED,
            FreightQuoteStatus.CANCELLED,
        ]
        context["owners"] = scoped_user_queryset(
            self.request.user, PermissionCode.USERS_VIEW
        ).order_by("email")
        context["can_create"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_QUOTES_CREATE
        )
        return context


class FreightQuoteDetailView(BackofficePermissionMixin, BackofficeContextMixin, DetailView):
    template_name = "backoffice/pages/freight_quotes/detail.html"
    context_object_name = "quote"
    permission_code = PermissionCode.FREIGHT_QUOTES_VIEW
    active_menu = "freight_quotes"
    page_title = "Detalhe da Cotação"

    def get_queryset(self):
        return _quote_queryset(self.request.user)

    def get_object(self, queryset=None):
        quote = super().get_object(queryset)
        return get_quote_with_expiration_applied(quote, actor=self.request.user)

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Cotações de Frete", reverse_lazy("backoffice:freight_quotes")),
            (self.object.reference_code, None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        quote = self.object
        context["status_labels"] = QUOTE_STATUS_LABELS
        context["charge_type_labels"] = CHARGE_TYPE_LABELS
        context["can_view_margin"] = user_can_view_quote_margin(self.request.user)
        context["can_edit"] = (
            quote.status == FreightQuoteStatus.DRAFT.value
            and user_has_backoffice_permission(
                self.request.user, PermissionCode.FREIGHT_QUOTES_UPDATE
            )
        )
        context["can_review"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_QUOTES_REVIEW
        )
        context["can_approve"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_QUOTES_APPROVE
        )
        context["can_send"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_QUOTES_SEND
        )
        context["can_reject"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_QUOTES_REJECT
        )
        context["can_cancel"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_QUOTES_CANCEL
        )
        context["can_revise"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_QUOTES_REVISE
        )
        context["revision_history"] = quote.freight_request.quotes.order_by("-version")
        context["audit_logs"] = AuditLog.objects.filter(target_id=str(quote.id)).select_related(
            "actor", "organization"
        )[:12]
        context["generated_offers"] = (
            scoped_freight_offer_queryset(self.request.user, PermissionCode.FREIGHT_OFFERS_VIEW)
            .filter(freight_quote=quote)
            .order_by("-created_at")
        )
        context["can_view_offers"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.FREIGHT_OFFERS_VIEW
        )
        return context


class FreightQuoteCreateView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/freight_quotes/form.html"
    permission_code = PermissionCode.FREIGHT_QUOTES_CREATE
    active_menu = "freight_quotes"
    page_title = "Nova Cotação"

    def get_freight_request(self):
        return get_object_or_404(
            scoped_freight_request_queryset(
                self.request.user, PermissionCode.FREIGHT_REQUESTS_VIEW
            ).select_related("customer", "organization"),
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
            ("Nova Cotação", None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        freight_request = self.get_freight_request()
        context["freight_request"] = freight_request
        context["can_create_quote"] = (
            freight_request.status in REQUEST_STATUSES_ALLOWING_QUOTE_CREATION
        )
        if "header_form" not in context:
            context["header_form"] = FreightQuoteHeaderForm(user=self.request.user)
        if "charge_formset" not in context:
            context["charge_formset"] = _initial_charge_formset(None)
        context["can_view_margin"] = user_can_view_quote_margin(self.request.user)
        context["is_edit"] = False
        return context

    def post(self, request, *args, **kwargs):
        freight_request = self.get_freight_request()
        if freight_request.status not in REQUEST_STATUSES_ALLOWING_QUOTE_CREATION:
            raise PermissionDenied
        header_form = FreightQuoteHeaderForm(request.POST, user=request.user)
        charge_formset = QuoteChargeFormSet(request.POST)
        if header_form.is_valid() and charge_formset.is_valid():
            try:
                if "estimated_cost" in header_form.cleaned_data and not user_can_view_quote_margin(
                    request.user
                ):
                    header_form.cleaned_data["estimated_cost"] = None
                data = _build_quote_data(
                    freight_request=freight_request,
                    created_by=request.user,
                    header_form=header_form,
                    charges=_charges_from_formset(charge_formset),
                )
                quote = create_freight_quote(data=data, actor=request.user)
                return redirect("backoffice:freight_quote_detail", pk=quote.pk)
            except ValidationError as exc:
                header_form.add_error(None, exc)
        return render(
            request,
            self.template_name,
            self.get_context_data(header_form=header_form, charge_formset=charge_formset),
        )


class FreightQuoteUpdateView(FreightQuoteCreateView):
    permission_code = PermissionCode.FREIGHT_QUOTES_UPDATE
    page_title = "Editar Cotação"

    def get_quote(self):
        return get_object_or_404(_quote_queryset(self.request.user), pk=self.kwargs["pk"])

    def get_freight_request(self):
        return self.get_quote().freight_request

    def get_breadcrumbs(self):
        quote = self.get_quote()
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Cotações de Frete", reverse_lazy("backoffice:freight_quotes")),
            (
                quote.reference_code,
                reverse_lazy("backoffice:freight_quote_detail", args=[quote.id]),
            ),
            ("Editar", None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        quote = self.get_quote()
        context["quote"] = quote
        context["is_edit"] = True
        if "header_form" not in context:
            context["header_form"] = FreightQuoteHeaderForm(user=self.request.user, instance=quote)
        if "charge_formset" not in context:
            context["charge_formset"] = _initial_charge_formset(quote)
        return context

    def post(self, request, *args, **kwargs):
        quote = self.get_quote()
        header_form = FreightQuoteHeaderForm(request.POST, user=request.user, instance=quote)
        charge_formset = QuoteChargeFormSet(request.POST)
        if header_form.is_valid() and charge_formset.is_valid():
            try:
                changes = {
                    k: v for k, v in header_form.cleaned_data.items() if k in header_form.fields
                }
                if not user_can_view_quote_margin(request.user):
                    changes.pop("estimated_cost", None)
                update_freight_quote_draft(
                    quote,
                    actor=request.user,
                    charges=_charges_from_formset(charge_formset),
                    **changes,
                )
                return redirect("backoffice:freight_quote_detail", pk=quote.pk)
            except ValidationError as exc:
                header_form.add_error(None, exc)
        return render(
            request,
            self.template_name,
            self.get_context_data(header_form=header_form, charge_formset=charge_formset),
        )


class FreightQuoteReviewView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_QUOTES_REVIEW
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        quote = get_object_or_404(_quote_queryset(request.user), pk=kwargs["pk"])
        try:
            submit_freight_quote_for_review(quote, actor=request.user)
        except ValidationError:
            pass
        return redirect("backoffice:freight_quote_detail", pk=quote.pk)


class FreightQuoteApproveView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_QUOTES_APPROVE
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        quote = get_object_or_404(_quote_queryset(request.user), pk=kwargs["pk"])
        try:
            approve_freight_quote(quote, actor=request.user)
        except ValidationError:
            pass
        return redirect("backoffice:freight_quote_detail", pk=quote.pk)


class FreightQuoteRejectView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_QUOTES_REJECT
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        quote = get_object_or_404(_quote_queryset(request.user), pk=kwargs["pk"])
        try:
            reject_freight_quote(
                quote, reason=request.POST.get("rejection_reason", ""), actor=request.user
            )
        except ValidationError:
            pass
        return redirect("backoffice:freight_quote_detail", pk=quote.pk)


class FreightQuoteSendView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_QUOTES_SEND
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        quote = get_object_or_404(_quote_queryset(request.user), pk=kwargs["pk"])
        try:
            send_freight_quote(quote, actor=request.user)
        except ValidationError:
            pass
        return redirect("backoffice:freight_quote_detail", pk=quote.pk)


class FreightQuoteCancelView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_QUOTES_CANCEL
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        quote = get_object_or_404(_quote_queryset(request.user), pk=kwargs["pk"])
        try:
            cancel_freight_quote(
                quote,
                reason=request.POST.get("cancellation_reason", ""),
                actor=request.user,
            )
        except ValidationError:
            pass
        return redirect("backoffice:freight_quote_detail", pk=quote.pk)


class FreightQuoteReviseView(BackofficePermissionMixin, View):
    permission_code = PermissionCode.FREIGHT_QUOTES_REVISE
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        source = get_object_or_404(_quote_queryset(request.user), pk=kwargs["pk"])
        try:
            new_quote = revise_freight_quote(
                source,
                data=FreightQuoteData(
                    freight_request=source.freight_request,
                    created_by=request.user,
                    owner=source.owner,
                    valid_until=source.valid_until,
                    estimated_cost=source.estimated_cost
                    if user_can_view_quote_margin(request.user)
                    else None,
                    tax_amount=source.tax_amount,
                    internal_notes=source.internal_notes,
                    customer_notes=source.customer_notes,
                    charges=tuple(
                        ChargeData(
                            charge_type=FreightQuoteChargeType(charge.charge_type),
                            description=charge.description,
                            quantity=charge.quantity,
                            unit_amount=charge.unit_amount,
                            is_discount=charge.is_discount,
                            sequence=charge.sequence,
                        )
                        for charge in source.charges.all()
                    ),
                ),
                actor=request.user,
            )
            return redirect("backoffice:freight_quote_edit", pk=new_quote.pk)
        except ValidationError:
            return redirect("backoffice:freight_quote_detail", pk=source.pk)
