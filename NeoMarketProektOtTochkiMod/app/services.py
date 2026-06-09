import requests
from django.utils import timezone
from django.conf import settings
from django.db import transaction

from .models import ProductModeration, ProductModerationFieldReport
from .exceptions import (
    ModerationNotFoundError,
    ModerationNotAssignedError,
    ModerationInvalidStatusError,
    ProductHasNoSkusError,
    B2BEventError
)

def approve_ticket_service(ticket_id: str, moderator, comment: str = ""):
    """
    Реализует канонический flow одобрения товара модератором.
    """
    try:
        moderation = ProductModeration.objects.select_related('moderator_id').get(id=ticket_id)
    except ProductModeration.DoesNotExist:
        raise ModerationNotFoundError("Product not found in moderation queue")

    if moderation.status == ProductModeration.StatusChoices.HARD_BLOCKED:
        raise ModerationInvalidStatusError("Product is permanently blocked")

    if moderation.status != ProductModeration.StatusChoices.IN_REVIEW:
        raise ModerationInvalidStatusError("Product is not in review status")

    if moderation.moderator_id != moderator:
        raise ModerationNotAssignedError("This moderation card is not assigned to you")

    b2b_url = getattr(settings, 'B2B_URL', 'http://b2b:8000')
    headers = {
        'X-Service-Key': getattr(settings, 'MOD_TO_B2B_KEY', 'default-service-key'),
        'Content-Type': 'application/json'
    }

    # 6. Проверка наличия SKU через B2B Public Catalog
    product_url = f"{b2b_url}/api/v1/products/{moderation.product_id}"
    response = requests.get(product_url, headers=headers, timeout=5)
    
    if response.status_code == 200:
        data = response.json()
        skus = data.get('skus', [])
        if not skus or len(skus) == 0:
            raise ProductHasNoSkusError("Product has no SKUs, cannot approve")
    else:
        raise B2BEventError(f"B2B public product check failed with status {response.status_code}")

    # 7 & 8. Атомарное обновление статуса и очистка field_reports
    with transaction.atomic():
        moderation.status = ProductModeration.StatusChoices.APPROVED
        moderation.date_moderation = timezone.now()
        moderation.moderator_comment = comment if comment else None
        moderation.blocking_reason = None
        moderation.save()
        
        ProductModerationFieldReport.objects.filter(product_moderation=moderation).delete()

        # 9. Отправка события в B2B
        event_payload = {
            "idempotency_key": str(moderation.id),
            "product_id": str(moderation.product_id),
            "event_type": "MODERATED",
            "moderator_id": str(moderator.id),
            "moderator_comment": comment if comment else "",
            "blocking_reason_id": None,
            "hard_block": False,
            "field_reports": [],
            "occurred_at": timezone.now().isoformat()
        }
    
        events_url = f"{b2b_url}/api/v1/moderation/events"
        event_response = requests.post(events_url, json=event_payload, headers=headers, timeout=5)
    
        if event_response.status_code not in (200, 201, 204):
            # 10. Если B2B вернул ошибку, мы выбрасываем исключение. 
            # Статус в БД уже MODERATED, но модератор увидит 500 и сможет повторить запрос (идемпотентность спасет).
            moderation.status = ProductModeration.StatusChoices.IN_REVIEW
            moderation.save()
            raise B2BEventError("Failed to notify B2B service about MODERATED event")

    return moderation

