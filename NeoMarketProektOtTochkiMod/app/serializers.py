from rest_framework import serializers

class ApproveTicketSerializer(serializers.Serializer):
    comment = serializers.CharField(
        max_length=2000, 
        required=False, 
        allow_blank=True,
        help_text="Комментарий модератора (для внутренних записей)"
    )