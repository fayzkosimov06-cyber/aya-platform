"""Synthetic-account regressions; never reads production users or logs."""
import json
from unittest.mock import patch
from django import forms
from django.test import TestCase, Client
from django.urls import reverse
from .forms import UserUpdateForm, AdminUpdateForm
from .models import User, JournalEntry, PermissionOverride

class ProfileAuditTests(TestCase):
    def setUp(self):
        self.member=User.objects.create(username="audit-member",is_approved=True,qr_code="unused.png")
        self.other=User.objects.create(username="audit-other",is_approved=True,qr_code="unused.png")
        self.root=User.objects.create(username="audit-root",is_superuser=True,is_staff=True,is_approved=True,qr_code="unused.png")

    def data(self, person=None, admin=False):
        person=person or self.member
        form=(AdminUpdateForm(instance=person,actor=self.root) if admin else UserUpdateForm(instance=person))
        return {name:form[name].value() for name in form.fields if name!="photo" and form[name].value() is not None}

    def test_invalid_profile_fields_visible_in_both_editors(self):
        for route,actor,admin in [("profile_edit",self.member,False),("admin_edit_user",self.root,True)]:
            for field,value in [("instagram","javascript:alert(1)"),("linkedin","not a URL"),("birth_date","2999-01-01"),("phone","1"*21)]:
                with self.subTest(route=route,field=field):
                    self.client.force_login(actor)
                    response=self.client.post(reverse(route,args=[self.member.pk] if admin else []),{**self.data(admin=admin),field:value})
                    self.assertEqual(response.status_code,200)
                    self.assertIn(field,response.context["form"].errors)
                    self.assertContains(response,"profile-error-summary")
                    self.assertContains(response,'href="#id_'+field+'"')
                    self.member.refresh_from_db()
                    self.assertNotEqual(str(getattr(self.member,field)),value)

    def test_non_field_error_is_visible(self):
        self.client.force_login(self.member)
        with patch.object(UserUpdateForm,"clean",side_effect=forms.ValidationError("Synthetic form error")):
            response=self.client.post(reverse("profile_edit"),self.data())
        self.assertContains(response,"Synthetic form error")

    def test_form_failure_logged_with_codes_without_submitted_value(self):
        self.client.force_login(self.member)
        marker="javascript:private-audit-marker"
        self.client.post(reverse("profile_edit"),{**self.data(),"instagram":marker})
        entries=JournalEntry.objects.filter(actor=self.member,section="profile_edit")
        self.assertEqual(entries.count(),1)
        entry=entries.get()
        self.assertEqual(entry.category,"failure")
        self.assertIn("instagram",entry.after["validation_codes"])
        self.assertNotIn(marker,json.dumps(entry.after))
        self.assertTrue(entry.private)

    def test_self_post_does_not_change_security_fields_or_other_account(self):
        self.client.force_login(self.member)
        response=self.client.post(reverse("profile_edit"),{**self.data(),"first_name":"Edited", "pk":self.other.pk,"id":self.other.pk,"user":self.other.pk,"role":"head_admin","is_superuser":"on","is_staff":"on","is_approved":"on","volunteer_access":"on","candidate_approved":"on","permission_overrides":"permissions"})
        self.assertEqual(response.status_code,302)
        self.member.refresh_from_db();self.other.refresh_from_db()
        self.assertEqual(self.member.first_name,"Edited")
        self.assertEqual(self.other.first_name,"")
        self.assertEqual(self.member.role,"volunteer")
        self.assertFalse(self.member.is_superuser);self.assertFalse(self.member.is_staff)
        self.assertFalse(self.member.volunteer_access);self.assertFalse(self.member.candidate_approved)
        self.assertFalse(PermissionOverride.objects.filter(user=self.member).exists())

    def test_direct_admin_and_rights_post_denied_for_member_and_candidate(self):
        for approved in (True,False):
            self.member.is_approved=approved;self.member.candidate_approved=not approved;self.member.save()
            self.client.force_login(self.member)
            for name,args,data in [("admin_edit_user",[self.other.pk],{**self.data(self.other,True),"role":"head_admin"}),("update_user_role",[self.other.pk],{"role":"head_admin"}),("rights_manage",[],{"targets":[self.member.pk],"permissions":"on","people":"on","scope":"all"}),("grant_volunteer_access",[self.member.pk],{}),("mark_candidate_visit",[self.member.pk],{}),("staff_applications",[],{})]:
                response=self.client.post(reverse(name,args=args),data)
                self.assertIn(response.status_code,(302,403,404),name)
            self.other.refresh_from_db();self.member.refresh_from_db()
            self.assertEqual(self.other.role,"volunteer");self.assertFalse(self.member.volunteer_access)
            self.assertFalse(PermissionOverride.objects.exists())

    def test_profile_and_rights_csrf_enforced(self):
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.root)
        for name,args in [("profile_edit",[]),("admin_edit_user",[self.member.pk]),("rights_manage",[])]:
            self.assertEqual(secure.post(reverse(name,args=args),{}).status_code,403)

    def test_decoy_post_has_no_effect(self):
        self.client.force_login(self.member)
        self.assertContains(self.client.get(reverse("cookie_vault")),"никаких")
        result=self.client.post(reverse("cookie_vault"),{"role":"head_admin","permissions":"on","targets":[self.member.pk]})
        self.assertEqual(result.status_code,405)
        self.member.refresh_from_db();self.assertEqual(self.member.role,"volunteer")
        self.assertFalse(PermissionOverride.objects.exists())

    def test_legacy_choices_are_rejected_with_visible_errors(self):
        self.member.city="Synthetic legacy city";self.member.save()
        self.client.force_login(self.member)
        response=self.client.post(reverse("profile_edit"),{**self.data(),"city":""})
        self.assertIn("city",response.context["form"].errors)
        self.assertContains(response,'href="#id_city"')
        self.member.refresh_from_db();self.assertEqual(self.member.city,"Synthetic legacy city")

    def test_candidate_can_edit_without_admission_or_privilege_change(self):
        self.member.is_approved=False;self.member.candidate_approved=True;self.member.save()
        self.client.force_login(self.member)
        self.assertEqual(self.client.post(reverse("profile_edit"),{**self.data(),"first_name":"Candidate edited"}).status_code,302)
        self.member.refresh_from_db();self.assertEqual(self.member.first_name,"Candidate edited")
        self.assertFalse(self.member.is_approved);self.assertFalse(self.member.volunteer_access)

    def test_stock_model_form_and_web_validation_difference_is_reproducible(self):
        # Django's default admin uses model validation, not the site's additional rules.
        stock=forms.modelform_factory(User,fields=['birth_date','instagram','linkedin'])
        data={'birth_date':'2999-01-01','instagram':'javascript:synthetic','linkedin':'not a URL'}
        self.assertTrue(stock(data,instance=self.member).is_valid())
        form=UserUpdateForm({**self.data(),**data},instance=self.member)
        self.assertFalse(form.is_valid())
        self.assertTrue({'birth_date','instagram','linkedin'}.issubset(form.errors))

    def test_staff_custom_fields_respect_database_lengths(self):
        self.member.role='worker';self.member.save()
        for field in ('job_title','office_location'):
            length=User._meta.get_field(field).max_length
            form=UserUpdateForm({**self.data(),field:'x'*(length+1)},instance=self.member)
            self.assertFalse(form.is_valid())
            self.assertIn(field,form.errors)

    def test_diagnostic_is_read_only_and_omits_personal_values(self):
        from .profile_diagnostics import diagnose_profile
        self.member.phone='synthetic-private-phone';self.member.instagram='javascript:synthetic-private-value';self.member.save()
        before=User.objects.values().get(pk=self.member.pk)
        journals=JournalEntry.objects.count()
        result=diagnose_profile(self.member.username)
        self.assertTrue(result['read_only'])
        self.assertIn('instagram',result['current_self_form']['codes'])
        self.assertNotIn('synthetic-private',json.dumps(result))
        self.assertEqual(before,User.objects.values().get(pk=self.member.pk))
        self.assertEqual(journals,JournalEntry.objects.count())

    def test_profile_update_does_not_accept_invalid_photo(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.force_login(self.member)
        data={**self.data(),'photo':SimpleUploadedFile('photo.jpg',b'<script>synthetic</script>',content_type='image/jpeg')}
        response=self.client.post(reverse('profile_edit'),data)
        self.assertIn('photo',response.context['form'].errors)
        self.assertContains(response,'href="#id_photo"')
        self.member.refresh_from_db();self.assertFalse(self.member.photo)

    def test_registration_post_does_not_grant_role_or_full_access(self):
        from .forms import UserRegisterForm
        form=UserRegisterForm({'username':'audit-register','first_name':'Synthetic','last_name':'Member','email':'synthetic@example.invalid','password1':'SyntheticRegistration-9216','password2':'SyntheticRegistration-9216','role':'head_admin','is_superuser':'on','is_staff':'on','is_approved':'on','volunteer_access':'on','candidate_approved':'on'})
        self.assertTrue(form.is_valid(),form.errors)
        person=form.save()
        self.assertEqual(person.role,'volunteer')
        for field in ('is_superuser','is_staff','is_approved','volunteer_access','candidate_approved'):self.assertFalse(getattr(person,field))

    def test_weak_password_rejected_and_source_settings_enable_validators(self):
        import ast
        from pathlib import Path
        from django.conf import settings
        from .forms import UserRegisterForm
        data={'username':'audit-register','first_name':'Synthetic','last_name':'Member','email':'synthetic@example.invalid','password1':'123','password2':'123'}
        self.assertFalse(UserRegisterForm(data).is_valid())
        for path in [settings.BASE_DIR/'aya_platform/settings.py',settings.BASE_DIR/'aya_platform/settings.py.example']:
            tree=ast.parse(path.read_text(encoding='utf-8-sig'))
            nodes=[node.value for node in tree.body if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='AUTH_PASSWORD_VALIDATORS' for target in node.targets)]
            self.assertTrue(nodes)
            self.assertGreaterEqual(len(ast.literal_eval(nodes[-1])),4)
