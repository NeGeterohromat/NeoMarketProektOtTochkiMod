import requests
from datetime import timedelta
from django.utils import timezone
from django.conf import settings
from django.db import transaction
from django.core.cache import cache

from .models import ProductModeration, ProductModerationFieldReport, ProductBlockingReason
from .exceptions import (
    ModerationNotFoundError,
    ModerationNotAssignedError,
    ModerationInvalidStatusError,
    ProductHasNoSkusError,
    B2BEventError,
    DoubleB2BEventError,
    B2BUnavailableError
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


def block_ticket_service(ticket_id: str, moderator, blocking_reason_ids: list, comment: str = "", field_reports: list = None):
    """
    Реализует канонический flow блокировки товара (soft или hard).
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

    if not blocking_reason_ids:
        raise ValueError("blocking_reason_ids cannot be empty")
    
    reason_id = blocking_reason_ids[0]
    try:
        blocking_reason = ProductBlockingReason.objects.get(id=reason_id)
    except ProductBlockingReason.DoesNotExist:
        raise ValueError("Blocking reason not found")

    b2b_url = getattr(settings, 'B2B_URL', 'http://b2b:8000')
    headers = {
        'X-Service-Key': getattr(settings, 'MOD_TO_B2B_KEY', 'default-service-key'),
        'Content-Type': 'application/json'
    }

    with transaction.atomic():
        # Определяем тип блокировки по причине
        if blocking_reason.hard_block:
            moderation.status = ProductModeration.StatusChoices.HARD_BLOCKED
        else:
            moderation.status = ProductModeration.StatusChoices.BLOCKED
            
        moderation.date_moderation = timezone.now()
        moderation.blocking_reason = blocking_reason
        moderation.moderator_comment = comment if comment else None
        moderation.save()
        
        # Удаляем старые field_reports
        ProductModerationFieldReport.objects.filter(product_moderation=moderation).delete()
        
        # Создаем новые field_reports (маппим field_path из OpenAPI на field_name из модели)
        if field_reports:
            for report in field_reports:
                path = report.get('field_path', '')
                if 'title' in path: field_name = 'title'
                elif 'description' in path: field_name = 'description'
                elif 'images' in path: field_name = 'product_images'
                elif 'category' in path: field_name = 'category'
                elif 'sku_name' in path or 'name' in path: field_name = 'sku_name'
                elif 'sku_image' in path: field_name = 'sku_image'
                elif 'price' in path: field_name = 'sku_price'
                ProductModerationFieldReport.objects.create(
                    product_moderation=moderation,
                    field_name=field_name,
                    sku_id=report.get('sku_id'),
                    comment=report.get('message', '')
                )

        # Формируем и отправляем событие в B2B
        event_payload = {
            "idempotency_key": str(moderation.id),
            "product_id": str(moderation.product_id),
            "event_type": "BLOCKED",
            "moderator_id": str(moderator.id),
            "moderator_comment": comment if comment else "",
            "blocking_reason_id": str(blocking_reason.id),
            "hard_block": blocking_reason.hard_block,
            "field_reports": [
                {
                    "field_name": fr.field_name,
                    "sku_id": str(fr.sku_id) if fr.sku_id else None,
                    "comment": fr.comment
                } for fr in moderation.field_reports.all()
            ],
            "occurred_at": timezone.now().isoformat()
        }
    
        events_url = f"{b2b_url}/api/v1/moderation/events"
        event_response = requests.post(events_url, json=event_payload, headers=headers, timeout=5)
    
        if event_response.status_code not in (200, 201, 204):
            # Транзакция откатится автоматически из-за исключения внутри with transaction.atomic()
            raise B2BEventError("Failed to notify B2B service about BLOCKED event")

    return moderation


def handle_b2b_event_service(event_data: dict):
    """
    Обработка входящих событий от B2B (PRODUCT_EDITED, PRODUCT_DELETED).
    """
    event_type = event_data.get('event_type')
    idempotency_key = event_data.get('idempotency_key')
    payload = event_data.get('payload', {})
    product_id = payload.get('product_id')
    
    if not product_id:
        return

    # Проверка идемпотентности
    if check_idempotency(idempotency_key):
        # Дубликат события - возвращаемся без побочных эффектов
        return

    try:
        moderation = ProductModeration.objects.get(product_id=product_id)
    except ProductModeration.DoesNotExist:
        if event_type != 'PRODUCT_CREATED':
            return

        create_order(product_id)
        return

    # событие CREATED но оно уже было в таблице
    if event_type == 'PRODUCT_CREATED':
        raise DoubleB2BEventError()


    if event_type == 'PRODUCT_EDITED':
        # edited_event_on_hard_blocked_is_ignored
        # Игнорируем идемпотентно
        if moderation.status == ProductModeration.StatusChoices.HARD_BLOCKED:
           return
        update_ticket(moderation)
            
    elif event_type == 'PRODUCT_DELETED':
        # deleted_event_removes_hard_blocked
        moderation.delete()

def get_order_data(product_id):
    b2b_url = getattr(settings, 'B2B_URL', 'http://b2b:8000')
    headers = {
        'X-Service-Key': getattr(settings, 'MOD_TO_B2B_KEY', 'default-service-key'),
        'Content-Type': 'application/json'
    }
    url = f"{b2b_url}/api/v1/products/{product_id}"
    response = requests.get(url, headers=headers, timeout=5)

    if response.status_code != 200:
        raise B2BUnavailableError()

    return response.json()

def create_order(product_id):
    response = get_order_data(product_id)

    ProductModeration.objects.create(
            product_id=product_id,
            seller_id=response['seller_id'],
            status=ProductModeration.StatusChoices.PENDING,
            queue_priority=2,
            json_after=response # По контракту запрос из Mod приходит без полей cost_price и reserved_quantity
            )

def update_ticket(mod):
    response=get_order_data(mod.product_id)
    
    with transaction.atomic():
        mod.json_before=mod.json_after
        mod.json_after=response
        mod.status=ProductModeration.StatusChoices.PENDING
        mod.moderator_id=None
        mod.save() # date_updated имеет флаг auto_now=True

        ProductModerationFieldReport.objects.filter(product_moderation=mod).delete()

def check_idempotency(idempotency_key: str) -> bool:
    """
    Проверяет идемпотентность события по ключу.
    
    Returns:
        True - если ключ уже был обработан (дубликат)
        False - если ключ новый
    
    Side effect: сохраняет ключ в кэш с TTL из настроек
    """
    if not idempotency_key:
        return False
    
    cache_key = f"idempotency:{idempotency_key}"
    
    # Проверяем, есть ли уже такой ключ в кэше
    if cache.get(cache_key):
        return True  # Дубликат
    
    # Сохраняем ключ с TTL (из настроек, по умолчанию 24 часа)
    ttl = getattr(settings, 'KEY_CACHE_TTL', 86400)  # 24 часа в секундах
    cache.set(cache_key, True, ttl)
    
    return False  # Новый ключ


def claim_next_ticket_service(moderator, queue_priority=None, category_ids=None):
    """
    Атомарно выбирает топовый PENDING-тикет, переводит в IN_REVIEW и привязывает к модератору.
    Защищено от race-conditions через SELECT FOR UPDATE SKIP LOCKED.
    """
    # 1. Ленивый возврат просроченных тикетов в очередь (если модератор пропал)
    timeout_minutes = getattr(settings, 'IN_REVIEW_TIMEOUT_MINUTES', 30)
    expiration_time = timezone.now() - timedelta(minutes=timeout_minutes)
    ProductModeration.objects.filter(
        status=ProductModeration.StatusChoices.IN_REVIEW,
        date_updated__lt=expiration_time
    ).update(status=ProductModeration.StatusChoices.PENDING, moderator_id=None)

    # 2. Проверка: есть ли у модератора уже активный тикет в работе
    if ProductModeration.objects.filter(
        moderator_id=moderator, 
        status=ProductModeration.StatusChoices.IN_REVIEW
    ).exists():
        raise ModerationInvalidStatusError("Moderator already has an active ticket in IN_REVIEW status")

    # 3. Определяем порядок перебора приоритетов
    priorities = [queue_priority] if queue_priority is not None else [1, 2, 3, 4]

    # 4. Атомарный поиск и блокировка тикета
    with transaction.atomic():
        for priority in priorities:
            qs = ProductModeration.objects.filter(
                status=ProductModeration.StatusChoices.PENDING,
                queue_priority=priority
            )
            
            # Фильтр по категориям внутри JSON-поля
            if category_ids:
                qs = qs.filter(json_after__category_id__in=category_ids)
                
            # Сортировка FIFO (самые старые сначала)
            qs = qs.order_by('date_updated')
            
            # SKIP LOCKED пропускает строки, заблокированные другими транзакциями
            ticket = qs.select_for_update(skip_locked=True).first()
            
            
            if ticket:
                ticket.status = ProductModeration.StatusChoices.IN_REVIEW
                ticket.moderator_id = moderator
                # date_updated обновится автоматически благодаря auto_now=True
                ticket.save(update_fields=['status', 'moderator_id', 'date_updated'])
                return ticket
                
    return None

def get_blocking_reasons_service(hard_block: bool = None, is_active: bool = True):
    """
    Возвращает список причин блокировки с фильтрацией.
    """
    queryset = ProductBlockingReason.objects.all()
    
    if hard_block is not None:
        queryset = queryset.filter(hard_block=hard_block)
    
    if is_active is not None:
        queryset = queryset.filter(is_active=is_active)
    
    return queryset


def create_blocking_reason_service(code: str, title: str, hard_block: bool, description: str = ""):
    """
    Создает новую причину блокировки.
    """
    if ProductBlockingReason.objects.filter(code=code).exists():
        raise ValueError(f"Reason with code '{code}' already exists")
    
    return ProductBlockingReason.objects.create(
        code=code,
        title=title,
        description=description,
        hard_block=hard_block,
        is_active=True
    )


def update_blocking_reason_service(reason_id: str, **kwargs):
    """
    Обновляет причину блокировки.
    """
    try:
        reason = ProductBlockingReason.objects.get(id=reason_id)
    except ProductBlockingReason.DoesNotExist:
        raise ValueError("Blocking reason not found")
    
    for key, value in kwargs.items():
        if value is not None:
            setattr(reason, key, value)
    
    reason.save()
    return reason


def deactivate_blocking_reason_service(reason_id: str):
    """
    Деактивирует причину блокировки (soft-delete).
    Проверяет ссылочную целостность: если на причину ссылаются карточки модерации,
    деактивация запрещена.
    """
    try:
        reason = ProductBlockingReason.objects.get(id=reason_id)
    except ProductBlockingReason.DoesNotExist:
        raise ValueError("Blocking reason not found")
    
    # Проверка ссылочной целостности
    if ProductModeration.objects.filter(blocking_reason=reason).exists():
        raise ValueError("Cannot deactivate reason: it is referenced by moderation cards")
    
    reason.is_active = False
    reason.save()
    return reason