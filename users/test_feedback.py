from datetime import date

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import UserUpdateForm, AdminUpdateForm
from .models import User, VolunteerVisit


class FeedbackRegressionTests(TestCase):
    def test_moderation_renders_visit_without_recording_account(self):
        moderator = User.objects.create(username='reviewer', role='moderator',
                                        is_approved=True, qr_code='unused.png')
        candidate = User.objects.create(username='candidate', candidate_approved=True,
                                       qr_code='unused.png')
        VolunteerVisit.objects.create(user=candidate, visit_date=timezone.localdate(),
                                      marked_by=None)
        self.client.force_login(moderator)
        response = self.client.get(reverse('moderator_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'candidate')

    def test_birth_date_html_round_trip(self):
        person = User.objects.create(username='birthday', birth_date=date(2002, 3, 17),
                                    qr_code='unused.png')
        for form_type in (UserUpdateForm, AdminUpdateForm):
            with self.subTest(form=form_type.__name__):
                form = form_type(instance=person)
                self.assertIn('value="2002-03-17"', str(form['birth_date']))
                data = {name: field.value() for name, field in
                        ((name, form[name]) for name in form.fields)
                        if name != 'photo' and field.value() is not None}
                data['birth_date'] = '2002-03-17'
                bound = form_type(data=data, instance=person)
                self.assertTrue(bound.is_valid(), bound.errors)
                bound.save()
                person.refresh_from_db()
                self.assertEqual(person.birth_date, date(2002, 3, 17))
