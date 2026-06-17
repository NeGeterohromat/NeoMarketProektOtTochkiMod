from rest_framework import serializers

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