from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from .models import User

class UserAdmin(BaseUserAdmin):
    model = User
    readonly_fields = ['last_login', 'created_at', 'updated_at',]
    list_display = [
        'email',
        'username',
        'phone',
        'company_name',
        'created_at',
        'updated_at'
    ]
    fieldsets = (
        (None, {'fields': ('email', 'username', 'company_name', 'password',)}),
        (_('Personal info'), {'fields': ('first_name', 'last_name', 'middle_name', 'phone',)}),
        (_('Important dates'), {'fields': ('last_login', 'created_at', 'updated_at',)}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'username', 'first_name', 'last_name', 'company_name', 'password1', 'password2', 'is_staff'),
        }),
    )
    list_filter = ['created_at', 'updated_at']
    search_fields = ['email', 'username', 'phone']
    ordering = ['email',]


admin.site.register(User, UserAdmin)