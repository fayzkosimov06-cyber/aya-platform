from django.urls import path
from . import views, workspace

urlpatterns = [
    path('<int:pk>/export/', workspace.export, name='event_export'),
    path('', workspace.listing, name='event_list'),
    path('create/', workspace.edit, name='event_create'),
    path('<int:pk>/', workspace.detail, name='event_detail'),
    path('<int:pk>/edit/', workspace.edit, name='event_edit'),
    path('<int:pk>/join/', views.event_join_view, name='event_join'),
    path('<int:pk>/finish/', views.event_finish_view, name='event_finish'),
    path('<int:pk>/report/', workspace.report_route, name='event_report_edit'),
    path('photos/<int:pk>/delete/', views.event_photo_delete_view, name='event_photo_delete'),
    # ... (другие пути)
    path('<int:pk>/delete/', workspace.delete, name='event_delete'),
]