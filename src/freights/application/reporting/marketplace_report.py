from django.db.models import Count, Sum
from src.identity.domain.enums import PermissionCode
from src.freights.infrastructure.django.models import (
    FreightRequest,
    FreightOffer,
    FreightOfferInterest,
    FreightOfferSelection,
    FreightOperation,
)
from src.shared.interfaces.backoffice.authorization import (
    scoped_freight_request_queryset,
    scoped_freight_offer_queryset,
)
from src.freights.application.reporting.base_report import get_report_date_range

def get_marketplace_report(user, filters):
    start_dt, end_dt = get_report_date_range(filters)
    
    reqs = scoped_freight_request_queryset(user, PermissionCode.FREIGHT_REQUESTS_VIEW)
    offers = scoped_freight_offer_queryset(user, PermissionCode.FREIGHT_OFFERS_VIEW)
    
    # Filter by date and organization if provided
    org_id = filters.get("organization_id")
    if org_id:
        reqs = reqs.filter(organization_id=org_id)
        offers = offers.filter(organization_id=org_id)
        
    reqs = reqs.filter(created_at__range=(start_dt, end_dt))
    offers = offers.filter(created_at__range=(start_dt, end_dt))
    
    interests = FreightOfferInterest.objects.filter(offer__in=offers, created_at__range=(start_dt, end_dt))
    selections = FreightOfferSelection.objects.filter(offer__in=offers, created_at__range=(start_dt, end_dt))
    operations = FreightOperation.objects.filter(selection__in=selections, created_at__range=(start_dt, end_dt))
    
    reqs_count = reqs.count()
    offers_count = offers.count()
    interests_count = interests.count()
    selections_count = selections.count()
    ops_count = operations.count()
    
    # Conversion rates
    req_to_offer = (offers_count / reqs_count * 100) if reqs_count > 0 else 0.0
    offer_to_interest = (interests_count / offers_count * 100) if offers_count > 0 else 0.0
    interest_to_selection = (selections_count / interests_count * 100) if interests_count > 0 else 0.0
    selection_to_op = (ops_count / selections_count * 100) if selections_count > 0 else 0.0
    
    charts = [
        {
            "id": "funnel_chart",
            "library": "apex",
            "type": "bar",
            "categories": ["Solicitações", "Ofertas", "Interesses", "Seleções", "Operações"],
            "series": [
                {
                    "name": "Mapeamento do Funil",
                    "data": [reqs_count, offers_count, interests_count, selections_count, ops_count]
                }
            ],
            "options": {
                "plotOptions": {
                    "bar": {
                        "horizontal": True
                    }
                }
            }
        }
    ]
    
    # Financial metrics backlog:
    # "Caso ainda não exista fonte segura para GMV/comissão, NÃO inventar esses indicadores. Documentar como backlog."
    # We will pass these financial indicators as None or placeholders to document as backlog in the template.
    
    return {
        "kpis": {
            "requests_created": reqs_count,
            "offers_published": offers_count,
            "interests_received": interests_count,
            "selections_made": selections_count,
            "operations_converted": ops_count,
            "rate_req_to_offer": round(req_to_offer, 1),
            "rate_offer_to_interest": round(offer_to_interest, 1),
            "rate_interest_to_selection": round(interest_to_selection, 1),
            "rate_selection_to_op": round(selection_to_op, 1),
            "gmv_backlog": True,
            "commission_backlog": True,
        },
        "charts": charts,
    }
