from __future__ import annotations
from django.db import models

STAFF_ONLY_ROLES = {'worker', 'head_admin'}
PRIVILEGED_ROLES = {'president', 'worker', 'head_admin'}
DIRECT_ACCESS_ROLES = {'president', 'worker', 'head_admin'}


def is_privileged_user(user) -> bool:
    return bool(getattr(user, 'is_authenticated', False) and (getattr(user, 'is_superuser', False) or getattr(user, 'role', None) in PRIVILEGED_ROLES))


def is_candidate_user(user) -> bool:
    return bool(
        getattr(user, 'is_authenticated', False)
        and getattr(user, 'candidate_approved', False)
        and not getattr(user, 'is_approved', False)
    )


def has_full_volunteer_access(user) -> bool:
    if not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False):
        return True
    if getattr(user, 'role', None) in PRIVILEGED_ROLES and not is_candidate_user(user):
        return True
    return bool(getattr(user, 'is_approved', False) or getattr(user, 'volunteer_access', False))


def can_register_for_events(user) -> bool:
    if not getattr(user, 'is_authenticated', False):
        return False
    if getattr(user, 'is_superuser', False):
        return False
    if getattr(user, 'role', None) in STAFF_ONLY_ROLES:
        return False
    if is_candidate_user(user):
        return False
    return has_full_volunteer_access(user)


def can_see_event_catalog(user) -> bool:
    if not getattr(user, 'is_authenticated', False):
        return True
    return has_full_volunteer_access(user)


def can_view_profile(viewer, person) -> bool:
    """Use the same visibility for profiles and their contact/photo/QR endpoints."""
    from .permissions import allowed
    authenticated = getattr(viewer, 'is_authenticated', False)
    if person.is_superuser:
        return bool(authenticated and viewer.is_superuser)
    if authenticated and viewer.pk == person.pk:
        return True
    if person.is_approved:
        return True
    if any(allowed(viewer, code) for code in ('contacts', 'people')):
        return True
    # Admission/visit operators need candidate profiles, not staff applications.
    return bool(person.role in {'volunteer', 'moderator', 'president'}
                and not hasattr(person, 'staff_application')
                and any(allowed(viewer, code) for code in ('admissions', 'visits')))


def can_view_event(user, event) -> bool:
    if can_manage_event(user, event):
        return True
    if not event.is_approved:
        return False
    # Published public announcements stay available to guests and candidates.
    return event.is_public_for_guests or has_full_volunteer_access(user)


def visible_profiles(viewer, people):
    """Queryset equivalent of can_view_profile for linked people on other pages."""
    from .permissions import allowed
    if getattr(viewer,'is_superuser',False):return people
    people=people.exclude(is_superuser=True)
    if not getattr(viewer,'is_authenticated',False):return people.filter(is_approved=True)
    if any(allowed(viewer,code) for code in ('contacts','people')):return people
    visible=models.Q(is_approved=True)|models.Q(pk=viewer.pk)
    if any(allowed(viewer,code) for code in ('admissions','visits')):
        visible |= models.Q(role__in=['volunteer','moderator','president'],staff_application__isnull=True)
    return people.filter(visible)


def visible_school_teachers(viewer, teachers):
    from .models import User
    return teachers.exclude(member__is_superuser=True).filter(
        models.Q(member__isnull=True)|models.Q(member__in=visible_profiles(viewer,User.objects.all())))


def is_public_volunteer(user) -> bool:
    return bool(
        getattr(user, 'is_approved', False)
        and not getattr(user, 'is_superuser', False)
        and getattr(user, 'role', None) not in STAFF_ONLY_ROLES
    )


def is_worker_account(user) -> bool:
    return bool(getattr(user, 'role', None) in STAFF_ONLY_ROLES)


def can_record_visits(user):
    from .permissions import allowed
    return allowed(user,'visits')


def can_manage_members(user):
    from .permissions import allowed
    return allowed(user,'people')


def can_manage_event(user, event):
    from .permissions import allowed, request_context
    req=request_context.get()
    code=getattr(req,'aya_capability',None)
    return allowed(user, code if code and (code.startswith('events_') or code.startswith('points_')) else 'events_edit', event)


def can_create_event(user):
    from .permissions import allowed
    return allowed(user, 'events_edit')

