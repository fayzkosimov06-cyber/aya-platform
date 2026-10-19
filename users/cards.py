"""Staff-controlled annual membership cards; owners receive a flattened preview only."""
from functools import wraps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.http import Http404, HttpResponse, HttpResponseForbidden, JsonResponse, FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.cache import patch_vary_headers
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from .card_access import can_manage_cards, can_preview_card, eligible_people, filter_cards
from .card_forms import CardEditionForm, CardForm, CardExportForm
from .card_models import current_card_year
from .card_print import preflight, preview_png, make_pdf, make_zip, photo_dpi
from .journal import emit
from .models import CardEdition, VolunteerCard, Direction, School, Club


def staff_only(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not can_manage_cards(request.user):
            return HttpResponseForbidden('Управление и печать карт доступны только сотрудникам отдела.')
        return view(request, *args, **kwargs)
    return wrapper


def private_response(response):
    response['Cache-Control'] = 'private, no-store, max-age=0'
    response['X-Content-Type-Options'] = 'nosniff'
    patch_vary_headers(response, ['Cookie'])
    return response


def record(request, action, card=None, **extra):
    emit('action', request.resolver_match.url_name, action, object_id=card.pk if card else '',
         after={'target_name': str(card) if card else 'Волонтёрские карты',
                'path': request.path, **extra}, private=True)
    request.aya_card_recorded = True


@never_cache
@staff_only
@require_GET
def listing(request):
    qs = filter_cards(VolunteerCard.objects.select_related('user', 'edition').filter(user__is_superuser=False), request.GET)
    query = request.GET.copy()
    query.pop('page', None)
    return render(request, 'users/cards/list.html', {
        'page': Paginator(qs.order_by('-edition__start_year', 'number'), 25).get_page(request.GET.get('page')),
        'editions': CardEdition.objects.all(), 'filters': request.GET,
        'directions': Direction.objects.all(), 'schools': School.objects.all(), 'clubs': Club.objects.all(),
        'export_form': CardExportForm(), 'query_string': query.urlencode(),
    })


@never_cache
@staff_only
@require_http_methods(['GET', 'POST'])
def edition_edit(request, pk=None):
    edition = get_object_or_404(CardEdition, pk=pk) if pk else None
    form = CardEditionForm(request.POST if request.method == 'POST' else None, request.FILES or None, instance=edition)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                saved = form.save()
                record(request, 'Сохранил оформление учебного года', year=saved.academic_year,
                       approval_ready=saved.approval_ready)
            messages.success(request, 'Оформление учебного года сохранено.')
            return redirect('card_edition_edit', pk=saved.pk)
        except (IntegrityError, OSError):
            form.add_error(None, 'Не удалось сохранить оформление. Проверьте, не существует ли уже такой учебный год.')
    assets = [{'kind': kind, 'label': label} for kind, label in [
        ('aya_logo', 'Логотип AYA'), ('university_logo', 'Логотип университета'), ('stamp', 'Печать'),
        ('signature', 'Подпись руководителя')] if edition and getattr(edition, kind)]
    return render(request, 'users/cards/edition.html', {'form': form, 'edition': edition, 'asset_list': assets})


@never_cache
@staff_only
@require_GET
def edition_asset(request, pk, kind):
    if kind not in {'aya_logo', 'university_logo', 'stamp', 'signature'}:
        raise Http404
    edition = get_object_or_404(CardEdition, pk=pk)
    field = getattr(edition, kind)
    if not field:
        raise Http404
    try:
        response = FileResponse(field.open('rb'), content_type='image/png')
    except (OSError, ValueError):
        raise Http404
    return private_response(response)


@never_cache
@staff_only
@require_GET
def profile_data(request, pk):
    person = get_object_or_404(eligible_people(), pk=pk)
    return private_response(JsonResponse({
        'first_name': person.first_name, 'last_name': person.last_name, 'patronymic': person.patronymic,
        'course': person.course, 'has_photo': bool(person.photo),
        'number': f'AYA-{current_card_year() % 100:02d}-{person.pk:04d}',
    }))


@never_cache
@staff_only
@require_http_methods(['GET', 'POST'])
def edit(request, pk=None):
    card = get_object_or_404(VolunteerCard.objects.select_related('user', 'edition'), pk=pk, user__is_superuser=False) if pk else None
    person_id = request.GET.get('user', '')
    person = eligible_people().filter(pk=person_id).first() if person_id.isdigit() else None
    year = request.GET.get('year', '')
    edition = CardEdition.objects.filter(start_year=int(year)).first() if year.isdigit() else CardEdition.objects.first()
    form = CardForm(request.POST if request.method == 'POST' else None, request.FILES or None,
                    instance=card, person=person, edition=edition)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                saved = form.save()
                record(request, 'Сохранил данные волонтёрской карты', saved)
            messages.success(request, 'Карта сохранена. Проверьте обе стороны перед выдачей.')
            return redirect('card_detail', pk=saved.pk)
        except ValidationError as error:
            form.add_error(None, error)
        except (IntegrityError, OSError):
            form.add_error(None, 'Не удалось сохранить карту. Проверьте уникальность номера и учебного года.')
    return render(request, 'users/cards/edit.html', {'form': form, 'card': card, 'editions_exist': CardEdition.objects.exists()})


@never_cache
@login_required
@require_GET
def mine(request):
    qs = request.user.volunteer_cards.select_related('user', 'edition').filter(status='issued')
    cards = [card for card in qs if can_preview_card(request.user, card)]
    return render(request, 'users/cards/mine.html', {'cards': cards})


@never_cache
@login_required
@require_GET
def detail(request, pk):
    card = get_object_or_404(VolunteerCard.objects.select_related('user', 'edition'), pk=pk, user__is_superuser=False)
    if not can_preview_card(request.user, card):
        raise Http404
    manager = can_manage_cards(request.user)
    request.aya_audit_target = {'target_name': str(card), 'target_type': 'users.VolunteerCard'}
    return render(request, 'users/cards/detail.html', {'card': card, 'manager': manager,
        'print_errors': preflight(card) if manager else [], 'photo_dpi': photo_dpi(card) if manager else None})


@never_cache
@login_required
@require_GET
def preview(request, pk, side):
    if side not in {'front', 'back'}:
        raise Http404
    card = get_object_or_404(VolunteerCard.objects.select_related('user', 'edition'), pk=pk, user__is_superuser=False)
    if not can_preview_card(request.user, card):
        raise Http404
    try:
        png = preview_png(card, side, viewer=not can_manage_cards(request.user))
    except (OSError, ValueError):
        raise Http404
    return private_response(HttpResponse(png, content_type='image/png'))


@never_cache
@staff_only
@require_POST
def change_status(request, pk):
    action = request.POST.get('action')
    if action not in {'issue', 'revoke'}:
        return HttpResponse('Неизвестное действие.', status=400)
    with transaction.atomic():
        card = get_object_or_404(VolunteerCard.objects.select_for_update().select_related('user', 'edition'),
                                 pk=pk, user__is_superuser=False)
        if action == 'issue':
            errors = preflight(card)
            if errors:
                messages.error(request, ' '.join(errors))
                return redirect('card_detail', pk=card.pk)
            card.status = 'issued'
            card.issued_at = timezone.now()
            card.issued_by = None if request.user.is_superuser else request.user
        else:
            card.status = 'revoked'
        card.save(update_fields=['status', 'issued_at', 'issued_by', 'updated_at'])
        record(request, 'Выдал волонтёрскую карту' if action == 'issue' else 'Отозвал волонтёрскую карту', card)
    messages.success(request, 'Карта выдана: она видна владельцу.' if action == 'issue' else 'Карта отозвана: просмотр владельцем и печать закрыты.')
    return redirect('card_detail', pk=card.pk)


def export_response(request, cards, fmt):
    if fmt == 'zip':
        body, content_type, filename = make_zip(cards), 'application/zip', 'aya-cards.zip'
    else:
        body, content_type, filename = make_pdf(cards, layout=fmt), 'application/pdf', f'aya-cards-{fmt}.pdf'
    response = private_response(HttpResponse(body, content_type=content_type))
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    record(request, 'Выгрузил волонтёрские карты для печати', count=len(cards), format=fmt,
           cards=[str(card) for card in cards])
    return response


@never_cache
@staff_only
@require_POST
def export(request):
    form = CardExportForm(request.POST)
    if form.is_valid():
        return export_response(request, list(form.cleaned_data['cards']), form.cleaned_data['format'])
    return render(request, 'users/cards/export_errors.html', {'form': form}, status=400)


@never_cache
@staff_only
@require_GET
def download(request, pk):
    form = CardExportForm({'cards': [pk], 'format': request.GET.get('format', 'press')})
    if form.is_valid():
        return export_response(request, list(form.cleaned_data['cards']), form.cleaned_data['format'])
    return render(request, 'users/cards/export_errors.html', {'form': form}, status=400)
