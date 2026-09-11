"""Shared public statistics and contact policy for home and About."""
from .access import has_full_volunteer_access, STAFF_ONLY_ROLES
from .models import User, School, Direction


def actual_counts():
    from events.models import Event
    people=User.objects.filter(is_approved=True, is_superuser=False)
    volunteers=people.exclude(role__in=STAFF_ONLY_ROLES)
    return {
        'volunteers':volunteers.count(),
        'active':volunteers.filter(is_active_volunteer_title=True).count(),
        'workers':people.filter(role__in=['worker','head_admin']).count(),
        'leaders':people.filter(role='leader').count(),
        'school_leaders':people.filter(school_leader_of__isnull=False).distinct().count(),
        'schools':School.objects.count(), 'directions':Direction.objects.count(),
        'events':Event.objects.filter(is_approved=True).count(),
    }


def public_stats(about):
    if about and about.stat_items.exists():
        records=list(about.stat_items.filter(is_active=True).order_by('order','id'))
        counts=actual_counts() if any(item.source!='manual' for item in records) else {}
        return [{'number':item.number if item.source=='manual' else counts.get(item.source,0), 'label':item.label, 'icon':item.icon} for item in records]
    counts=actual_counts()
    return [{'number':counts[key], 'label':label, 'icon':icon} for key,label,icon in [
        ('volunteers','Волонтёров','fas fa-users'),('events','Мероприятий','fas fa-calendar-check'),('directions','Направлений','fas fa-compass'),('schools','Школ','fas fa-graduation-cap')]]


def public_contacts(about,user):
    if not about:return []
    result=[]
    for link in about.contact_links.filter(is_active=True).order_by('order','id'):
        private=link.platform=='telegram' or link.requires_volunteer_access
        if link.platform in ['instagram','facebook']:private=False
        if not private or has_full_volunteer_access(user):result.append(link)
    return result


def video_embed_url(raw):
    from urllib.parse import urlsplit, parse_qs
    import re
    if not raw:return ''
    parsed=urlsplit(raw)
    if parsed.scheme not in ['http','https']:return ''
    host=(parsed.hostname or '').lower()
    key=''
    if host in ['youtube.com','www.youtube.com','m.youtube.com','youtube-nocookie.com','www.youtube-nocookie.com']:
        key=parse_qs(parsed.query).get('v',[''])[0] if parsed.path=='/watch' else parsed.path.split('/')[-1]
    elif host=='youtu.be':key=parsed.path.strip('/')
    if key and re.fullmatch(r'[A-Za-z0-9_-]{11}',key):return 'https://www.youtube-nocookie.com/embed/'+key
    if host in ['vimeo.com','www.vimeo.com','player.vimeo.com']:
        key=parsed.path.rstrip('/').split('/')[-1]
        if key.isdigit():return 'https://player.vimeo.com/video/'+key
    return ''
