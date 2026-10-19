from django.db.models import Q


def can_manage_cards(user):
    # Deliberately independent of delegated capabilities: print approval is staff-only.
    return bool(user.is_authenticated and user.is_active and
                (user.is_superuser or (user.is_approved and user.role in {'worker', 'head_admin'})))


def eligible_person(user):
    return bool(user.is_active and user.is_approved and not user.is_superuser
                and user.role not in {'worker', 'head_admin'})


def eligible_people():
    from .models import User
    return User.objects.filter(is_active=True, is_approved=True, is_superuser=False).exclude(role__in=['worker', 'head_admin'])


def can_preview_card(actor, card):
    return can_manage_cards(actor) or (actor.is_authenticated and actor.pk == card.user_id
                                     and card.status == 'issued' and eligible_person(card.user))


def profile_card_context(actor, person):
    """A visible profile entry without exposing card data to other volunteers."""
    manager = can_manage_cards(actor)
    if actor.is_authenticated and actor.pk == person.pk and manager:
        return {'profile_card_management': True}
    if not eligible_person(person) or not (manager or (actor.is_authenticated and actor.pk == person.pk)):
        return {}
    from .card_models import current_card_year
    cards = person.volunteer_cards.select_related('user', 'edition')
    if not manager:
        cards = cards.filter(status='issued')
    card = cards.order_by('-edition__start_year', '-updated_at').first()
    return {'profile_card_visible': True, 'profile_card_manager': manager,
            'profile_volunteer_card': card,
            'profile_card_has_current': bool(card and card.edition.start_year == current_card_year())}


def filter_cards(cards, query):
    text = query.get('q', '').strip()[:150]
    if text:
        cards = cards.filter(Q(first_name__icontains=text) | Q(last_name__icontains=text)
                             | Q(patronymic__icontains=text) | Q(number__icontains=text)
                             | Q(user__username__icontains=text))
    for key, field in [('year', 'edition__start_year'), ('course', 'course')]:
        value = query.get(key, '')
        if str(value).isdigit():
            cards = cards.filter(**{field: value})
    for key, fields in [
        ('direction', ['user__directions', 'user__directions_led']),
        ('school', ['user__aya_schools', 'user__school_leader_of', 'user__schoolteacher__school_id']),
        ('club', ['user__aya_clubs', 'user__clubs_led']),
    ]:
        value = query.get(key, '')
        if str(value).isdigit():
            match = Q()
            for field in fields:
                match |= Q(**{field: value})
            cards = cards.filter(match)
    if query.get('faculty'):
        cards = cards.filter(user__faculty=query['faculty'][:200])
    if query.get('status') in {'draft', 'issued', 'revoked'}:
        cards = cards.filter(status=query['status'])
    return cards.distinct()
