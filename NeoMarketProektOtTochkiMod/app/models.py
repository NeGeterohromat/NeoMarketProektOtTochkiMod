import uuid
from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator


class ProductBlockingReason(models.Model):
    """
    Таблица product_blocking_reasons (seed)
    """
    id = models.UUIDField(
        primary_key=True, 
        default=uuid.uuid4, 
        editable=False,
        help_text="Идентификатор (генерируется автоматически)"
    )
    code = models.CharField(
        max_length=64,
        unique=True,
        verbose_name="Код причины",
        help_text="Уникальный код причины (например, FORBIDDEN_GOODS)"
    )
    title = models.CharField(
        max_length=255, 
        verbose_name="Текст причины блокировки"
    )
    description = models.TextField(
        blank=True,
        default="",
        verbose_name="Описание причины"
    )
    hard_block = models.BooleanField(
        default=False, 
        verbose_name="Перманентная блокировка"
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Активна"
    )

    class Meta:
        db_table = 'product_blocking_reasons'
        verbose_name = 'Причина блокировки'
        verbose_name_plural = 'Причины блокировок'
        ordering = ['title']

    def __str__(self):
        return self.title


class ProductModeration(models.Model):
    """
    Таблица product_moderation
    """
    class StatusChoices(models.TextChoices):
        PENDING = 'PENDING', 'Ожидает'
        IN_REVIEW = 'IN_REVIEW', 'В работе'
        APPROVED = 'APPROVED', 'Промодерировано'
        BLOCKED = 'BLOCKED', 'Заблокировано'
        HARD_BLOCKED = 'HARD_BLOCKED', 'Жесткая блокировка'

    id = models.UUIDField(
        primary_key=True, 
        default=uuid.uuid4, 
        editable=False
    )
    product_id = models.UUIDField(
        unique=True, 
        verbose_name="ID товара в B2B"
    )
    seller_id = models.UUIDField(
        verbose_name="ID продавца"
    )
    status = models.CharField(
        max_length=20, 
        choices=StatusChoices.choices, 
        default=StatusChoices.PENDING,
        verbose_name="Статус модерации"
    )
    queue_priority = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(4)],
        verbose_name="Приоритет очереди (1-4)"
    )
    json_before = models.JSONField(
        null=True, 
        blank=True, 
        verbose_name="Состояние товара ДО изменений"
    )
    json_after = models.JSONField(
        verbose_name="Текущее состояние товара (JSON)"
    )
    blocking_reason = models.ForeignKey(
        ProductBlockingReason, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='moderations',
        verbose_name="Причина блокировки"
    )
    moderator_id = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    moderator_comment = models.TextField(
        null=True, 
        blank=True, 
        verbose_name="Комментарий модератора"
    )
    date_created = models.DateTimeField(
        auto_now_add=True, 
        verbose_name="Дата создания"
    )
    date_updated = models.DateTimeField(
        auto_now=True, 
        verbose_name="Дата последнего обновления"
    )
    date_moderation = models.DateTimeField(
        null=True, 
        blank=True, 
        verbose_name="Дата последнего решения модератора"
    )

    class Meta:
        db_table = 'product_moderation'
        verbose_name = 'Модерация товара'
        verbose_name_plural = 'Модерация товаров'
        # Реализация ограничения CHECK (queue_priority BETWEEN 1 AND 4) на уровне БД
        constraints = [
            models.CheckConstraint(
                condition=models.Q(queue_priority__gte=1, queue_priority__lte=4),
                name='check_queue_priority_range'
            )
        ]
        # Полезные индексы для ускорения выборок очереди модерации
        indexes = [
            models.Index(fields=['status', 'queue_priority']),
            models.Index(fields=['seller_id']),
        ]

    def __str__(self):
        return f"Модерация товара {self.product_id} ({self.get_status_display()})"


class ProductModerationFieldReport(models.Model):
    """
    Таблица product_moderation_field_report
    """
    class FieldNameChoices(models.TextChoices):
        TITLE = 'title', 'Название'
        DESCRIPTION = 'description', 'Описание'
        PRODUCT_IMAGES = 'product_images', 'Изображения товара'
        CATEGORY = 'category', 'Категория'
        SKU_NAME = 'sku_name', 'Название SKU'
        SKU_IMAGE = 'sku_image', 'Изображение SKU'
        SKU_PRICE = 'sku_price', 'Цена SKU'

    id = models.UUIDField(
        primary_key=True, 
        default=uuid.uuid4, 
        editable=False
    )
    product_moderation = models.ForeignKey(
        ProductModeration, 
        on_delete=models.CASCADE, 
        related_name='field_reports',
        verbose_name="Запись модерации"
    )
    field_name = models.CharField(
        max_length=50, 
        choices=FieldNameChoices.choices, 
        verbose_name="Название поля"
    )
    sku_id = models.UUIDField(
        null=True, 
        blank=True, 
        verbose_name="ID конкретного SKU (null = замечание к товару)"
    )
    comment = models.TextField(
        verbose_name="Комментарий модератора"
    )
    date_created = models.DateTimeField(
        auto_now_add=True, 
        verbose_name="Дата создания"
    )

    class Meta:
        db_table = 'product_moderation_field_report'
        verbose_name = 'Отчет по полю модерации'
        verbose_name_plural = 'Отчеты по полям модерации'
        indexes = [
            models.Index(fields=['product_moderation', 'field_name']),
        ]

    def __str__(self):
        return f"Замечание к {self.field_name} для модерации {self.product_moderation_id}"