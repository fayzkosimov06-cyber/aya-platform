from django import template
register = template.Library()

def presentation(person):
    cached = getattr(person, '_aya_presentation', None)
    if cached is not None:
        return cached
    roles = []
    frame = 'volunteer'
    if person.is_superuser:
        roles = [('staff', 'Суперадминистратор')]
    elif person.role in ('worker', 'head_admin'):
        roles = [('staff', 'Начальник отдела' if person.role == 'head_admin' else 'Сотрудник отдела')]
    else:
        leader = person.directions_led.exists()
        teacher = person.school_leader_of.exists()
        if person.role == 'president':
            roles.append(('president', 'Президент'))
        if leader:
            roles.append(('leader', 'Руководитель направления'))
        if teacher:
            roles.append(('teacher', 'Учитель школы'))
        if person.is_active_volunteer_title:
            roles.append(('active', 'Активный волонтёр'))
        if person.role == 'moderator':
            roles.append(('staff', 'Модератор'))
        frame = ('president' if person.role == 'president' else 'combined' if leader and teacher else
                 'leader' if leader else 'teacher' if teacher else 'active' if person.is_active_volunteer_title else 'volunteer')
    if not roles:
        roles = [('volunteer', 'Волонтёр')]
    result = {'frame': frame, 'roles': roles}
    person._aya_presentation = result
    return result

@register.inclusion_tag('users/partials/portrait.html')
def portrait(person, size='medium'):
    return {'person': person, 'size': size, **presentation(person)}

@register.inclusion_tag('users/partials/role_badges.html')
def role_badges(person):
    return presentation(person)
