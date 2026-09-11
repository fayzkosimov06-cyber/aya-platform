"""The rating and profile use the same set of eligible event evaluations."""
from decimal import Decimal, ROUND_HALF_UP
from django.db.models import Exists, OuterRef, Avg, Count, Subquery
from django.core.paginator import Paginator
from django.shortcuts import render
from .access import has_full_volunteer_access, STAFF_ONLY_ROLES
from .models import User
from events.models import Event, EventEvaluation


def eligible_evaluations():
    participant = Event.participants.through.objects.filter(event_id=OuterRef('event_id'), user_id=OuterRef('volunteer_id'))
    return EventEvaluation.objects.filter(
        event__is_completed=True, event__is_approved=True,
        total_score__gte=1, total_score__lte=5,
    ).annotate(is_registered=Exists(participant)).filter(is_registered=True)


def rounded_score(value):
    return Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def rating_rows():
    aggregates = eligible_evaluations().filter(volunteer_id=OuterRef('pk')).order_by().values('volunteer_id').annotate(
        average=Avg('total_score'), total=Count('pk'), events=Count('event_id', distinct=True),
    )
    users = User.objects.filter(is_approved=True, is_superuser=False).exclude(role__in=STAFF_ONLY_ROLES).annotate(
        rating_average=Subquery(aggregates.values('average')[:1]),
        rating_evaluations=Subquery(aggregates.values('total')[:1]),
        rating_events=Subquery(aggregates.values('events')[:1]),
    ).filter(rating_average__isnull=False)
    rows=[]
    for user in users:
        rows.append({'member':user,'score':rounded_score(user.rating_average),'evaluations':user.rating_evaluations,'events':user.rating_events})
    # Ties are defined by the score visible to users, not invisible decimals.
    rows.sort(key=lambda row:(-row['score'], row['member'].last_name.casefold(),row['member'].first_name.casefold(),row['member'].pk))
    previous=None;place=0
    for index,row in enumerate(rows,1):
        if row['score']!=previous:place=index
        row['place']=place;previous=row['score']
    return rows


def rating_view(request):
    if not has_full_volunteer_access(request.user):
        return render(request,'users/rating.html',{'rating_locked':True})
    rows=rating_rows()
    page=Paginator(rows,30).get_page(request.GET.get('page'))
    return render(request,'users/rating.html',{
        'rating_locked':False,'rating_page':page,'ranked_count':len(rows),
        'leaders':[row for row in rows if row['place']<=3] if page.number==1 else [],
        'my_rating':next((row for row in rows if row['member'].pk==request.user.pk),None),
    })
