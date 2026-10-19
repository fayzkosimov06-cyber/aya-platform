"""One layout for raster previews and vector, font-embedded print PDFs.

All coordinates are millimetres from the card's top left. Print sheets retain
86 x 54 mm trim, 3 mm bleed and cut marks. No generated artwork is embedded.
"""
import functools
import json
import threading
import zipfile
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageChops
import qrcode
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader
from reportlab.lib.colors import HexColor, CMYKColor
from reportlab.lib.units import mm
from .profile_qr import profile_url

W, H, BLEED, MARK = 86, 54, 3, 3
NAVY, MUTED, PALE, WHITE = '#153858', '#566F88', '#E8F0F6', '#FFFFFF'
FONTS = Path(__file__).parent / 'card_assets' / 'fonts'
_font_lock = threading.Lock()


@functools.lru_cache(maxsize=1)
def fonts():
    with _font_lock:
        for name, filename in [('AYA-Regular', 'NotoSans-Regular.ttf'), ('AYA-Bold', 'NotoSans-Bold.ttf')]:
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(FONTS / filename)))
    return True


def font_size(text, width, preferred, bold=False):
    fonts()
    length = pdfmetrics.stringWidth(text, 'AYA-Bold' if bold else 'AYA-Regular', preferred) / mm
    return min(preferred, preferred * width / length) if length else preferred


def opened_image(value, *, trim=False):
    if hasattr(value, 'storage'):
        with value.open('rb') as stream:
            with Image.open(stream) as source:
                source.load()
                image = ImageOps.exif_transpose(source).convert('RGBA')
    else:
        with Image.open(value) as source:
            source.load()
            image = source.convert('RGBA')
    if trim:
        white = Image.new('RGBA', image.size, 'white')
        white.alpha_composite(image)
        difference = ImageChops.difference(white.convert('RGB'), Image.new('RGB', image.size, 'white'))
        bounds = difference.point(lambda p: 255 if p > 22 else 0).getbbox()
        if bounds:
            image = image.crop(bounds)
    return image


def artwork(card):
    root = Path(settings.BASE_DIR) / 'static' / 'img'
    return {
        'aya': opened_image(card.edition.aya_logo or root / 'aya-logo-2026.png', trim=True),
        'university': opened_image(card.edition.university_logo or root / 'logo_university.png', trim=True),
        'photo': opened_image(card.photo) if card.photo else None,
        'stamp': opened_image(card.edition.stamp, trim=True) if card.edition.stamp else None,
        'signature': opened_image(card.edition.signature, trim=True) if card.edition.signature else None,
    }


def preflight(card):
    from .card_access import eligible_person
    fonts()
    errors = []
    if not eligible_person(card.user):
        errors.append('Карта доступна только допущенному действующему волонтёру.')
    if card.edition.valid_until < timezone.localdate():
        errors.append('Учебный год карты уже закончился.')
    if not card.name_lines:
        errors.append('Заполните ФИО.')
    if any(font_size(line.upper(), 50, 10, True) < 5.3 for line in card.name_lines):
        errors.append('Одна из частей ФИО слишком длинная для читаемой печати. Проверьте её в редакторе карты.')
    if any(ord(char) not in pdfmetrics.getFont('AYA-Bold').face.charWidths for line in card.name_lines + [card.number] for char in line.upper()):
        errors.append('В ФИО есть символы, которые не поддерживает печатный шрифт. Проверьте написание.')
    if font_size(card.number, 43, 7, True) < 4.5:
        errors.append('Номер слишком длинный для карты. Используйте более короткий номер.')
    if not card.photo:
        errors.append('Добавьте фотографию.')
    if not card.edition.approval_ready:
        errors.append('Для этого учебного года ещё не загружены печать и подпись.')
    if not errors:
        try:
            artwork(card)
        except (OSError, ValueError):
            errors.append('Один из файлов карты недоступен. Проверьте фото и оформление учебного года.')
    return errors


def photo_dpi(card):
    if not card.photo:
        return None
    try:
        with card.photo.open('rb') as stream:
            with Image.open(stream) as image:
                return round(min(image.width / (22 / 25.4), image.height / (28 / 25.4)))
    except (OSError, ValueError):
        return None


@functools.lru_cache(maxsize=256)
def qr_matrix(url):
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_Q, box_size=1, border=4)
    code.add_data(url)
    code.make(fit=True)
    return tuple(tuple(row) for row in code.get_matrix())


def image_placement(image, x, y, width, height, crop=False):
    if crop:
        ratio = width / height
        iw, ih = image.size
        if iw / ih > ratio:
            cut = ih * ratio
            image = image.crop(((iw - cut) / 2, 0, (iw + cut) / 2, ih))
        else:
            cut = iw / ratio
            top = (ih - cut) * .4
            image = image.crop((0, top, iw, top + cut))
        return image, x, y, width, height
    scale = min(width / image.width, height / image.height)
    tw, th = image.width * scale, image.height * scale
    return image, x + (width - tw) / 2, y + (height - th) / 2, tw, th


class PDFPainter:
    def __init__(self, document, x=0, y=0):
        self.c, self.x, self.y = document, x * mm, y * mm

    def rect(self, x, y, w, h, fill):
        self.c.setFillColor(HexColor(fill))
        self.c.rect(self.x + x*mm, self.y + (H-y-h)*mm, w*mm, h*mm, stroke=0, fill=1)

    def line(self, x, y, w, color=PALE):
        self.c.setStrokeColor(HexColor(color))
        self.c.setLineWidth(.12*mm)
        self.c.line(self.x+x*mm, self.y+(H-y)*mm, self.x+(x+w)*mm, self.y+(H-y)*mm)

    def text(self, text, x, y, size, *, bold=False, color=NAVY, align='left', width=None):
        if width is not None:
            size = font_size(text, width, size, bold)
        self.c.setFillColor(HexColor(color))
        self.c.setFont('AYA-Bold' if bold else 'AYA-Regular', size)
        method = {'left': self.c.drawString, 'right': self.c.drawRightString, 'center': self.c.drawCentredString}[align]
        method(self.x+x*mm, self.y+(H-y)*mm-size*.78, text)

    def image(self, image, x, y, w, h, *, crop=False):
        image, x, y, w, h = image_placement(image, x, y, w, h, crop)
        # Bound memory and file size in large jobs; 600 dpi is ample at card scale.
        image = image.copy()
        image.thumbnail((max(1, round(w/25.4*600)), max(1, round(h/25.4*600))), Image.Resampling.LANCZOS)
        self.c.drawImage(ImageReader(image), self.x+x*mm, self.y+(H-y-h)*mm,
                         w*mm, h*mm, mask='auto')

    def qr(self, matrix, x, y, size):
        self.rect(x, y, size, size, WHITE)
        # QR is vector and pure black, avoiding four-colour registration problems.
        self.c.setFillColor(CMYKColor(0, 0, 0, 1))
        unit = size / len(matrix)
        for row, values in enumerate(matrix):
            start = None
            for col in range(len(values) + 1):
                dark = col < len(values) and values[col]
                if dark and start is None:
                    start = col
                elif not dark and start is not None:
                    self.c.rect(self.x+(x+start*unit)*mm, self.y+(H-y-(row+1)*unit)*mm,
                                (col-start)*unit*mm, unit*mm, stroke=0, fill=1)
                    start = None


class RasterPainter:
    def __init__(self, dpi=180):
        self.scale = dpi / 25.4
        self.dpi = dpi
        self.im = Image.new('RGB', (round(W*self.scale), round(H*self.scale)), 'white')
        self.draw = ImageDraw.Draw(self.im)

    def rect(self, x, y, w, h, fill):
        s = self.scale
        self.draw.rectangle([round(x*s), round(y*s), round((x+w)*s)-1, round((y+h)*s)-1], fill=fill)

    def line(self, x, y, w, color=PALE):
        s = self.scale
        self.draw.line([x*s, y*s, (x+w)*s, y*s], fill=color, width=max(1, round(.12*s)))

    def text(self, text, x, y, size, *, bold=False, color=NAVY, align='left', width=None):
        if width is not None:
            size = font_size(text, width, size, bold)
        font = ImageFont.truetype(str(FONTS / ('NotoSans-Bold.ttf' if bold else 'NotoSans-Regular.ttf')),
                                  max(1, round(size*self.dpi/72)))
        anchor = {'left': 'lt', 'right': 'rt', 'center': 'mt'}[align]
        self.draw.text((x*self.scale, y*self.scale), text, font=font, fill=color, anchor=anchor)

    def image(self, image, x, y, w, h, *, crop=False):
        image, x, y, w, h = image_placement(image, x, y, w, h, crop)
        image = image.resize((max(1, round(w*self.scale)), max(1, round(h*self.scale))), Image.Resampling.LANCZOS)
        self.im.paste(image, (round(x*self.scale), round(y*self.scale)), image.getchannel('A') if image.mode == 'RGBA' else None)

    def qr(self, matrix, x, y, size):
        self.rect(x, y, size, size, WHITE)
        unit = size / len(matrix)
        for row, values in enumerate(matrix):
            for col, dark in enumerate(values):
                if dark:
                    self.rect(x+col*unit, y+row*unit, unit, unit, '#000000')


def paint_card(p, card, side, assets=None):
    fonts()
    a = assets or artwork(card)
    p.rect(-BLEED, -BLEED, W+2*BLEED, H+2*BLEED, WHITE)
    year = card.edition.academic_year
    if side == 'front':
        p.image(a['aya'], 4.5, 3, 16.5, 10)
        p.image(a['university'], 74, 2.5, 7.8, 10.5)
        p.text('КОРТИ ВОЛОНТЁР', 25, 3.2, 7.6, bold=True, width=46)
        p.text('Карта волонтёра', 25, 7.3, 5.8, color=MUTED)
        p.text('Volunteer card', 25, 10.2, 5.8, color=MUTED)
        if a['photo']:
            p.image(a['photo'], 4.5, 17, 22, 28, crop=True)
        else:
            p.rect(4.5, 17, 22, 28, PALE)
            p.text('Фото', 15.5, 29, 8, color=MUTED, align='center')
        names = card.name_lines
        first_y = {1: 26, 2: 22, 3: 18.5}.get(len(names), 18.5)
        for i, value in enumerate(names):
            p.text(value.upper(), 31, first_y+i*7.0, 10, bold=True, width=50)
        if card.course:
            p.text('Курс · Year', 31, 41, 5.5, color=MUTED)
            p.text(str(card.course), 48, 39.8, 10, bold=True)
        p.rect(-BLEED, 47, W+2*BLEED, 7+BLEED, PALE)
        p.text('№ '+card.number, 4.5, 49.3, 7, bold=True, width=43)
        p.text(year, 81.5, 49.1, 7.8, bold=True, align='right')
    else:
        p.rect(57, -BLEED, 29+BLEED, H+2*BLEED, PALE)
        p.image(a['aya'], 4.5, 3.5, 12, 8)
        p.image(a['university'], 19.5, 3, 6.6, 8.8)
        p.text(year, 53, 4.2, 7.1, bold=True, align='right')
        for i, text in enumerate(['Соли таҳсил', 'Учебный год', 'Academic year']):
            p.text(text, 53, 8.2+i*2.15, 4.2, color=MUTED, align='right')
        p.text('Тасдиқ', 4.5, 17, 8.1, bold=True)
        p.text('Подтверждение · Approval', 4.5, 21.4, 5.0, color=MUTED, width=48)
        if a['stamp']:
            p.image(a['stamp'], 7, 26, 20, 16)
        if a['signature']:
            p.image(a['signature'], 28, 30, 23, 9)
        p.line(4.5, 43.5, 48, '#7890A7')
        for i, text in enumerate(['Имзои роҳбар', 'Подпись руководителя', 'Director’s signature']):
            p.text(text, 4.5, 45+i*2.25, 4.3, color=MUTED)
        for i, text in enumerate(['ПРОФИЛ', 'ПРОФИЛЬ', 'PROFILE']):
            p.text(text, 71.5, 6.5+i*3.4, 5.8, bold=True, color=MUTED, align='center')
        p.qr(qr_matrix(profile_url(card.user)), 60, 20, 23)
        p.text(card.number, 71.5, 47.3, 6.3, bold=True, align='center', width=25)


def preview_png(card, side, *, viewer=False, dpi=180):
    painter = RasterPainter(dpi)
    paint_card(painter, card, side)
    if viewer or card.status != 'issued':
        label = 'ДЛЯ ПРОСМОТРА' if viewer else 'ЧЕРНОВИК'
        overlay = Image.new('RGBA', painter.im.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(overlay)
        font = ImageFont.truetype(str(FONTS / 'NotoSans-Bold.ttf'), round(dpi/9))
        draw.text((overlay.width/2, overlay.height/2), label, fill=(75, 100, 125, 65),
                  font=font, anchor='mm', stroke_width=1)
        overlay = overlay.rotate(18, resample=Image.Resampling.BICUBIC)
        painter.im = Image.alpha_composite(painter.im.convert('RGBA'), overlay).convert('RGB')
    output = BytesIO()
    painter.im.save(output, format='PNG', dpi=(dpi, dpi))
    return output.getvalue()


def crop_marks(c, x, y):
    c.setStrokeColor(CMYKColor(0, 0, 0, 1))
    c.setLineWidth(.2)
    for yy in [y, y+H]:
        for x1, x2 in [(x-5.5, x-3.5), (x+W+3.5, x+W+5.5)]:
            c.line(x1*mm, yy*mm, x2*mm, yy*mm)
    for xx in [x, x+W]:
        for y1, y2 in [(y-5.5, y-3.5), (y+H+3.5, y+H+5.5)]:
            c.line(xx*mm, y1*mm, xx*mm, y2*mm)


def imposed_slots(cards, binding='long'):
    """8 cards/sheet: keep card pairs registered, including partially filled sheets."""
    for start in range(0, len(cards), 8):
        chunk = cards[start:start+8]
        front = [(i//2, i%2, item) for i, item in enumerate(chunk)]
        if binding == 'long':
            back = [(row, 1-col, item) for row, col, item in front]
        else:
            back = [(3-row, col, item) for row, col, item in front]
        yield front, back


def make_pdf(cards, *, layout='press'):
    cards = list(cards)
    if not cards or len(cards) > 100:
        raise ValueError('Выгрузка должна содержать от 1 до 100 карт.')
    if layout not in {'press', 'a4-long', 'a4-short'}:
        raise ValueError('Неизвестный формат печати.')
    fonts()
    stream = BytesIO()
    size = (98*mm, 66*mm) if layout == 'press' else (210*mm, 297*mm)
    c = canvas.Canvas(stream, pagesize=size, pageCompression=1, pdfVersion=(1, 4), initialFontName='AYA-Regular')
    c.setTitle('AYA - Volunteer cards')
    c.setAuthor('AYA')
    if layout == 'press':
        for card in cards:
            a = artwork(card)
            for side in ['front', 'back']:
                c.setTrimBox((6*mm, 6*mm, 92*mm, 60*mm))
                c.setBleedBox((3*mm, 3*mm, 95*mm, 63*mm))
                c.setCropBox((0, 0, 98*mm, 66*mm))
                paint_card(PDFPainter(c, 6, 6), card, side, a)
                crop_marks(c, 6, 6)
                c.showPage()
    else:
        for front, back in imposed_slots(cards, 'short' if layout == 'a4-short' else 'long'):
            # Symmetric grid: 2 x 4; 98 x 66 mm cells include bleed and marks.
            for side, slots in [('front', front), ('back', back)]:
                for row, col, card in slots:
                    x, y = 7 + col*98 + 6, 297 - 16.5 - (row+1)*66 + 6
                    paint_card(PDFPainter(c, x, y), card, side)
                    crop_marks(c, x, y)
                c.showPage()
    c.save()
    return stream.getvalue()


PRINT_INSTRUCTIONS = '''AYA — волонтёрские карты
Готовый размер: 86 × 54 мм. Вылеты: 3 мм со всех сторон.
PDF для типографии: страницы 98 × 66 мм включают метки реза;
TrimBox задаёт 86 × 54 мм, BleedBox — 92 × 60 мм.
Страницы идут парами: лицевая сторона, оборот той же карты.
Шрифты встроены. QR-код векторный. Изображения — в исходном доступном качестве.
Цвет: RGB (QR — чистый чёрный). PDF не обозначается как PDF/X.
Точный профиль CMYK, PDF/X, скругление углов и материал согласуются с типографией.
А4: 8 карт на листе, затем обороты тех же карт; пустые позиции сохраняются.
Выбирайте файл под переворот по длинной либо короткой стороне.
Печатать в масштабе 100%, без «вписать в страницу».
Сначала проверьте совмещение на одном пробном листе.
'''


def make_zip(cards):
    stream = BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('PRINT-README.txt', PRINT_INSTRUCTIONS.encode('utf-8-sig'))
        manifest = []
        for card in cards:
            filename = f'aya-card-{card.pk.hex}.pdf'
            archive.writestr(filename, make_pdf([card]))
            manifest.append({'file': filename, 'number': card.number, 'full_name': card.full_name,
                             'academic_year': card.edition.academic_year})
        archive.writestr('cards.json', json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8'))
    return stream.getvalue()
