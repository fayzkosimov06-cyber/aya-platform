# users/context_processors.py
from .models import Notification
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
            'can_open_admin': can_manage_members(request.user),
            'can_open_moderation': can_record_visits(request.user),
            'unread_notifications_count': unread_notifications.count(),
        }
    return {}