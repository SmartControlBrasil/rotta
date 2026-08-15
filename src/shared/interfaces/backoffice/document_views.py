from __future__ import annotations

import mimetypes

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView

from src.audit.infrastructure.django.models import AuditLog
from src.carriers.domain.enums import CarrierDocumentType
from src.compliance.application.queries import (
    DocumentFilters,
    collect_unified_documents,
    document_kpis,
)
from src.compliance.application.services import (
    approve_document,
    record_document_download,
    reject_document,
    resolve_document,
    start_document_review,
    upload_document,
)
from src.compliance.application.upload import validate_upload_file
from src.compliance.domain.enums import DocumentStatus, EntityType
from src.drivers.domain.enums import DriverDocumentType
from src.identity.domain.enums import PermissionCode
from src.shared.infrastructure.django.storage import PrivateDocumentStorageAdapter
from src.vehicles.domain.enums import VehicleDocumentType

from .authorization import (
    scoped_carrier_document_queryset,
    scoped_carrier_queryset,
    scoped_driver_document_queryset,
    scoped_driver_queryset,
    scoped_organization_queryset,
    scoped_user_queryset,
    scoped_vehicle_document_queryset,
    scoped_vehicle_queryset,
    user_can_access_document,
    user_has_backoffice_permission,
)
from .views import (
    PAGE_SIZE,
    BackofficeContextMixin,
    BackofficePermissionMixin,
)


class DocumentAccessMixin:
    def get_document_bundle(self, document_id: str):
        resolved = resolve_document(document_id=document_id)
        if resolved is None:
            raise Http404
        document, entity_type = resolved
        if not user_can_access_document(self.request.user, document, entity_type):
            raise PermissionDenied
        return document, entity_type


class DocumentListView(BackofficePermissionMixin, BackofficeContextMixin, ListView):
    template_name = "backoffice/pages/documents/list.html"
    permission_code = PermissionCode.DOCUMENTS_VIEW
    active_menu = "documents"
    page_title = "Documentos"
    context_object_name = "documents"
    paginate_by = PAGE_SIZE

    def get_queryset(self):
        filters = DocumentFilters(
            q=self.request.GET.get("q", "").strip(),
            entity_type=self.request.GET.get("entity_type", "").strip(),
            document_type=self.request.GET.get("document_type", "").strip(),
            status=self.request.GET.get("status", "").strip(),
            validity=self.request.GET.get("validity", "").strip(),
            organization_id=self.request.GET.get("organization", "").strip(),
            reviewer_id=self.request.GET.get("reviewer", "").strip(),
        )
        self.document_filters = filters
        return collect_unified_documents(
            driver_documents_qs=scoped_driver_document_queryset(
                self.request.user, PermissionCode.DOCUMENTS_VIEW
            ),
            vehicle_documents_qs=scoped_vehicle_document_queryset(
                self.request.user, PermissionCode.DOCUMENTS_VIEW
            ),
            carrier_documents_qs=scoped_carrier_document_queryset(
                self.request.user, PermissionCode.DOCUMENTS_VIEW
            ),
            filters=filters,
        )

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Documentos", None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        driver_qs = scoped_driver_document_queryset(
            self.request.user, PermissionCode.DOCUMENTS_VIEW
        )
        vehicle_qs = scoped_vehicle_document_queryset(
            self.request.user, PermissionCode.DOCUMENTS_VIEW
        )
        carrier_qs = scoped_carrier_document_queryset(
            self.request.user, PermissionCode.DOCUMENTS_VIEW
        )
        context["filters"] = self.document_filters
        context["kpis"] = document_kpis(
            driver_documents_qs=driver_qs,
            vehicle_documents_qs=vehicle_qs,
            carrier_documents_qs=carrier_qs,
        )
        context["entity_types"] = list(EntityType)
        context["document_statuses"] = list(DocumentStatus)
        context["organizations"] = scoped_organization_queryset(
            self.request.user, PermissionCode.ORGANIZATIONS_VIEW
        ).order_by("name")
        context["reviewers"] = scoped_user_queryset(
            self.request.user, PermissionCode.USERS_VIEW
        ).order_by("username")
        context["can_upload"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.DOCUMENTS_UPLOAD
        )
        context["can_review"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.DOCUMENTS_REVIEW
        )
        return context


class DocumentReviewListView(DocumentListView):
    template_name = "backoffice/pages/documents/review.html"
    permission_code = PermissionCode.DOCUMENTS_REVIEW
    page_title = "Fila de análise"

    def get_queryset(self):
        filters = DocumentFilters(
            q=self.request.GET.get("q", "").strip(),
            entity_type=self.request.GET.get("entity_type", "").strip(),
            document_type=self.request.GET.get("document_type", "").strip(),
            status=DocumentStatus.UNDER_REVIEW.value,
            validity=self.request.GET.get("validity", "").strip(),
            organization_id=self.request.GET.get("organization", "").strip(),
            reviewer_id=self.request.GET.get("reviewer", "").strip(),
        )
        pending_filters = DocumentFilters(
            q=filters.q,
            entity_type=filters.entity_type,
            document_type=filters.document_type,
            status=DocumentStatus.PENDING.value,
            validity=filters.validity,
            organization_id=filters.organization_id,
            reviewer_id=filters.reviewer_id,
        )
        self.document_filters = filters
        under_review = collect_unified_documents(
            driver_documents_qs=scoped_driver_document_queryset(
                self.request.user, PermissionCode.DOCUMENTS_REVIEW
            ),
            vehicle_documents_qs=scoped_vehicle_document_queryset(
                self.request.user, PermissionCode.DOCUMENTS_REVIEW
            ),
            carrier_documents_qs=scoped_carrier_document_queryset(
                self.request.user, PermissionCode.DOCUMENTS_REVIEW
            ),
            filters=filters,
        )
        pending = collect_unified_documents(
            driver_documents_qs=scoped_driver_document_queryset(
                self.request.user, PermissionCode.DOCUMENTS_REVIEW
            ),
            vehicle_documents_qs=scoped_vehicle_document_queryset(
                self.request.user, PermissionCode.DOCUMENTS_REVIEW
            ),
            carrier_documents_qs=scoped_carrier_document_queryset(
                self.request.user, PermissionCode.DOCUMENTS_REVIEW
            ),
            filters=pending_filters,
        )
        combined = under_review + pending
        combined.sort(key=lambda item: item.created_at, reverse=True)
        return combined

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Documentos", reverse_lazy("backoffice:documents")),
            ("Fila de análise", None),
        )


class DocumentDetailView(
    BackofficePermissionMixin, BackofficeContextMixin, DocumentAccessMixin, DetailView
):
    template_name = "backoffice/pages/documents/detail.html"
    permission_code = PermissionCode.DOCUMENTS_VIEW
    active_menu = "documents"
    page_title = "Documento"
    context_object_name = "document_record"
    pk_url_kwarg = "pk"

    def get_object(self):
        document, entity_type = self.get_document_bundle(str(self.kwargs["pk"]))
        self.entity_type = entity_type
        self.document_instance = document
        from src.compliance.application.services import unified_document_from_instance

        return unified_document_from_instance(document, entity_type)

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Documentos", reverse_lazy("backoffice:documents")),
            (self.object.document_type, None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        document = self.document_instance
        fk_field = {
            EntityType.DRIVER: "driver",
            EntityType.VEHICLE: "vehicle",
            EntityType.CARRIER: "carrier",
        }[self.entity_type]
        entity = getattr(document, fk_field)
        context["entity_type"] = self.entity_type
        context["document"] = document
        context["versions"] = (
            type(document)
            .objects.filter(**{fk_field: entity, "document_type": document.document_type})
            .select_related("reviewed_by", "replaced_by")
            .order_by("-created_at")
        )
        context["audit_logs"] = AuditLog.objects.filter(target_id=str(document.id)).select_related(
            "actor", "organization"
        )[:12]
        context["can_download"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.DOCUMENTS_DOWNLOAD
        )
        context["can_review"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.DOCUMENTS_REVIEW
        )
        context["can_approve"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.DOCUMENTS_APPROVE
        )
        context["can_reject"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.DOCUMENTS_REJECT
        )
        context["can_replace"] = user_has_backoffice_permission(
            self.request.user, PermissionCode.DOCUMENTS_REPLACE
        )
        return context

    def post(self, request, *args, **kwargs):
        document, entity_type = self.get_document_bundle(str(self.kwargs["pk"]))
        action = request.POST.get("action", "").strip()
        if action == "start_review":
            if not user_has_backoffice_permission(request.user, PermissionCode.DOCUMENTS_REVIEW):
                raise PermissionDenied
            start_document_review(document=document, entity_type=entity_type, actor=request.user)
        elif action == "approve":
            if not user_has_backoffice_permission(request.user, PermissionCode.DOCUMENTS_APPROVE):
                raise PermissionDenied
            approve_document(document=document, entity_type=entity_type, actor=request.user)
        elif action == "reject":
            if not user_has_backoffice_permission(request.user, PermissionCode.DOCUMENTS_REJECT):
                raise PermissionDenied
            reject_document(
                document=document,
                entity_type=entity_type,
                actor=request.user,
                rejection_reason=request.POST.get("rejection_reason", ""),
            )
        else:
            raise PermissionDenied
        return redirect("backoffice:document_detail", pk=document.pk)


class DocumentDownloadView(BackofficePermissionMixin, DocumentAccessMixin, View):
    permission_code = PermissionCode.DOCUMENTS_DOWNLOAD

    def get(self, request, pk):
        document, entity_type = self.get_document_bundle(str(pk))
        storage = PrivateDocumentStorageAdapter()
        if not storage.exists(document.storage_key):
            raise Http404
        record_document_download(document=document, entity_type=entity_type, actor=request.user)
        handle = storage.open(document.storage_key)
        content_type = mimetypes.guess_type(document.original_filename or document.storage_key)[0]
        response = FileResponse(handle, content_type=content_type or "application/octet-stream")
        filename = document.original_filename or f"{document.document_type}.bin"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class DocumentUploadView(BackofficePermissionMixin, BackofficeContextMixin, TemplateView):
    template_name = "backoffice/pages/documents/upload.html"
    permission_code = PermissionCode.DOCUMENTS_UPLOAD
    active_menu = "documents"
    page_title = "Upload de documento"

    def get_breadcrumbs(self):
        return (
            ("Dashboard", reverse_lazy("backoffice:dashboard")),
            ("Documentos", reverse_lazy("backoffice:documents")),
            ("Upload", None),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["entity_types"] = list(EntityType)
        context["driver_document_types"] = list(DriverDocumentType)
        context["vehicle_document_types"] = list(VehicleDocumentType)
        context["carrier_document_types"] = list(CarrierDocumentType)
        context["drivers"] = scoped_driver_queryset(
            self.request.user, PermissionCode.DRIVERS_VIEW
        ).order_by("full_name")
        context["vehicles"] = scoped_vehicle_queryset(
            self.request.user, PermissionCode.VEHICLES_VIEW
        ).order_by("plate")
        context["carriers"] = scoped_carrier_queryset(
            self.request.user, PermissionCode.CARRIERS_VIEW
        ).order_by("trade_name")
        context["organizations"] = scoped_organization_queryset(
            self.request.user, PermissionCode.ORGANIZATIONS_VIEW
        ).order_by("name")
        return context

    def post(self, request, *args, **kwargs):
        entity_type_value = request.POST.get("entity_type", "").strip()
        entity_id = request.POST.get("entity_id", "").strip()
        document_type = request.POST.get("document_type", "").strip()
        issue_date_raw = request.POST.get("issue_date", "").strip()
        expiration_date_raw = request.POST.get("expiration_date", "").strip()
        notes = request.POST.get("notes", "").strip()
        replace_document_id = request.POST.get("replace_document_id", "").strip() or None

        try:
            entity_type = EntityType(entity_type_value)
        except ValueError as exc:
            raise ValidationError({"entity_type": "Tipo de entidade inválido."}) from exc

        if entity_type == EntityType.DRIVER:
            get_object_or_404(
                scoped_driver_queryset(request.user, PermissionCode.DRIVERS_VIEW),
                pk=entity_id,
            )
        elif entity_type == EntityType.VEHICLE:
            get_object_or_404(
                scoped_vehicle_queryset(request.user, PermissionCode.VEHICLES_VIEW),
                pk=entity_id,
            )
        else:
            get_object_or_404(
                scoped_carrier_queryset(request.user, PermissionCode.CARRIERS_VIEW),
                pk=entity_id,
            )

        validated_upload = validate_upload_file(uploaded_file=request.FILES.get("file"))
        from django.utils.dateparse import parse_date

        document = upload_document(
            entity_type=entity_type,
            entity_id=entity_id,
            document_type=document_type,
            validated_upload=validated_upload,
            storage=PrivateDocumentStorageAdapter(),
            actor=request.user,
            issue_date=parse_date(issue_date_raw) if issue_date_raw else None,
            expiration_date=parse_date(expiration_date_raw) if expiration_date_raw else None,
            notes=notes,
            replace_document_id=replace_document_id,
        )
        return redirect("backoffice:document_detail", pk=document.pk)
