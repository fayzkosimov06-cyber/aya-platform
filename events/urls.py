from django.urls import path
from . import views

urlpatterns = [
    path('', views.event_list_view, name='event_list'),
    path('create/', views.event_create_view, name='event_create'),
    path('<int:pk>/', views.event_detail_view, name='event_detail'),
    path('<int:pk>/edit/', views.event_edit_view, name='event_edit'),
    path('<int:pk>/join/', views.event_join_view, name='event_join'),
    path('<int:pk>/finish/', views.event_finish_view, name='event_finish'),
    path('<int:pk>/report/', views.event_report_edit_view, name='event_report_edit'),
    path('photos/<int:pk>/delete/', views.event_photo_delete_view, name='event_photo_delete'),
    # ... (другие пути)
    path('<int:pk>/delete/', views.event_delete_view, name='event_delete'),
]