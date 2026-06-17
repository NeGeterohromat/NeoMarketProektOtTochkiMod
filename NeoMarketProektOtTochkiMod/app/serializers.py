from rest_framework import serializers
from .models import ProductBlockingReason

class ApproveTicketSerializer(serializers.Serializer):
    comment = serializers.CharField(
        max_length=2000, 
        required=False, 
        allow_blank=True,
        help_text="Комментарий модератора (для внутренних записей)"
    )

class FieldReportSerializer(serializers.Serializer):
    field_path = serializers.CharField(max_length=255)
    message = serializers.CharField(max_length=1000)
    severity = serializers.ChoiceField(choices=['INFO', 'WARNING', 'ERROR'], default='ERROR')
    sku_id = serializers.UUIDField(required=False, allow_null=True)

class BlockTicketSerializer(serializers.Serializer):
    blocking_reason_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1
    )
    comment = serializers.CharField(max_length=2000, required=False, allow_blank=True, default='')
    field_reports = FieldReportSerializer(many=True, required=False, default=[])

class B2BEventSerializer(serializers.Serializer):
    event_type = serializers.ChoiceField(choices=['PRODUCT_CREATED', 'PRODUCT_EDITED', 'PRODUCT_DELETED'])
    idempotency_key = serializers.UUIDField()
    occurred_at = serializers.DateTimeField()
    payload = serializers.DictField()

class ClaimTicketRequestSerializer(serializers.Serializer):
    queue_priority = serializers.IntegerField(
        min_value=1, 
        max_value=4, 
        required=False, 
        allow_null=True,
        help_text="Опциональный фильтр по приоритету (1-4)"
    )
    category_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
        help_text="Опциональный фильтр по категориям"
    )

class ProductBlockingReasonSerializer(serializers.ModelSerializer):
    """
    Сериализатор для справочника причин блокировки.
    Соответствует BlockingReasonResponse из moderation.yaml
    """
    class Meta:
        model = ProductBlockingReason
        fields = ['id', 'code', 'title', 'description', 'hard_block', 'is_active']
        read_only_fields = ['id']


class ProductBlockingReasonCreateSerializer(serializers.Serializer):
    """
    Сериализатор для создания причины блокировки (admin).
    Соответствует BlockingReasonCreateRequest из moderation.yaml
    """
    code = serializers.CharField(max_length=64)
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    hard_block = serializers.BooleanField()

    def validate_code(self, value):
        import re
        if not re.match(r'^[A-Z_]+$', value):
            raise serializers.ValidationError("Code must contain only uppercase letters and underscores")
        return value


class ProductBlockingReasonUpdateSerializer(serializers.Serializer):
    """
    Сериализатор для обновления причины блокировки (admin).
    Соответствует BlockingReasonUpdateRequest из moderation.yaml
    """
    title = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)