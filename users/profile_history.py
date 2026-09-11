from django.core.paginator import Paginator
from .rating import eligible_evaluations


def evaluation_history(request, member):
    evaluations = eligible_evaluations().filter(volunteer=member)
    events = list(evaluations.order_by('event__title', 'event_id').values('event_id', 'event__title').distinct())
    selected = request.GET.get('event', '')
    valid_ids = {str(event['event_id']) for event in events}
    invalid = bool(selected and selected not in valid_ids)
    if invalid:
        evaluations = evaluations.none()
    elif selected:
        evaluations = evaluations.filter(event_id=int(selected))
    page = Paginator(evaluations.select_related('event', 'evaluator').order_by('-updated_at', '-pk'), 10).get_page(request.GET.get('evaluations_page'))
    return {'history_page': page, 'history_events': events, 'history_event': selected, 'history_invalid': invalid}
