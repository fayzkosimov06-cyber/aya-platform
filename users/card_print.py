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
NAVY, MUTED, PALE, WHITE = '#0C2F62', '#60758E', '#E6F0F7', '#FFFFFF'
FONTS = Path(__file__).parent / 'card_assets' / 'fonts'
NAME_WIDTH, NAME_SIZE = 20, 10.8
PHOTO_WIDTH, PHOTO_HEIGHT = 21.5, 28.7
STRIPE_WIDTH = 17
DEPARTMENT_LINES = ('Шуъбаи кор бо ҷавонони ДДТТ', 'ба номи Абуали ибни сино')
UNIVERSITY_LINES = ('ДДТТ', 'ба номи', 'Абуали', 'ибни Сино')
_font_lock = threading.Lock()


@functools.lru_cache(maxsize=1)
def fonts():
    with _font_lock:
        for name, filename in [('AYA-Regular', 'NotoSans-Regular.ttf'),
                               ('AYA-Medium', 'NotoSans-Medium.ttf'), ('AYA-Bold', 'NotoSans-Bold.ttf')]:
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(FONTS / filename)))
    return True


def font_name(bold=False, medium=False):
    return 'AYA-Bold' if bold else 'AYA-Medium' if medium else 'AYA-Regular'


def font_size(text, width, preferred, bold=False, *, medium=False):
    fonts()
    length = pdfmetrics.stringWidth(text, font_name(bold, medium), preferred) / mm
    return min(preferred, preferred * width / length) if length else preferred


def opened_image(value, *, trim=False):
    if hasattr(value, 'storage'):
        if getattr(value, '_committed', True):
            with value.storage.open(value.name, 'rb') as stream:
                data = stream.read()
        else:
            # The bundled proof (and an unsaved upload) can be rendered on both
            # sides without closing the caller's in-memory file after the front.
            value.file.seek(0)
            data = value.file.read()
            value.file.seek(0)
        with Image.open(BytesIO(data)) as source:
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


def badge_image(image):
    """Remove only border-connected white backing, retaining white crest details.

    This is a rendering copy: the uploaded original is never changed. Padding
    connects all outside edges, even when trimming made the shield touch them.
    """
    image = image.convert('RGBA').copy()
    red, green, blue, alpha = image.split()
    white = ImageChops.multiply(ImageChops.multiply(
        red.point(lambda c: 255 if c >= 242 else 0),
        green.point(lambda c: 255 if c >= 242 else 0)),
        blue.point(lambda c: 255 if c >= 242 else 0))
    padded = Image.new('L', (image.width+2, image.height+2), 255)
    padded.paste(white, (1, 1))
    ImageDraw.floodfill(padded, (0, 0), 128)
    outside = padded.crop((1, 1, image.width+1, image.height+1))
    image.putalpha(ImageChops.multiply(alpha, outside.point(lambda c: 0 if c == 128 else 255)))
    return image


def artwork(card):
    root = Path(settings.BASE_DIR) / 'static' / 'img'
    return {
        'aya': opened_image(card.edition.aya_logo or root / 'aya-logo-2026.png', trim=True),
        'university': badge_image(opened_image(card.edition.university_logo or root / 'logo_university.png', trim=True)),
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
    if any(font_size(line, NAME_WIDTH, NAME_SIZE, medium=True) < 5.3 for line in card.name_lines):
        errors.append('Одна из частей ФИО слишком длинная для читаемой печати. Проверьте её в редакторе карты.')
    if any(ord(char) not in pdfmetrics.getFont('AYA-Medium').face.charWidths
           for line in card.name_lines for char in line) or any(
               ord(char) not in pdfmetrics.getFont('AYA-Bold').face.charWidths for char in card.number):
        errors.append('В ФИО есть символы, которые не поддерживает печатный шрифт. Проверьте написание.')
    if font_size(card.number, 60, 7.5, True) < 4.5:
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
                return round(min(image.width / (PHOTO_WIDTH / 25.4), image.height / (PHOTO_HEIGHT / 25.4)))
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

    def rect(self, x, y, w, h, fill, *, radius=0):
        self.c.setFillColor(HexColor(fill))
        args = (self.x + x*mm, self.y + (H-y-h)*mm, w*mm, h*mm)
        if radius:
            self.c.roundRect(*args, radius*mm, stroke=0, fill=1)
        else:
            self.c.rect(*args, stroke=0, fill=1)

    def line(self, x, y, w, color=PALE, *, vertical=False):
        self.c.setStrokeColor(HexColor(color))
        self.c.setLineWidth(.12*mm)
        self.c.line(self.x+x*mm, self.y+(H-y)*mm,
                    self.x+(x if vertical else x+w)*mm, self.y+(H-y-w if vertical else H-y)*mm)

    def polygon(self, points, fill):
        path = self.c.beginPath()
        path.moveTo(self.x+points[0][0]*mm, self.y+(H-points[0][1])*mm)
        for x, y in points[1:]:
            path.lineTo(self.x+x*mm, self.y+(H-y)*mm)
        path.close()
        self.c.setFillColor(HexColor(fill))
        self.c.drawPath(path, stroke=0, fill=1)

    def text(self, text, x, y, size, *, bold=False, medium=False, color=NAVY, align='left', width=None):
        if width is not None:
            size = font_size(text, width, size, bold, medium=medium)
        self.c.setFillColor(HexColor(color))
        face = font_name(bold, medium)
        self.c.setFont(face, size)
        method = {'left': self.c.drawString, 'right': self.c.drawRightString, 'center': self.c.drawCentredString}[align]
        # Both painters use the font's capital height to position the baseline.
        # An estimated baseline here and an ink-top anchor in Pillow used to make
        # the on-site preview differ noticeably from the downloaded PDF.
        cap = pdfmetrics.getFont(face).face.capHeight / 1000
        method(self.x+x*mm, self.y+(H-y)*mm-size*cap, text)

    def image(self, image, x, y, w, h, *, crop=False, radius=0):
        image, x, y, w, h = image_placement(image, x, y, w, h, crop)
        # Bound memory and file size in large jobs; 600 dpi is ample at card scale.
        image = image.copy()
        image.thumbnail((max(1, round(w/25.4*600)), max(1, round(h/25.4*600))), Image.Resampling.LANCZOS)
        self.c.saveState()
        if radius:
            clip = self.c.beginPath()
            clip.roundRect(self.x+x*mm, self.y+(H-y-h)*mm, w*mm, h*mm, radius*mm)
            self.c.clipPath(clip, stroke=0)
        self.c.drawImage(ImageReader(image), self.x+x*mm, self.y+(H-y-h)*mm,
                         w*mm, h*mm, mask='auto')
        self.c.restoreState()

    def qr(self, matrix, x, y, size):
        self.rect(x, y, size, size, WHITE, radius=1.5)
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

    def rect(self, x, y, w, h, fill, *, radius=0):
        s = self.scale
        box = [round(x*s), round(y*s), round((x+w)*s)-1, round((y+h)*s)-1]
        if radius:
            self.draw.rounded_rectangle(box, radius=round(radius*s), fill=fill)
        else:
            self.draw.rectangle(box, fill=fill)

    def line(self, x, y, w, color=PALE, *, vertical=False):
        s = self.scale
        self.draw.line([x*s, y*s, (x if vertical else x+w)*s,
                        (y+w if vertical else y)*s], fill=color, width=max(1, round(.12*s)))

    def polygon(self, points, fill):
        self.draw.polygon([(round(x*self.scale), round(y*self.scale)) for x, y in points], fill=fill)

    def text(self, text, x, y, size, *, bold=False, medium=False, color=NAVY, align='left', width=None):
        if width is not None:
            size = font_size(text, width, size, bold, medium=medium)
        face = font_name(bold, medium)
        filename = {'AYA-Regular': 'NotoSans-Regular.ttf', 'AYA-Medium': 'NotoSans-Medium.ttf',
                    'AYA-Bold': 'NotoSans-Bold.ttf'}[face]
        font = ImageFont.truetype(str(FONTS / filename),
                                  max(1, round(size*self.dpi/72)))
        anchor = {'left': 'ls', 'right': 'rs', 'center': 'ms'}[align]
        cap = pdfmetrics.getFont(face).face.capHeight / 1000
        self.draw.text((x*self.scale, y*self.scale + size*self.dpi/72*cap),
                       text, font=font, fill=color, anchor=anchor)

    def image(self, image, x, y, w, h, *, crop=False, radius=0):
        image, x, y, w, h = image_placement(image, x, y, w, h, crop)
        image = image.resize((max(1, round(w*self.scale)), max(1, round(h*self.scale))), Image.Resampling.LANCZOS)
        mask = image.getchannel('A') if image.mode == 'RGBA' else None
        if radius:
            corners = Image.new('L', image.size, 0)
            ImageDraw.Draw(corners).rounded_rectangle((0, 0, image.width-1, image.height-1),
                                                     radius=round(radius*self.scale), fill=255)
            mask = ImageChops.multiply(mask, corners) if mask else corners
        self.im.paste(image, (round(x*self.scale), round(y*self.scale)), mask)

    def qr(self, matrix, x, y, size):
        self.rect(x, y, size, size, WHITE, radius=1.5)
        unit = size / len(matrix)
        for row, values in enumerate(matrix):
            for col, dark in enumerate(values):
                if dark:
                    self.rect(x+col*unit, y+row*unit, unit, unit, '#000000')


def paint_card(p, card, side, assets=None, *, qr_url=None):
    fonts()
    a = assets or artwork(card)
    p.rect(-BLEED, -BLEED, W+2*BLEED, H+2*BLEED, WHITE)
    year = card.edition.academic_year
    # The opposite back edge is deliberate: front and reverse form one card.
    stripe_x = 0 if side == 'front' else W-STRIPE_WIDTH
    p.rect(-BLEED if side == 'front' else stripe_x, -BLEED,
           STRIPE_WIDTH+BLEED, H+2*BLEED, NAVY)
    p.image(a['university'], stripe_x+3.2, 4.0, 10.6, 14.2)
    p.line(stripe_x+4.3, 20.5, 8.4, '#9FB6CC')
    for i, text in enumerate(UNIVERSITY_LINES):
        p.text(text, stripe_x+8.5, 22.5+i*3.9, 6.5, medium=True,
               color=WHITE, align='center', width=13)
    p.rect(stripe_x+3, 42.8, 11, .22, '#00BADB')
    p.text(year, stripe_x+8.5, 47.5, 6.3, medium=True,
           color=WHITE, align='center', width=14)
    if side == 'front':
        p.image(a['aya'], 19.5, 3.0, 20, 10.5)
        p.line(42, 4.5, 8, '#72BED5', vertical=True)
        p.text('КОРТИ ВОЛОНТЁР', 44, 5.0, 7.7, bold=True, width=39.5)
        p.text('Карта волонтёра · Volunteer card', 44, 10, 5.0, color=MUTED, width=39.5)
        if a['photo']:
            p.image(a['photo'], 19.5, 18, PHOTO_WIDTH, PHOTO_HEIGHT, crop=True, radius=1.3)
        else:
            p.rect(19.5, 18, PHOTO_WIDTH, PHOTO_HEIGHT, PALE, radius=1.3)
            p.text('Фото', 30.25, 31, 8, color=MUTED, align='center')
        names = card.name_lines
        first_y = {1: 24.4, 2: 21.6, 3: 18.8}.get(len(names), 18.8)
        # Option 2: natural case, medium weight and one balanced size for all
        # components. Long names shrink together and never invade the QR margin.
        name_size = min((font_size(value, NAME_WIDTH, NAME_SIZE, medium=True)
                         for value in names), default=NAME_SIZE)
        for i, value in enumerate(names):
            p.text(value, 43.5, first_y+i*5.6, name_size, medium=True)
        if card.course:
            p.text('Курс · Year', 43.5, 37.7, 5.8, color=MUTED)
            p.text(str(card.course), 43.5, 41.2, 11.5, medium=True)
        p.rect(64.8, 20.5, 18.7, 18.7, '#D6E7F7', radius=1.4)
        p.rect(65.0, 20.7, 18.3, 18.3, WHITE, radius=1.2)
        p.qr(qr_matrix(qr_url or profile_url(card.user)), 65.15, 20.85, 18.0)
        p.text('Профиль · Profile', 74.15, 40.4, 4.8, color=MUTED, align='center', width=18.7)
        p.text('№ '+card.number, 19.5, 49.5, 7.5, bold=True, width=64)
    else:
        p.image(a['aya'], 5, 3, 18.5, 10)
        p.line(25.5, 4.2, 7.5, '#72BED5', vertical=True)
        p.text('ASSOCIATION OF', 27.5, 4.7, 7.0, medium=True, width=38)
        p.text('YOUTH ATSMU', 27.5, 8.4, 7.0, medium=True, width=38)
        for i, text in enumerate(DEPARTMENT_LINES):
            p.text(text, 5, 16.5+i*3.9, 8.0, bold=True, width=60.5)
        # A larger 29 x 21 mm white area remains clear of text and branding.
        if a['stamp']:
            p.image(a['stamp'], 5, 24.2, 29, 21)
        if a['signature']:
            p.image(a['signature'], 37, 34.3, 28.5, 9.5)
        p.line(37, 45.0, 28.5, '#91A2B7')
        p.text('Муҳр · Печать · Stamp', 19.5, 46.4, 4.2, color=MUTED, align='center', width=29)
        p.text('Имзои роҳбар · Подпись · Signature', 51.25, 46.4, 4.2, color=MUTED, align='center', width=28.5)
        p.text('№ '+card.number, 5, 50.3, 7.5, bold=True, width=60)


def preview_png(card, side, *, viewer=False, dpi=240, qr_url=None):
    painter = RasterPainter(dpi)
    paint_card(painter, card, side, qr_url=qr_url)
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


def make_pdf(cards, *, layout='press', qr_url=None):
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
                paint_card(PDFPainter(c, 6, 6), card, side, a, qr_url=qr_url)
                crop_marks(c, 6, 6)
                c.showPage()
    else:
        for front, back in imposed_slots(cards, 'short' if layout == 'a4-short' else 'long'):
            # Symmetric grid: 2 x 4; 98 x 66 mm cells include bleed and marks.
            for side, slots in [('front', front), ('back', back)]:
                for row, col, card in slots:
                    x, y = 7 + col*98 + 6, 297 - 16.5 - (row+1)*66 + 6
                    paint_card(PDFPainter(c, x, y), card, side, qr_url=qr_url)
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
