# users/urls.py
from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    # Главная страница и "О нас"
    path('', views.home_view, name='home'),
    path('about/', views.about_view, name='about_page'),

    # НОВЫЙ ПУТЬ: База данных волонтеров
    path('volunteers/', views.volunteer_list_view, name='volunteer_list'),

    # Аутентификация
    path('signup/', views.signup_view, name='signup'),
    path('login/', auth_views.LoginView.as_view(template_name='users/login.html'), name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Профили
    path('profile/', views.my_profile_view, name='my_profile'),
    path('profile/edit/', views.profile_edit_view, name='profile_edit'),
    path('profile/<int:pk>/', views.public_profile_view, name='public_profile'),
    # Вставьте эту строку
    path('profile/<int:pk>/admin-edit/', views.admin_edit_user_view, name='admin_edit_user'),

    # Панель Модератора
    path('moderation/', views.moderator_dashboard_view, name='moderator_dashboard'),
    path('moderation/approve/<int:pk>/', views.approve_user_view, name='approve_user'),
    path('moderation/reject/<int:pk>/', views.reject_user_view, name='reject_user'),
    

    # Панель Администратора
    path('administration/', views.admin_dashboard_view, name='admin_dashboard'),
    path('administration/users/', views.user_management_view, name='user_management'),
    path('administration/users/update-role/<int:pk>/', views.update_user_role_view, name='update_user_role'),
    path('administration/users/toggle-active/<int:pk>/', views.toggle_active_volunteer_view, name='toggle_active_volunteer'),
    path('administration/directions/', views.direction_management_view, name='direction_management'),
    path('administration/directions/create/', views.direction_create_view, name='direction_create'),
    path('administration/directions/delete/<int:pk>/', views.direction_delete_view, name='direction_delete'),
    path('administration/directions/assign-leader/<int:pk>/', views.assign_direction_leader_view, name='assign_direction_leader'),
    path('administration/schools/', views.school_management_view, name='school_management'),
    path('administration/schools/create/', views.school_create_view, name='school_create'),
    path('administration/schools/delete/<int:pk>/', views.school_delete_view, name='school_delete'),
    path('administration/schools/assign-leader/<int:pk>/', views.assign_school_leader_view, name='assign_school_leader'),
    path('administration/about/edit/', views.about_page_edit_view, name='about_page_edit'),
    path('administration/structure/', views.administration_page_view, name='administration_page'), 
    # --- НОВЫЙ URL ДЛЯ ЖУРНАЛА ---
    path('administration/logs/', views.audit_log_view, name='audit_log'),

    # Уведомления
    path('notifications/', views.notification_list_view, name='notifications'),
    path('notifications/read/<int:pk>/', views.mark_notification_as_read_view, name='mark_notification_as_read'),
]