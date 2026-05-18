from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from users.models import User


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True, required=True, validators=[validate_password]
    )

    class Meta:
        model = User
        fields = (
            'id',
            'email', 
            'password', 
            'first_name',
            'last_name',
            'middle_name',
            'company_name',
            'phone',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at',)

    def create(self, validated_data):
        email = validated_data.get('email')
        return User.objects.create_user(
            username=email, 
            **validated_data
        )