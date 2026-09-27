from django import template
register = template.Library()

@register.filter
def safe_social_url(value, network=None):
    from users.social_links import social_url
    return social_url(value,network)

def presentation(person):
    roles = []
    frame = 'volunteer'
    if person.is_superuser:
        roles = [('staff', 'Суперадминистратор')]
    elif person.role in ('worker', 'head_admin'):
        roles = [('staff', 'Начальник отдела' if person.role == 'head_admin' else 'Сотрудник отдела')]
    else:
        leader = person.directions_led.exists()
        teacher = person.school_leader_of.exists() or person.schoolteacher_set.exists()
        club = person.clubs_led.exists()
        if person.role == 'president':
            roles.append(('president', 'Президент'))
        if leader:
            roles.append(('leader', 'Руководитель направления'))
        if teacher:
            roles.append(('teacher', 'Учитель школы'))
        if club:
            roles.append(('club', 'Ответственный за клуб'))
        if person.is_active_volunteer_title:
            roles.append(('active', 'Активный волонтёр'))
        if person.role == 'moderator':
            roles.append(('staff', 'Модератор'))
        frames = [name for name, present in [('leader',leader),('teacher',teacher),('club',club)] if present]
        frame = 'president' if person.role == 'president' else '-'.join(frames) if frames else 'active' if person.is_active_volunteer_title else 'volunteer'
    if not roles:
        roles = [('volunteer', 'Волонтёр')]
    result = {'frame': frame, 'roles': roles}
    return result

@register.inclusion_tag('users/partials/portrait.html')
def portrait(person, size='medium', photo=None):
    return {'person': person, 'size': size, 'portrait_photo':photo, **presentation(person)}

@register.inclusion_tag('users/partials/role_badges.html')
def role_badges(person):
    return presentation(person)


@register.inclusion_tag('users/partials/appointments.html')
def appointments(person):
    from users.models import School
    from django.db.models import Q
    return {'directions':person.directions_led.all(),
            'schools':School.objects.filter(Q(leaders=person)|Q(teachers__member=person)).distinct(),
            'clubs':person.clubs_led.all()}


@register.simple_tag
def deletion_allowed(actor,target):
    from users.deletion import can_delete_user
    return can_delete_user(actor,target)
