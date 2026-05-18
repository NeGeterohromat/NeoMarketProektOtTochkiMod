import uuid
from django.db import models
from django.utils import timezone


class Moderation(models.Model):
    class Events(models.TextChoices):
        PRODUCT_CREATED = "PRODUCT_CREATED", "Создано"
        PRODUCT_EDITED = "PRODUCT_EDITED", "Отредактировано"
        PRODUCT_DELETED = "PRODUCT_DELETED", "Удалено"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    idempotency_key = models.UUIDField(default=uuid.uuid4)
    product = models.UUIDField(default=uuid.uuid4)
    seller = models.UUIDField(default=uuid.uuid4)
    event = models.CharField(max_length=32, choices=Events)
    date = models.DateTimeField(default=timezone.now)