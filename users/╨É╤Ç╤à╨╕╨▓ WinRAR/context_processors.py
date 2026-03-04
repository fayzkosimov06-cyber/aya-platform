# users/context_processors.py
from .models import Notification

def notifications_processor(request):
    """
    Этот процессор добавляет информацию о непрочитанных уведомлениях
    в контекст каждого шаблона, чтобы колокольчик 🔔 работал на всех страницах.
    """
    if request.user.is_authenticated:
        unread_notifications = Notification.objects.filter(recipient=request.user, is_read=False)
        return {
            'unread_notifications': unread_notifications,
            'unread_notifications_count': unread_notifications.count(),
        }
    return {}