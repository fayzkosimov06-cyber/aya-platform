# users/urls.py
from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from . import about_views
from . import training
from .home_views import home_manage_view
from .points import points_rating as rating_view
from . import points, units, proposals, management, control_views


urlpatterns = [
    path('help/', training.help_view, name='training_help'),
    path('help/progress/', training.progress_view, name='training_progress'),
    path('administration/rights/', control_views.rights, name='rights_manage'),
    path('administration/private-log/', control_views.journal, {'mode':'private'}, name='journal_private'),
    path('administration/activity-log/', control_views.journal, {'mode':'activity'}, name='journal_activity'),
    path('administration/balance/', control_views.balance, name='ghost_balance'),
    path('administration/dates/', control_views.dates, name='ghost_dates'),
    path('activity/search/', control_views.search_event, name='record_search'),
    path('schools/', units.catalog, {'kind':'school'}, name='school_catalog'),
    path('schools/new/', units.create, {'kind':'school'}, name='school_create_page'),
    path('directions/new/', units.create, name='direction_create_page'),
    path('schools/<int:pk>/delete/', units.delete, {'kind':'school'}, name='school_delete_page'),
    path('directions/<int:pk>/delete/', units.delete, name='direction_delete_page'),
    path('schools/<int:pk>/suggest-points/', proposals.suggest, {'kind':'school'}, name='school_suggest'),
    path('directions/<int:pk>/suggest-points/', proposals.suggest, name='direction_suggest'),
    path('points/proposals/', proposals.listing, name='proposal_list'),
    path('points/proposals/<int:pk>/', proposals.review, name='proposal_review'),
    path('directions/', units.catalog, name='unit_catalog'),
    path('directions/<int:pk>/', units.detail, name='direction_detail'),
    path('directions/<int:pk>/edit/', units.edit, name='direction_edit'),
    path('schools/<int:pk>/', units.detail, {'kind':'school'}, name='school_detail'),
    path('schools/<int:pk>/edit/', units.edit, {'kind':'school'}, name='school_edit'),
    path('schools/<int:pk>/teachers/new/', units.school_item, {'item_type':'teacher'}, name='teacher_create'),
    path('schools/<int:pk>/teachers/<int:item_id>/', units.school_item, {'item_type':'teacher'}, name='teacher_edit'),
    path('schools/<int:pk>/lessons/new/', units.school_item, {'item_type':'lesson'}, name='lesson_create'),
    path('schools/<int:pk>/lessons/<int:item_id>/', units.school_item, {'item_type':'lesson'}, name='lesson_edit'),
    path('points/new/', points.quick_award, name='points_quick'),
    path('points/works/', points.work_list, name='points_works'),
    path('points/works/<int:pk>/', points.work_detail, name='points_work'),
    path('points/awards/<int:pk>/correct/', points.correct_award, name='points_correct'),
    path('points/kinds/', points.kinds, name='points_kinds'),
    path('rating/', rating_view, name='volunteer_rating'),
    path('administration/home/', home_manage_view, name='home_manage'),
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
    path('profile/<int:pk>/activity/', views.activity_periods_manage_view, name='activity_periods_manage'),
    path('profile/<int:pk>/activity/<int:period_id>/edit/', views.activity_period_edit_view, name='activity_period_edit'),
    path('profile/<int:pk>/activity/<int:period_id>/delete/', views.activity_period_delete_view, name='activity_period_delete'),


    # Панель Модератора
    path('moderation/', views.moderator_dashboard_view, name='moderator_dashboard'),
    path('moderation/approve/<int:pk>/', views.approve_user_view, name='approve_user'),
    path('moderation/reject/<int:pk>/', views.reject_user_view, name='reject_user'),

    # NEW: отметки "пришёл" и доступ сразу
    path('moderation/visit/<int:pk>/', views.mark_candidate_visit_view, name='mark_candidate_visit'),
    path('moderation/grant-access/<int:pk>/', views.grant_volunteer_access_view, name='grant_volunteer_access'),
    path('moderation/visit-delete/<int:visit_id>/', views.delete_candidate_visit_view, name='delete_candidate_visit'),


    # Панель Администратора
    path('administration/', management.dashboard, name='admin_dashboard'),
    path('administration/users/', management.people, name='user_management'),
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
    path('administration/logs/', control_views.journal, name='audit_log'),

    # Уведомления
    path('notifications/', views.notification_list_view, name='notifications'),
    path('notifications/read/<int:pk>/', views.mark_notification_as_read_view, name='mark_notification_as_read'),
    # NEW: Mark all as read
    path('notifications/read-all/', views.mark_all_notifications_as_read_view, name='mark_all_notifications_as_read'),
    path('profile/<int:pk>/admin-password-change/', views.admin_password_change_view, name='admin_password_change'),
    path('administration/about/', about_views.about_manage_view, name='admin_about_manage'),
    path('about/manage/', about_views.about_manage_view, name='about_manage'),
]
