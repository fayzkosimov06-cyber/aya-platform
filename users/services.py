from datetime import timedelta
from django.utils import timezone


def grant_access(user, actor, *, old=False):
    """Caller locks the user inside a transaction; repeated grants do not reset dates."""
    if user.is_approved:
        return False
    now = timezone.now()
    user.candidate_approved = True
    user.volunteer_access = True
    user.is_approved = True
    user.is_old_volunteer = old
    user.volunteer_access_granted_at = now
    user.volunteer_access_granted_by = actor
    user.new_volunteer_until = None if old else now + timedelta(days=14)
    user.save(update_fields=['candidate_approved', 'volunteer_access', 'is_approved', 'is_old_volunteer', 'volunteer_access_granted_at', 'volunteer_access_granted_by', 'new_volunteer_until'])
    return True
