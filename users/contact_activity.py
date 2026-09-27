import re
from urllib.parse import urlsplit
from django.http import Http404, JsonResponse
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.cache import never_cache
from django.shortcuts import get_object_or_404, redirect
from .models import User
from .views import can_view_field, is_privileged_viewer
from .social_links import social_url
from .journal import emit


def destination(person, network):
    value=getattr(person,network,'').strip()
    if network=='telegram':
        if re.fullmatch(r'@?[A-Za-z0-9_]{3,64}',value): return 'https://t.me/'+value.lstrip('@')
        url=social_url(value)
        return url if url and urlsplit(url).hostname in {'t.me','telegram.me','www.t.me'} else ''
    return social_url(value,network)


@never_cache
@require_GET
def open_contact(request, pk, network):
    if network not in {'telegram','instagram','linkedin'}: raise Http404
    person=get_object_or_404(User,pk=pk)
    if person.is_superuser and not request.user.is_superuser: raise Http404
    if not (person.is_approved or person.candidate_approved) and request.user!=person and not is_privileged_viewer(request.user): raise Http404
    if not can_view_field(request.user,person,getattr(person,network+'_privacy')): raise Http404
    url=destination(person,network)
    if not url: raise Http404
    emit('contact','public_profile','Перешёл по ссылке',object_id=person.pk,after={'target_name':str(person),'network':network,'path':request.path},private=True)
    return redirect(url)


@never_cache
@require_POST
def reveal_phone(request, pk):
    person=get_object_or_404(User,pk=pk)
    if person.is_superuser and not request.user.is_superuser: raise Http404
    if not (person.is_approved or person.candidate_approved) and request.user!=person and not is_privileged_viewer(request.user): raise Http404
    if not can_view_field(request.user,person,person.phone_privacy) or not person.phone: raise Http404
    emit('contact','public_profile','Раскрыл номер телефона',object_id=person.pk,after={'target_name':str(person),'network':'phone'},private=True)
    response=JsonResponse({'phone':person.phone})
    response['Cache-Control']='no-store, private'
    return response
