from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Max
from django.http import HttpResponseForbidden, HttpResponseBadRequest
from django.shortcuts import render, redirect, get_object_or_404
from .access import can_manage_members
from .models import HomePage, HomeSlide, HomeQuote, User


class StyledForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'


class HomePageForm(StyledForm):
    class Meta:
        model = HomePage
        fields = ['quotes_per_view']


class HomeSlideForm(StyledForm):
    class Meta:
        model = HomeSlide
        fields = ['image', 'caption']


class HomeQuoteForm(StyledForm):
    author_type = forms.ChoiceField(choices=[('member', 'Участник сайта'), ('external', 'Учёный или другой автор')], label='Кто автор?')
    member = forms.ModelChoiceField(queryset=User.objects.none(), required=False, label='Выберите участника')

    class Meta:
        model = HomeQuote
        fields = ['author_type', 'member', 'text', 'author_name', 'author_role', 'photo', 'source_url']
        widgets = {'text': forms.Textarea(attrs={'rows': 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['member'].queryset = User.objects.filter(is_approved=True, is_superuser=False).order_by('last_name','first_name','username')
        self.fields['member'].widget.attrs['class'] = 'form-control use-select2'
        self.fields['member'].label_from_instance = lambda user: f'{user.get_full_name() or user.username} · {user.get_role_display()} · @{user.username}'
        if not self.is_bound:
            self.initial['author_type'] = 'member' if self.instance.member_id else 'external'

    def clean(self):
        data = super().clean()
        if data.get('author_type') == 'member':
            member=data.get('member')
            if not member:
                self.add_error('member', 'Выберите участника сайта.')
            else:
                data['author_name'] = member.get_full_name() or member.username
            data['source_url'] = ''
        else:
            data['member'] = None
            if not (data.get('author_name') or '').strip():
                self.add_error('author_name', 'Укажите имя автора.')
        return data


@login_required
@transaction.atomic
def home_manage_view(request):
    if not can_manage_members(request.user):
        return HttpResponseForbidden('Недостаточно прав.')
    page, _ = HomePage.objects.get_or_create(pk=1)
    slide = get_object_or_404(HomeSlide, page=page, pk=request.GET['slide']) if request.GET.get('slide') else None
    quote = get_object_or_404(HomeQuote, page=page, pk=request.GET['quote']) if request.GET.get('quote') else None
    settings_form = HomePageForm(instance=page)
    slide_form = HomeSlideForm(instance=slide)
    quote_form = HomeQuoteForm(instance=quote)
    upload_errors = []
    if request.method == 'POST':
        action=request.POST.get('action')
        if action == 'settings':
            settings_form=HomePageForm(request.POST,instance=page)
            if settings_form.is_valid():
                settings_form.save(); messages.success(request,'Режим показа цитат сохранён.'); return redirect('home_manage')
        elif action == 'upload':
            files=request.FILES.getlist('images')
            cleaned=[]
            if not files: upload_errors.append('Выберите фотографии.')
            for file in files:
                try: cleaned.append(forms.ImageField().clean(file))
                except forms.ValidationError as exc: upload_errors.extend(exc.messages)
            if not upload_errors:
                start=(page.slides.aggregate(n=Max('order'))['n'] or 0)+1
                for i,file in enumerate(cleaned): HomeSlide.objects.create(page=page,image=file,order=start+i)
                messages.success(request,'Фотографии добавлены.'); return redirect('home_manage')
        elif action in ['save_slide','save_quote']:
            model,formclass=(HomeSlide,HomeSlideForm) if action=='save_slide' else (HomeQuote,HomeQuoteForm)
            obj=get_object_or_404(model,page=page,pk=request.POST['id']) if request.POST.get('id') else None
            form=formclass(request.POST,request.FILES,instance=obj)
            if form.is_valid():
                record=form.save(commit=False); record.page=page
                if not record.pk: record.order=(model.objects.filter(page=page).aggregate(n=Max('order'))['n'] or 0)+1
                record.save();messages.success(request,'Изменения сохранены.');return redirect('home_manage')
            if action=='save_slide':slide_form=form;slide=obj
            else:quote_form=form;quote=obj
        elif action in ['delete','toggle','up','down']:
            model={'slide':HomeSlide,'quote':HomeQuote}.get(request.POST.get('kind'))
            if model is None:return HttpResponseBadRequest('Неизвестный раздел.')
            obj=get_object_or_404(model,page=page,pk=request.POST.get('id'))
            if action=='delete':obj.delete()
            elif action=='toggle':obj.is_active=not obj.is_active;obj.save(update_fields=['is_active'])
            else:
                records=list(model.objects.filter(page=page).select_for_update())
                index=next(i for i,item in enumerate(records) if item.pk==obj.pk)
                other=index+(-1 if action=='up' else 1)
                if 0<=other<len(records):records[index],records[other]=records[other],records[index]
                for i,item in enumerate(records):item.order=i
                model.objects.bulk_update(records,['order'])
            return redirect('home_manage')
        else:return HttpResponseBadRequest('Неизвестное действие.')
    return render(request,'users/home_manage.html',{'page':page,'settings_form':settings_form,'slide_form':slide_form,'quote_form':quote_form,'slide':slide,'quote':quote,'slides':page.slides.all(),'quotes':page.quotes.select_related('member').all(),'upload_errors':upload_errors})
