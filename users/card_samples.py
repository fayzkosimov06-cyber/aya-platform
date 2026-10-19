"""Fictional design proof. No users, cards, files or editions are saved."""
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from .card_models import CardEdition, VolunteerCard, current_card_year
from .profile_qr import public_site_url


def sample_card(edition=None):
    from .models import User
    person = User(first_name='Фирӯз', last_name='Азизов', patronymic='Алиевич')
    card = VolunteerCard(user=person, edition=edition or CardEdition(start_year=current_card_year()),
                         number='AYA-DEMO-0017', first_name=person.first_name, last_name=person.last_name,
                         patronymic=person.patronymic, course=3, status='issued')
    card.photo = SimpleUploadedFile('fictional-portrait.png',
        (Path(__file__).parent / 'card_assets' / 'demo-portrait.png').read_bytes(), content_type='image/png')
    return card


def sample_qr_url():
    # A demo must not send scanners to a guessed real person's profile.
    return public_site_url() + reverse('volunteer_list')
