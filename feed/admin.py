from django.contrib import admin
from .models import Release


@admin.register(Release)
class ReleaseAdmin(admin.ModelAdmin):
    list_display = ('uploader', 'release_name', 'received_at', 'created_at')
    list_filter = ('received_at',)
    search_fields = ('uploader', 'release_name')
    ordering = ('-received_at',)
