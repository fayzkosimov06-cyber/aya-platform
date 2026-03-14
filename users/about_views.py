from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .models import AboutContactLink, AboutExtraBlock, AboutPage, AboutStatItem, AboutValueBlock


ICON_CHOICES = [
    ('fa-solid fa-star', 'Звезда'),
    ('fa-solid fa-heart', 'Сердце'),
    ('fa-solid fa-bullseye', 'Цель'),
    ('fa-solid fa-lightbulb', 'Идея'),
    ('fa-solid fa-users', 'Команда'),
    ('fa-solid fa-user-group', 'Люди'),
    ('fa-solid fa-hand-holding-heart', 'Помощь'),
    ('fa-solid fa-graduation-cap', 'Обучение'),
    ('fa-solid fa-briefcase-medical', 'Медицина'),
    ('fa-solid fa-leaf', 'Экология'),
    ('fa-solid fa-chart-line', 'Рост'),
    ('fa-solid fa-chart-column', 'Статистика'),
    ('fa-solid fa-calendar-check', 'Мероприятия'),
    ('fa-solid fa-location-dot', 'Адрес'),
    ('fa-solid fa-envelope', 'Email'),
    ('fa-solid fa-phone', 'Телефон'),
]


CONTACT_LABEL_DEFAULTS = {
    'instagram': 'Instagram',
    'facebook': 'Facebook',
    'telegram': 'Telegram',
    'youtube': 'YouTube',
    'tiktok': 'TikTok',
    'whatsapp': 'WhatsApp',
    'website': 'Сайт',
    'email': 'Email',
    'phone': 'Телефон',
    'custom': 'Ссылка',
}


def can_edit_about(user):
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.role in ['leader', 'worker', 'head_admin', 'president']


def _to_int(val, default=0):
    try:
        return int(val)
    except Exception:
        return default


def _is_checked(request, name):
    return request.POST.get(name) in ['1', 'true', 'on', 'yes']


def _ensure_about_exists():
    obj, _ = AboutPage.objects.get_or_create(pk=1)
    return obj


def _clean_text(request, key, fallback=''):
    return (request.POST.get(key) or fallback).strip()


def _contact_payload(request):
    platform = (_clean_text(request, 'platform', 'custom') or 'custom').lower()
    if platform not in dict(AboutContactLink.PLATFORM_CHOICES):
        platform = 'custom'

    label = _clean_text(request, 'label') or CONTACT_LABEL_DEFAULTS.get(platform, 'Ссылка')
    url = _clean_text(request, 'url')
    icon = _clean_text(request, 'icon')
    if not icon:
        icon = AboutContactLink.PLATFORM_ICONS.get(platform, 'fa-solid fa-link')

    return {
        'platform': platform,
        'label': label,
        'url': url,
        'icon': icon,
        'order': _to_int(request.POST.get('order'), 0),
        'is_active': _is_checked(request, 'is_active'),
        'requires_volunteer_access': _is_checked(request, 'requires_volunteer_access'),
    }


@login_required
def about_manage_view(request):
    if not can_edit_about(request.user):
        messages.error(request, 'Недостаточно прав для редактирования этой страницы.')
        return redirect('about_page')

    about = _ensure_about_exists()

    if request.method == 'POST':
        action = (_clean_text(request, 'action') or '').strip()

        if action == 'update_main':
            about.title = _clean_text(request, 'title', about.title) or about.title
            about.description = _clean_text(request, 'description')
            about.video_url = _clean_text(request, 'video_url')
            about.mission_title = _clean_text(request, 'mission_title', about.mission_title) or about.mission_title
            about.mission_text = _clean_text(request, 'mission_text')
            about.email = _clean_text(request, 'email')
            about.address = _clean_text(request, 'address')
            # резервные старые поля оставляем, чтобы fallback на публичной странице тоже работал
            about.instagram = _clean_text(request, 'instagram')
            about.telegram = _clean_text(request, 'telegram')
            about.save()
            messages.success(request, 'Основная информация сохранена.')
            return redirect('about_manage')

        if action == 'add_value':
            AboutValueBlock.objects.create(
                about=about,
                title=_clean_text(request, 'title', 'Новый блок') or 'Новый блок',
                text=_clean_text(request, 'text'),
                icon=_clean_text(request, 'icon', 'fa-solid fa-star') or 'fa-solid fa-star',
                order=_to_int(request.POST.get('order'), 0),
                is_active=_is_checked(request, 'is_active'),
            )
            messages.success(request, 'Блок добавлен.')
            return redirect('about_manage')

        if action == 'update_value':
            obj = get_object_or_404(AboutValueBlock, pk=request.POST.get('id'), about=about)
            obj.title = _clean_text(request, 'title', obj.title) or obj.title
            obj.text = _clean_text(request, 'text')
            obj.icon = _clean_text(request, 'icon', obj.icon) or obj.icon
            obj.order = _to_int(request.POST.get('order'), obj.order)
            obj.is_active = _is_checked(request, 'is_active')
            obj.save()
            messages.success(request, 'Блок обновлён.')
            return redirect('about_manage')

        if action == 'delete_value':
            get_object_or_404(AboutValueBlock, pk=request.POST.get('id'), about=about).delete()
            messages.warning(request, 'Блок удалён.')
            return redirect('about_manage')

        if action == 'add_stat':
            AboutStatItem.objects.create(
                about=about,
                number=_clean_text(request, 'number', '0') or '0',
                label=_clean_text(request, 'label', 'Подпись') or 'Подпись',
                icon=_clean_text(request, 'icon', 'fa-solid fa-chart-line') or 'fa-solid fa-chart-line',
                order=_to_int(request.POST.get('order'), 0),
                is_active=_is_checked(request, 'is_active'),
            )
            messages.success(request, 'Карточка статистики добавлена.')
            return redirect('about_manage')

        if action == 'update_stat':
            obj = get_object_or_404(AboutStatItem, pk=request.POST.get('id'), about=about)
            obj.number = _clean_text(request, 'number', obj.number) or obj.number
            obj.label = _clean_text(request, 'label', obj.label) or obj.label
            obj.icon = _clean_text(request, 'icon', obj.icon) or obj.icon
            obj.order = _to_int(request.POST.get('order'), obj.order)
            obj.is_active = _is_checked(request, 'is_active')
            obj.save()
            messages.success(request, 'Карточка статистики обновлена.')
            return redirect('about_manage')

        if action == 'delete_stat':
            get_object_or_404(AboutStatItem, pk=request.POST.get('id'), about=about).delete()
            messages.warning(request, 'Карточка статистики удалена.')
            return redirect('about_manage')

        if action == 'add_contact':
            payload = _contact_payload(request)
            if not payload['url']:
                messages.error(request, 'Укажите ссылку или контакт.')
            else:
                AboutContactLink.objects.create(about=about, **payload)
                messages.success(request, 'Соцсеть/контакт добавлен.')
            return redirect('about_manage')

        if action == 'update_contact':
            obj = get_object_or_404(AboutContactLink, pk=request.POST.get('id'), about=about)
            payload = _contact_payload(request)
            if not payload['url']:
                messages.error(request, 'Укажите ссылку или контакт.')
            else:
                for key, value in payload.items():
                    setattr(obj, key, value)
                obj.save()
                messages.success(request, 'Соцсеть/контакт обновлён.')
            return redirect('about_manage')

        if action == 'delete_contact':
            get_object_or_404(AboutContactLink, pk=request.POST.get('id'), about=about).delete()
            messages.warning(request, 'Соцсеть/контакт удалён.')
            return redirect('about_manage')

        if action == 'add_extra':
            AboutExtraBlock.objects.create(
                about=about,
                title=_clean_text(request, 'title', 'Новый блок') or 'Новый блок',
                text=_clean_text(request, 'text'),
                icon=_clean_text(request, 'icon', 'fa-solid fa-lightbulb') or 'fa-solid fa-lightbulb',
                order=_to_int(request.POST.get('order'), 0),
                is_active=_is_checked(request, 'is_active'),
            )
            messages.success(request, 'Дополнительный блок добавлен.')
            return redirect('about_manage')

        if action == 'update_extra':
            obj = get_object_or_404(AboutExtraBlock, pk=request.POST.get('id'), about=about)
            obj.title = _clean_text(request, 'title', obj.title) or obj.title
            obj.text = _clean_text(request, 'text')
            obj.icon = _clean_text(request, 'icon', obj.icon) or obj.icon
            obj.order = _to_int(request.POST.get('order'), obj.order)
            obj.is_active = _is_checked(request, 'is_active')
            obj.save()
            messages.success(request, 'Дополнительный блок обновлён.')
            return redirect('about_manage')

        if action == 'delete_extra':
            get_object_or_404(AboutExtraBlock, pk=request.POST.get('id'), about=about).delete()
            messages.warning(request, 'Дополнительный блок удалён.')
            return redirect('about_manage')

        messages.error(request, 'Неизвестное действие.')
        return redirect('about_manage')

    context = {
        'about': about,
        'value_blocks': about.value_blocks.all().order_by('order', 'id'),
        'stat_items': about.stat_items.all().order_by('order', 'id'),
        'contact_links': about.contact_links.all().order_by('order', 'id'),
        'extra_blocks': about.extra_blocks.all().order_by('order', 'id'),
        'platform_choices': AboutContactLink.PLATFORM_CHOICES,
        'icon_choices': ICON_CHOICES,
    }
    return render(request, 'users/about_manage.html', context)
