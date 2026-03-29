from django.contrib import admin
from .models import Release, FavouriteUploader


@admin.register(Release)
class ReleaseAdmin(admin.ModelAdmin):
    list_display = ('release_name', 'artist', 'uploader', 'release_type', 'received_at')
    list_filter = ('release_type', 'received_at')
    search_fields = ('release_name', 'artist', 'uploader')
    ordering = ('-received_at',)


@admin.register(FavouriteUploader)
class FavouriteUploaderAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at')
    search_fields = ('name',)
