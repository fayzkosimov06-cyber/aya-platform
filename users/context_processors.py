# users/context_processors.py
from .models import Notification
from .permissions import CAPABILITIES,allowed
from .points import can_award
from .access import can_manage_members, can_record_visits

def notifications_processor(request):
    """
    Этот процессор добавляет информацию о непрочитанных уведомлениях
    в контекст каждого шаблона, чтобы колокольчик 🔔 работал на всех страницах.
    """
    if request.user.is_authenticated:
        unread_notifications = Notification.objects.filter(recipient=request.user, is_read=False)
        return {
            'unread_notifications': unread_notifications,
            'can_award_points': can_award(request.user),
            'can_open_admin': any(allowed(request.user,c) for c in CAPABILITIES if c not in {'contacts','visits'}),
            'can_manage_rights': allowed(request.user,'permissions'),
            'can_view_audit': allowed(request.user,'audit'),
            'grants': {c:allowed(request.user,c) for c in CAPABILITIES},
            'can_open_moderation': allowed(request.user,'visits') or allowed(request.user,'admissions'),
            'unread_notifications_count': unread_notifications.count(),
        }
    return {}