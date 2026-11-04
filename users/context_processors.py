# users/context_processors.py
from django.conf import settings
from .models import Notification
from .permissions import CAPABILITIES,allowed
from .access import can_manage_members, can_record_visits
from .card_access import can_manage_cards, eligible_person

def notifications_processor(request):
    """
    Этот процессор добавляет информацию о непрочитанных уведомлениях
    в контекст каждого шаблона, чтобы колокольчик 🔔 работал на всех страницах.
    """
    if request.user.is_authenticated:
        from .birthdays import notify, context
        notify(request.user)
        unread_notifications = Notification.objects.filter(recipient=request.user, is_read=False)
        grants = {c:allowed(request.user,c) for c in CAPABILITIES}
        return {
            'csrf_cookie_name': settings.CSRF_COOKIE_NAME,
            'can_manage_cards': can_manage_cards(request.user),
            'can_have_card': eligible_person(request.user),
            **context(request),
            'unread_notifications': unread_notifications,
            'can_award_points': grants['points_award'],
            'can_open_admin': any(grants[c] for c in CAPABILITIES if c not in {'contacts','visits'}),
            'can_manage_rights': grants['permissions'],
            'can_view_audit': grants['audit'],
            'grants': grants,
            'can_open_moderation': grants['visits'] or grants['admissions'],
            'unread_notifications_count': unread_notifications.count(),
        }
    return {'csrf_cookie_name': settings.CSRF_COOKIE_NAME}
