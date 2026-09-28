"""Stable subject keys for presentation-only journal grouping."""
import re

def subject_key(section, object_id, before, after, actor_id=None):
    data={**(before or {}),**(after or {})}
    parents={'events.EventPhoto':('event','events.Event'),'events.EventVideo':('event','events.Event'),'events.EventAttendance':('event','events.Event'),'events.EventHero':('event','events.Event'),'users.SchoolTeacher':('school','users.School'),'users.SchoolLesson':('school','users.School'),'users.ClubMeeting':('club','users.Club'),'users.ContributionAward':('work','users.ContributionWork'),'users.PermissionOverride':('user','users.User'),'users.ActivityPeriod':('user','users.User')}
    if section in parents:
        field,model=parents[section];value=data.get(field) or data.get(field+'_id')
        if str(value).isdigit():return model+':'+str(value)
    if section in {'users.User','users.Direction','users.School','users.Club','users.ContributionWork','events.Event'} and str(object_id).isdigit():return section+':'+str(object_id)
    if section in {'public_profile','open_profile_photo','reveal_phone','reveal_birthday','open_contact'} and str(object_id).isdigit():return 'users.User:'+str(object_id)
    path=data.get('path','')
    for pattern,model in [(r'^/(?:profile|people)/(\d+)(?:/|$)','users.User'),(r'^/events/(\d+)(?:/|$)','events.Event'),(r'^/schools/(\d+)(?:/|$)','users.School'),(r'^/directions/(\d+)(?:/|$)','users.Direction'),(r'^/clubs/(\d+)(?:/|$)','users.Club'),(r'^/points/works/(\d+)(?:/|$)','users.ContributionWork')]:
        match=re.match(pattern,path)
        if match:return model+':'+match.group(1)
    if section in {'my_profile','profile_edit'} and actor_id:return 'users.User:'+str(actor_id)
    if section:return 'section:'+section+(':'+str(object_id) if object_id else '')
    return ''
