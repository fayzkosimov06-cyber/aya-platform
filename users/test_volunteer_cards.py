from datetime import date
from io import BytesIO
import json
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
from PIL import Image, ImageChops
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfReader
import pypdfium2 as pdfium
import zxingcpp
from reportlab.lib.units import mm
from .models import User, CardEdition, VolunteerCard, PermissionOverride, JournalEntry, Club
from .card_models import current_card_year
from .card_forms import CardForm, CardEditionForm, CardExportForm
from .card_print import make_pdf, make_zip, preview_png, preflight, imposed_slots, font_size
from .card_storage import normalized_image
from .profile_qr import profile_url


def picture(name='test.png', color='#ccd9e5', size=(900, 1200)):
    stream = BytesIO()
    Image.new('RGB', size, color).save(stream, format='PNG')
    return SimpleUploadedFile(name, stream.getvalue(), content_type='image/png')


class VolunteerCardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.member = User.objects.create(username='card-member', first_name='Фирӯз', last_name='Азизов',
            patronymic='Алиевич', course=3, is_approved=True, photo=picture(), qr_code='qr_codes/not-used.png')
        cls.other = User.objects.create(username='card-other', first_name='Саид', is_approved=True, qr_code='qr_codes/not-used2.png')
        cls.worker = User.objects.create(username='card-worker', role='worker', is_approved=True, qr_code='qr_codes/not-used3.png')
        cls.head = User.objects.create(username='card-head', role='head_admin', is_approved=True, qr_code='qr_codes/not-used4.png')
        cls.president = User.objects.create(username='card-president', role='president', is_approved=True, qr_code='qr_codes/not-used5.png')
        cls.pending_worker = User.objects.create(username='card-not-approved', role='worker', is_approved=False, qr_code='qr_codes/not-used6.png')
        cls.hidden = User.objects.create(username='card-hidden', is_superuser=True, is_approved=True)
        cls.edition = CardEdition.objects.create(start_year=current_card_year(),
            stamp=picture(color='#d6e8f7', size=(400, 400)), signature=picture(size=(700, 160)))
        cls.card = VolunteerCard.objects.create(user=cls.member, edition=cls.edition, number='AYA-TEST-0001',
            first_name=cls.member.first_name, last_name=cls.member.last_name, patronymic=cls.member.patronymic,
            course=3, photo=picture(), status='issued')

    def login(self, user=None):
        self.client.force_login(user or self.worker)

    def data(self, **extra):
        return {'user': self.member.pk, 'edition': self.edition.pk, 'number': self.card.number,
            'first_name': 'Фирӯз', 'last_name': 'Азизов', 'patronymic': 'Алиевич', 'course': 3,
            'photo_source': 'keep', **extra}

    def test_three_name_lines_and_missing_components_never_leave_empty_lines(self):
        self.assertEqual(self.card.name_lines, ['Азизов', 'Фирӯз', 'Алиевич'])
        for family, given, patronymic, expected in [
            ('Азизов','Фирӯз','',['Азизов','Фирӯз']),
            ('','Фирӯз','Алиевич',['Фирӯз','Алиевич']),
            ('','Фирӯз','',['Фирӯз']),
        ]:
            self.card.last_name, self.card.first_name, self.card.patronymic = family, given, patronymic
            self.assertEqual(self.card.name_lines, expected)
            self.assertNotIn('', self.card.name_lines)
            self.assertTrue(make_pdf([self.card]).startswith(b'%PDF'))

    def test_registration_allows_given_and_patronymic_without_family(self):
        from .forms import UserRegisterForm
        form = UserRegisterForm(data={'username':'new-card-student','first_name':'Фирӯз','last_name':'',
            'patronymic':'Алиевич','email':'card@example.test','password1':'Sample-Card-92746!', 'password2':'Sample-Card-92746!'})
        self.assertTrue(form.is_valid(), form.errors)
        person = form.save()
        self.assertEqual(person.get_full_name(), 'Фирӯз Алиевич')
        self.assertFalse(person.is_approved)
        self.assertEqual(person.role, 'volunteer')

    def test_manager_roles_are_checked_on_every_endpoint_and_cannot_be_delegated_to_president(self):
        urls = [reverse('card_list'), reverse('card_create'), reverse('card_edit', args=[self.card.pk]),
            reverse('card_edition_edit', args=[self.edition.pk]),
            reverse('card_edition_asset', args=[self.edition.pk, 'stamp']),
            reverse('card_profile_data', args=[self.member.pk]), reverse('card_download', args=[self.card.pk]),
            reverse('card_sample_preview', args=['front'])]
        for actor in [self.member, self.other, self.president, self.pending_worker]:
            self.login(actor)
            for url in urls:
                self.assertEqual(self.client.get(url).status_code, 403, url)
            self.assertEqual(self.client.post(reverse('card_status',args=[self.card.pk]),{'action':'revoke'}).status_code,403)
            self.assertEqual(self.client.post(reverse('card_export'),{'cards':[self.card.pk],'format':'press'}).status_code,403)
        for actor in [self.worker, self.head, self.hidden]:
            self.login(actor)
            self.assertEqual(self.client.get(reverse('card_list')).status_code, 200)
        PermissionOverride.objects.create(user=self.president, code='people', enabled=True)
        self.login(self.president)
        self.assertEqual(self.client.get(reverse('card_list')).status_code,403)

    def test_owner_can_only_see_their_issued_flattened_preview(self):
        detail = reverse('card_detail', args=[self.card.pk])
        image = reverse('card_preview', args=[self.card.pk, 'back'])
        self.assertEqual(self.client.get(detail).status_code,302)
        self.login(self.other)
        self.assertEqual(self.client.get(detail).status_code,404)
        self.assertEqual(self.client.get(image).status_code,404)
        self.login(self.member)
        response = self.client.get(detail)
        self.assertEqual(response.status_code,200)
        self.assertNotContains(response, reverse('card_download',args=[self.card.pk]))
        self.assertNotContains(response, reverse('card_edition_asset',args=[self.edition.pk,'stamp']))
        preview = self.client.get(image)
        self.assertEqual(preview.status_code,200)
        self.assertEqual(preview['Content-Type'],'image/png')
        self.assertIn('no-store',preview['Cache-Control'])
        self.assertIn('Cookie',preview['Vary'])
        self.assertNotEqual(preview.content, preview_png(self.card,'back',viewer=False))
        self.card.status='draft';self.card.save()
        self.assertEqual(self.client.get(detail).status_code,404)

    def test_assets_are_private_normalized_and_not_reachable_via_public_media(self):
        root = Path(settings.CARD_PRIVATE_ROOT).resolve()
        self.assertTrue(Path(self.card.photo.path).resolve().is_relative_to(root))
        self.assertFalse(root.is_relative_to(Path(settings.MEDIA_ROOT).resolve()))
        with self.assertRaises(ValueError):
            _ = self.edition.stamp.url
        self.login()
        self.assertEqual(self.client.get(reverse('card_edition_edit',args=[self.edition.pk])).status_code,200)
        response = self.client.get(reverse('card_edition_asset',args=[self.edition.pk,'stamp']))
        self.assertEqual(response.status_code,200)
        self.assertIn('no-store',response['Cache-Control'])
        self.assertEqual(self.client.get('/media/'+self.edition.stamp.name).status_code,404)
        self.assertEqual(self.client.get(reverse('card_edition_asset',args=[self.edition.pk,'photo'])).status_code,404)

    def test_invalid_uploads_and_oversized_images_are_rejected(self):
        for upload in [SimpleUploadedFile('x.svg',b'<svg><script/></svg>',content_type='image/svg+xml'),
                       SimpleUploadedFile('x.png',b'not an image',content_type='image/png')]:
            with self.assertRaises(ValidationError):normalized_image(upload)
        result=normalized_image(picture('photo.png',size=(3000,3000)))
        with Image.open(result) as image:
            self.assertLessEqual(max(image.size),2400)
            self.assertFalse(image.getexif())

    def test_separate_photo_and_profile_copy_do_not_modify_real_profile(self):
        before=User.objects.values().get(pk=self.member.pk)
        form=CardForm(data=self.data(photo_source='profile'),instance=self.card)
        self.assertTrue(form.is_valid(),form.errors)
        card=form.save()
        self.assertEqual(card.status,'draft')
        self.assertTrue(Path(card.photo.path).resolve().is_relative_to(Path(settings.CARD_PRIVATE_ROOT).resolve()))
        self.assertEqual(User.objects.values().get(pk=self.member.pk),before)
        form=CardForm(data=self.data(photo_source='upload'),files={'photo':picture('new.png',color='yellow')},instance=card)
        self.assertTrue(form.is_valid(),form.errors)
        form.save()
        self.assertEqual(User.objects.values().get(pk=self.member.pk),before)

    def test_edit_cannot_reassign_owner_year_status_or_role(self):
        later=CardEdition.objects.create(start_year=current_card_year()+1)
        form=CardForm(data=self.data(user=self.other.pk,edition=later.pk,status='issued',role='head_admin',is_superuser='on'),instance=self.card)
        self.assertTrue(form.is_valid(),form.errors)
        card=form.save()
        self.assertEqual(card.user_id,self.member.pk)
        self.assertEqual(card.edition_id,self.edition.pk)
        self.assertEqual(card.status,'draft')
        self.member.refresh_from_db();self.assertEqual(self.member.role,'volunteer')

    def test_issue_requires_approval_photo_and_eligible_person_and_revoke_closes_preview(self):
        self.login()
        self.card.status='draft';self.card.save()
        self.edition.signature='';self.edition.save()
        self.client.post(reverse('card_status',args=[self.card.pk]),{'action':'issue'})
        self.card.refresh_from_db();self.assertEqual(self.card.status,'draft')
        self.edition.signature=picture();self.edition.save()
        response=self.client.post(reverse('card_status',args=[self.card.pk]),{'action':'issue'})
        self.assertEqual(response.status_code,302)
        self.card.refresh_from_db();self.assertEqual(self.card.status,'issued')
        self.assertEqual(self.card.issued_by_id,self.worker.pk)
        self.client.post(reverse('card_status',args=[self.card.pk]),{'action':'revoke'})
        self.card.refresh_from_db();self.assertEqual(self.card.status,'revoked')
        self.login(self.member)
        self.assertEqual(self.client.get(reverse('card_preview',args=[self.card.pk,'front'])).status_code,404)

    def test_candidate_disabled_hidden_and_staff_cannot_receive_a_card(self):
        for field,value in [('is_approved',False),('is_active',False),('is_superuser',True),('role','worker')]:
            person=User.objects.get(pk=self.member.pk)
            setattr(person,field,value)
            self.card.user=person
            self.assertTrue(preflight(self.card),field)
        self.login()
        self.assertEqual(self.client.get(reverse('card_profile_data',args=[self.hidden.pk])).status_code,404)

    def test_csrf_is_enforced_and_get_never_issues_cards(self):
        client=Client(enforce_csrf_checks=True);client.force_login(self.worker)
        status=reverse('card_status',args=[self.card.pk])
        self.assertEqual(client.get(status).status_code,405)
        self.assertEqual(client.post(status,{'action':'revoke'}).status_code,403)
        self.card.refresh_from_db();self.assertEqual(self.card.status,'issued')

    def test_expiry_and_revocation_stop_both_single_and_bulk_exports(self):
        self.login()
        for status in ['draft','revoked']:
            self.card.status=status;self.card.save()
            self.assertEqual(self.client.get(reverse('card_download',args=[self.card.pk])).status_code,400)
        self.card.status='issued';self.card.save()
        future=date(self.edition.start_year+1,9,1)
        with patch('django.utils.timezone.localdate',return_value=future):
            self.assertEqual(self.client.get(reverse('card_download',args=[self.card.pk])).status_code,400)

    def test_pdf_has_true_trim_bleed_embedded_fonts_and_three_separate_name_baselines(self):
        reader=PdfReader(BytesIO(make_pdf([self.card])))
        self.assertEqual(len(reader.pages),2)
        page=reader.pages[0]
        self.assertAlmostEqual(float(page.mediabox.width)/mm,98,places=3)
        self.assertAlmostEqual(float(page.trimbox.width)/mm,86,places=3)
        self.assertAlmostEqual(float(page.trimbox.height)/mm,54,places=3)
        self.assertAlmostEqual(float(page.bleedbox.width)/mm,92,places=3)
        positions=[]
        def visitor(text, cm, tm, font, size):
            for line in self.card.name_lines:
                if line.upper() in text:positions.append((line,tm[5]))
        text=page.extract_text(visitor_text=visitor)
        self.assertIn('ФИРӮЗ',text)
        self.assertEqual(len({round(pos,2) for _,pos in positions}),3)
        self.assertNotIn('Группа',text)
        self.assertNotIn('Гурӯҳ',text)
        embedded=0
        for font in page['/Resources']['/Font'].values():
            descriptor=font.get_object().get('/FontDescriptor')
            if descriptor and '/FontFile2' in descriptor.get_object():embedded+=1
        self.assertGreaterEqual(embedded,2)

    def test_real_pdf_qr_decodes_independently_at_print_resolution(self):
        document=pdfium.PdfDocument(make_pdf([self.card]))
        image=document[0].render(scale=300/72).to_pil()
        decoded=zxingcpp.read_barcode(image)
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded.text,profile_url(self.member))
        self.assertIsNone(zxingcpp.read_barcode(document[1].render(scale=300/72).to_pil()))
        document.close()

    def test_a4_imposition_pairs_every_card_even_on_partial_sheet_and_decodes_all_qr(self):
        cards=[self.card]
        for i in range(8):
            person=User.objects.create(username=f'print-{i}',is_approved=True,qr_code=f'qr_codes/print-{i}.png')
            cards.append(VolunteerCard(user=person,edition=self.edition,number=f'AYA-DEMO-{i}',first_name='Саид',photo=self.card.photo,status='issued'))
        for binding in ['long','short']:
            for front,back in imposed_slots(cards,binding):
                self.assertEqual({id(c) for _,_,c in front},{id(c) for _,_,c in back})
                expected={(r,1-col,id(c)) if binding=='long' else (3-r,col,id(c)) for r,col,c in front}
                self.assertEqual(expected,{(r,col,id(c)) for r,col,c in back})
            pdf=make_pdf(cards,layout='a4-'+binding)
            reader=PdfReader(BytesIO(pdf));self.assertEqual(len(reader.pages),4)
            self.assertAlmostEqual(float(reader.pages[0].mediabox.width)/mm,210,places=3)
            document=pdfium.PdfDocument(pdf)
            for i,expected in [(0,8),(2,1)]:
                image=document[i].render(scale=300/72).to_pil()
                decoded=zxingcpp.read_barcodes(image)
                self.assertEqual(len(decoded),expected)
            document.close()

    def test_exports_are_private_attachments_and_each_zip_pdf_matches_card(self):
        self.login()
        for fmt in ['press','a4-long','a4-short','zip']:
            response=self.client.post(reverse('card_export'),{'cards':[str(self.card.pk)],'format':fmt})
            self.assertEqual(response.status_code,200)
            self.assertIn('attachment',response['Content-Disposition'])
            self.assertIn('no-store',response['Cache-Control'])
            if fmt=='zip':
                with ZipFile(BytesIO(response.content)) as archive:
                    manifest=json.loads(archive.read('cards.json'))
                    self.assertEqual(manifest[0]['number'],self.card.number)
                    self.assertEqual(len(PdfReader(BytesIO(archive.read(manifest[0]['file']))).pages),2)
                    self.assertIn('PRINT-README.txt',archive.namelist())
        entries=JournalEntry.objects.filter(section='card_export',category='action')
        self.assertEqual(entries.count(),4)
        self.assertTrue(all(entry.private for entry in entries))

    def test_export_rejects_invalid_ids_formats_and_over_limit_before_rendering(self):
        self.login()
        for data in [{'cards':['no-such-card'],'format':'press'}, {'cards':[str(self.card.pk)],'format':'evil'}, {'format':'press'}]:
            self.assertEqual(self.client.post(reverse('card_export'),data).status_code,400)
        with patch('users.card_print.make_pdf') as renderer:
            self.client.post(reverse('card_export'),{'cards':[str(self.card.pk)],'format':'../zip'})
            renderer.assert_not_called()
        people=User.objects.bulk_create([User(username=f'limit-{i}',is_approved=True) for i in range(101)])
        cards=VolunteerCard.objects.bulk_create([VolunteerCard(user=person,edition=self.edition,number=f'LIMIT-{i}',first_name='Саид',photo=self.card.photo,status='issued') for i,person in enumerate(people)])
        form=CardExportForm({'cards':[str(card.pk) for card in cards],'format':'press'})
        self.assertFalse(form.is_valid())
        self.assertIn('100',str(form.errors))

    def test_card_number_is_editable_and_normalized_unique_and_year_cannot_be_changed(self):
        form=CardForm(data=self.data(number=' my-card-78 '),instance=self.card)
        self.assertTrue(form.is_valid(),form.errors)
        card=form.save();self.assertEqual(card.number,'MY-CARD-78')
        form=CardForm(data=self.data(user=self.other.pk,number='my-card-78',photo_source='profile'))
        self.assertFalse(form.is_valid());self.assertIn('number',form.errors)
        form=CardEditionForm(data={'start_year':2100,'name_order':'family_first'},instance=self.edition)
        self.assertTrue(form.is_valid(),form.errors)
        self.assertEqual(form.save().start_year,current_card_year())

    def test_filters_include_clubs_and_manual_snapshot_does_not_follow_profile_changes(self):
        club=Club.objects.create(name='Print club');club.members.add(self.member)
        self.login()
        response=self.client.get(reverse('card_list'),{'club':club.pk})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,self.card.number)
        club.members.clear();club.leaders.add(self.member)
        self.assertContains(self.client.get(reverse('card_list'),{'club':club.pk}),self.card.number)
        User.objects.filter(pk=self.member.pk).update(first_name='New profile name')
        self.card.refresh_from_db();self.assertEqual(self.card.first_name,'Фирӯз')

    def test_pdf_images_are_bounded_to_print_resolution_for_large_jobs(self):
        reader=PdfReader(BytesIO(make_pdf([self.card])))
        for page in reader.pages:
            for image in page['/Resources'].get('/XObject',{}).values():
                image=image.get_object()
                if image.get('/Subtype')=='/Image':
                    # The enlarged signature slot is 36 mm wide at up to 600 dpi.
                    self.assertLessEqual(int(image['/Width']),851)
                    self.assertLessEqual(int(image['/Height']),700)

    def test_uploaded_photo_is_used_even_if_profile_source_was_not_changed(self):
        form=CardForm(data=self.data(photo_source='profile'),files={'photo':picture(color='yellow')},instance=self.card)
        self.assertTrue(form.is_valid(),form.errors)
        card=form.save()
        with card.photo.open('rb') as stream:
            with Image.open(stream) as image:self.assertEqual(image.convert('RGB').getpixel((0,0)),(255,255,0))

    def test_staff_create_issue_view_and_download_workflow(self):
        person=User.objects.create(username='complete-card-flow',is_approved=True,photo=picture(),qr_code='qr_codes/workflow.png')
        self.login()
        response=self.client.post(reverse('card_create'),self.data(user=person.pk,number='AYA-FLOW-001',photo_source='profile',last_name='',is_superuser='on',status='issued'))
        self.assertEqual(response.status_code,302)
        card=VolunteerCard.objects.get(user=person)
        self.assertEqual(card.status,'draft')
        self.client.post(reverse('card_status',args=[card.pk]),{'action':'issue'})
        card.refresh_from_db();self.assertEqual(card.status,'issued')
        self.assertEqual(self.client.get(reverse('card_download',args=[card.pk])).status_code,200)
        self.login(person)
        self.assertEqual(self.client.get(reverse('card_detail',args=[card.pk])).status_code,200)
        self.assertEqual(self.client.get(reverse('card_preview',args=[card.pk,'back'])).status_code,200)
        self.assertEqual(self.client.get(reverse('card_download',args=[card.pk])).status_code,403)
        person.refresh_from_db();self.assertFalse(person.is_superuser)

    def test_cards_are_discoverable_in_staff_dashboard_sidebar_and_profile(self):
        self.login()
        dashboard = self.client.get(reverse('admin_dashboard'))
        self.assertContains(dashboard, 'data-card-management-entry')
        self.assertContains(dashboard, reverse('card_list'))
        self.assertContains(self.client.get(reverse('my_profile')), 'Управлять картами')
        listing = self.client.get(reverse('card_list'))
        self.assertContains(listing, 'aria-current="page"')
        self.assertContains(listing, reverse('card_sample_preview', args=['front']))
        self.assertContains(listing, reverse('card_sample_preview', args=['back']))
        self.assertContains(listing, 'Вымышленные имя и фотография')
        self.assertContains(self.client.get(reverse('public_profile', args=[self.member.pk])),
                            reverse('card_detail', args=[self.card.pk]))
        self.login(self.president)
        self.assertNotContains(self.client.get(reverse('admin_dashboard')), 'data-card-management-entry')

    def test_profile_card_is_visible_to_owner_and_staff_only_and_draft_is_not_exposed(self):
        detail = reverse('card_detail', args=[self.card.pk])
        self.login(self.member)
        self.assertContains(self.client.get(reverse('my_profile')), detail)
        self.assertContains(self.client.get(reverse('my_profile')), 'Моя волонтёрская карта')
        self.card.status = 'draft'
        self.card.save(update_fields=['status'])
        response = self.client.get(reverse('my_profile'))
        self.assertContains(response, 'после выдачи сотрудниками отдела')
        self.assertNotContains(response, detail)
        self.login(self.other)
        response = self.client.get(reverse('public_profile', args=[self.member.pk]))
        self.assertNotContains(response, 'data-profile-card-entry')
        self.assertNotContains(response, self.card.number)
        self.login()
        response = self.client.get(reverse('public_profile', args=[self.member.pk]))
        self.assertContains(response, detail)

    def test_first_visit_has_live_design_proof_and_setup_without_creating_records(self):
        self.card.delete()
        self.edition.delete()
        self.login()
        response = self.client.get(reverse('card_list'))
        self.assertContains(response, 'Начать первый выпуск')
        self.assertContains(response, '<details class="vc-design" open>')
        self.assertNotContains(response, 'data-card-selection')
        self.assertContains(response, reverse('card_edition_create'))
        counts = (User.objects.count(), CardEdition.objects.count(), VolunteerCard.objects.count(), JournalEntry.objects.count())
        files = set(Path(settings.CARD_PRIVATE_ROOT).rglob('*'))
        for side in ['front', 'back']:
            response = self.client.get(reverse('card_sample_preview', args=[side]))
            self.assertEqual(response.status_code, 200)
            self.assertIn('no-store', response['Cache-Control'])
            if side == 'front':
                decoded = zxingcpp.read_barcode(Image.open(BytesIO(response.content)))
                self.assertIsNotNone(decoded)
                self.assertEqual(decoded.text, 'https://aya.test' + reverse('volunteer_list'))
        self.assertEqual(counts, (User.objects.count(), CardEdition.objects.count(), VolunteerCard.objects.count(), JournalEntry.objects.count()))
        self.assertEqual(files, set(Path(settings.CARD_PRIVATE_ROOT).rglob('*')))
        self.assertEqual(self.client.get(reverse('card_sample_preview', args=['invalid'])).status_code, 404)

    def test_preview_and_print_name_baselines_match_and_both_qr_codes_scan(self):
        dpi = 300
        scale = dpi / 25.4
        pdf = pdfium.PdfDocument(make_pdf([self.card]))
        rendered = pdf[0].render(scale=dpi/72).to_pil().crop(
            (round(6*scale), round(6*scale), round(92*scale), round(60*scale)))
        preview = Image.open(BytesIO(preview_png(self.card, 'front', dpi=dpi))).convert('RGB')
        def text_rows(image):
            rows = []
            for y in range(round(17*scale), round(34*scale)):
                ink = sum(1 for x in range(round(30*scale), round(58*scale))
                          if all(c < 160 for c in image.getpixel((x,y))[:3]))
                if ink > 5:
                    if not rows or y-rows[-1][-1] > 8:
                        rows.append([y])
                    else:
                        rows[-1].append(y)
            return rows
        print_rows, preview_rows = text_rows(rendered), text_rows(preview)
        self.assertEqual(len(print_rows), 3)
        self.assertEqual(len(preview_rows), 3)
        for left, right in zip(print_rows, preview_rows):
            self.assertLessEqual(abs(left[0]-right[0]), 3)
            self.assertLessEqual(abs(left[-1]-right[-1]), 3)
        for image in [pdf[0].render(scale=dpi/72).to_pil(),
                      Image.open(BytesIO(preview_png(self.card, 'front', dpi=dpi)))]:
            decoded = zxingcpp.read_barcode(image)
            self.assertIsNotNone(decoded)
            self.assertEqual(decoded.text, profile_url(self.member))
        pdf.close()

    def test_back_department_text_and_full_stamp_signature_spaces_in_png_and_pdf(self):
        self.edition.stamp = picture(color='#fa00fa', size=(600,600))
        self.edition.signature = picture(color='#00b400', size=(1400,280))
        data = make_pdf([self.card])
        text = ' '.join(PdfReader(BytesIO(data)).pages[1].extract_text().split())
        self.assertIn('Шуъбаи кор бо ҷавонони ДДТТ ба номи Абуали ибни сино', text)
        self.assertIn('Муҳр', text)
        self.assertIn('Signature', text)
        dpi, scale = 300, 300/25.4
        document = pdfium.PdfDocument(data)
        printed = document[1].render(scale=dpi/72).to_pil().crop(
            (round(6*scale),round(6*scale),round(92*scale),round(60*scale))).convert('RGB')
        preview = Image.open(BytesIO(preview_png(self.card,'back',dpi=dpi))).convert('RGB')
        for image in [printed, preview]:
            self.assertIsNone(zxingcpp.read_barcode(image))
            red, green, blue = image.split()
            seal_mask = ImageChops.multiply(ImageChops.multiply(
                red.point(lambda c:255 if c>220 else 0),blue.point(lambda c:255 if c>220 else 0)),
                green.point(lambda c:255 if c<50 else 0))
            signature_mask = ImageChops.multiply(ImageChops.multiply(
                green.point(lambda c:255 if c>120 else 0),red.point(lambda c:255 if c<50 else 0)),
                blue.point(lambda c:255 if c<50 else 0))
            self.assertIsNotNone(seal_mask.getbbox())
            self.assertIsNotNone(signature_mask.getbbox())
            left, top, right, bottom = [v/scale for v in seal_mask.getbbox()]
            self.assertGreaterEqual(left,7.8)
            self.assertLessEqual(right,31.2)
            self.assertGreaterEqual(top,28.0)
            self.assertLessEqual(bottom,44.5)
            self.assertGreaterEqual(bottom-top,15.6)
            left, top, right, bottom = [v/scale for v in signature_mask.getbbox()]
            self.assertGreaterEqual(left,42.8)
            self.assertLessEqual(right,79.2)
            self.assertGreaterEqual(top,32.6)
            self.assertLessEqual(bottom,43.2)
        document.close()

    def test_long_full_name_stays_left_of_front_qr_and_extreme_names_are_flagged(self):
        from reportlab.pdfbase import pdfmetrics
        self.card.last_name = 'Абдурахмонов'
        self.card.first_name = 'Абдурашид'
        self.card.patronymic = 'Сайфуллозода'
        self.assertEqual(preflight(self.card), [])
        names = {line.upper() for line in self.card.name_lines}
        positions = {}
        def inspect(text, cm, tm, font, size):
            value = text.strip()
            if value in names:
                positions[value] = (tm[4]/mm-6, size)
        PdfReader(BytesIO(make_pdf([self.card]))).pages[0].extract_text(visitor_text=inspect)
        self.assertEqual(set(positions), names)
        for name, (left, size) in positions.items():
            self.assertGreaterEqual(left,30)
            self.assertLessEqual(left+pdfmetrics.stringWidth(name,'AYA-Bold',size)/mm,57.6)
            self.assertGreaterEqual(size,5.3)
        self.card.last_name = 'Ж'*150
        self.assertTrue(any('слишком длинная' in error for error in preflight(self.card)))
