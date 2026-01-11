from django.urls import path
from . import views

app_name = 'feed'

urlpatterns = [
    path('', views.index, name='index'),
    path('releases/', views.releases_partial, name='releases_partial'),
    path('sync/', views.sync_releases, name='sync'),
    path('sync/stream/', views.sync_releases_stream, name='sync_stream'),
]
