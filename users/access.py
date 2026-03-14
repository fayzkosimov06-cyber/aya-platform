from __future__ import annotations

STAFF_ONLY_ROLES = {'leader', 'worker', 'head_admin'}
PRIVILEGED_ROLES = {'leader', 'moderator', 'president', 'worker', 'head_admin'}
DIRECT_ACCESS_ROLES = {'leader', 'president', 'worker', 'head_admin'}


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
    return not is_candidate_user(user)


def is_public_volunteer(user) -> bool:
    return bool(
        getattr(user, 'is_approved', False)
        and not getattr(user, 'is_superuser', False)
        and getattr(user, 'role', None) not in STAFF_ONLY_ROLES
    )


def is_worker_account(user) -> bool:
    return bool(getattr(user, 'role', None) in STAFF_ONLY_ROLES)
