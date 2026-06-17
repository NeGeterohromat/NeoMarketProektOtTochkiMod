from django.contrib import admin
from .models import ProductBlockingReason


@admin.register(ProductBlockingReason)
class ProductBlockingReasonAdmin(admin.ModelAdmin):
    list_display = ('code', 'title', 'hard_block', 'is_active')
    list_filter = ('hard_block', 'is_active')
    search_fields = ('code', 'title', 'description')
    readonly_fields = ('id',)
    
    fieldsets = (
        (None, {
            'fields': ('id', 'code', 'title', 'description')
        }),
        ('Настройки', {
            'fields': ('hard_block', 'is_active')
        }),
    )