"""Keep legacy school leadership and teacher cards in agreement."""
from django.db.models.signals import m2m_changed, pre_save, post_save, post_delete
from django.dispatch import receiver
from django.db.models import Q
from .models import User, School, SchoolTeacher, Direction, Club


@receiver(pre_save, sender=SchoolTeacher)
def remember_teacher(sender, instance, **kwargs):
    instance._previous_assignment = sender.objects.filter(pk=instance.pk).values('school_id', 'member_id').first() if instance.pk else None


@receiver(post_save, sender=SchoolTeacher)
def teacher_saved(sender,instance,**kwargs):
    previous = getattr(instance, '_previous_assignment', None)
    if previous and previous['member_id'] and (previous['member_id'], previous['school_id']) != (instance.member_id, instance.school_id):
        if not SchoolTeacher.objects.filter(**previous).exists():
            old_school = School.objects.filter(pk=previous['school_id']).first()
            if old_school:
                old_school.leaders.remove(previous['member_id'])
    if instance.member_id:
        instance.school.leaders.add(instance.member_id)
        instance.school.members.add(instance.member_id)


@receiver(post_save, sender=School)
def sync_club_direction(sender, instance, **kwargs):
    instance.clubs.update(direction_id=instance.direction_id)


@receiver(post_delete, sender=SchoolTeacher)
def teacher_removed(sender,instance,**kwargs):
    if instance.member_id and not SchoolTeacher.objects.filter(school_id=instance.school_id,member_id=instance.member_id).exists():
        instance.school.leaders.remove(instance.member_id)


@receiver(m2m_changed, sender=User.school_leader_of.through)
def leadership_changed(sender,instance,action,reverse,pk_set,**kwargs):
    if action=='post_remove':
        if reverse:SchoolTeacher.objects.filter(school=instance,member_id__in=pk_set).delete()
        else:SchoolTeacher.objects.filter(member=instance,school_id__in=pk_set).delete()
    elif action=='post_clear':
        if reverse:SchoolTeacher.objects.filter(school=instance,member__isnull=False).delete()
        else:SchoolTeacher.objects.filter(member=instance).delete()


@receiver(m2m_changed, sender=School.members.through)
@receiver(m2m_changed, sender=User.directions.through)
@receiver(m2m_changed, sender=Club.members.through)
def membership_removed(sender, instance, action, reverse, pk_set, **kwargs):
    if action not in {'post_remove','post_clear'}:
        return
    model = School if sender == School.members.through else Club if sender == Club.members.through else Direction
    if isinstance(instance, User):
        teams=model.objects.filter(pk__in=pk_set) if action=='post_remove' else model.objects.filter(Q(leaders=instance)|Q(featured_members=instance)).distinct()
        for team in teams:
            team.leaders.remove(instance)
            team.featured_members.remove(instance)
    else:
        if action=='post_remove':
            instance.leaders.remove(*pk_set)
            instance.featured_members.remove(*pk_set)
        else:
            instance.leaders.clear()
            instance.featured_members.clear()
