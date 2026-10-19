"""Refresh stored QR images in place; never modify accounts, permissions or DB rows."""
import json
import os
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath

from django.core.files.storage import FileSystemStorage
from django.core.management.base import BaseCommand, CommandError

from users.models import User
from users.profile_qr import png_for_profile, public_site_url


def replace_png(path, content, root):
    assert path.parent == root and not path.is_symlink()
    if not root.exists():
        root.mkdir(mode=0o755)
        root.chmod(0o755)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=root, prefix='.aya-qr-', suffix='.tmp', delete=False) as file:
            temporary = Path(file.name)
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        temporary.chmod(0o644)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            assert temporary.resolve().parent == root
            temporary.unlink()


class Command(BaseCommand):
    help = 'Обновить сохранённые QR-коды профилей. Без --apply выполняется только проверка.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        public_site_url()
        storage = User._meta.get_field('qr_code').storage
        if not isinstance(storage, FileSystemStorage):
            raise CommandError('Для этой операции требуется локальное хранилище QR-кодов.')
        media = Path(storage.location).resolve()
        root = media / 'qr_codes'
        if root.is_symlink() or root.resolve() != root:
            raise CommandError('Каталог QR-кодов не должен быть символической ссылкой.')
        counts = Counter(name for name in User.objects.values_list('qr_code', flat=True) if name)
        plan = []
        unchanged = missing = 0
        for person in User.objects.filter(is_superuser=False).only('pk', 'qr_code').order_by('pk'):
            name = person.qr_code.name
            if not name:
                missing += 1
                continue  # The profile download still generates a current QR on demand.
            parts = PurePosixPath(name).parts
            if ('\\' in name or len(parts) != 2 or parts[0] != 'qr_codes'
                    or Path(parts[1]).suffix.lower() != '.png' or counts[name] != 1):
                raise CommandError('Обнаружена небезопасная или общая ссылка на файл QR-кода. Изменения не выполнены.')
            path = media / name
            if path.is_symlink() or path.resolve().parent != root:
                raise CommandError('Небезопасный путь QR-кода. Изменения не выполнены.')
            if path.exists() and (not path.is_file() or path.stat().st_size > 8 * 1024 * 1024):
                raise CommandError('Неожиданный формат сохранённого QR-кода. Изменения не выполнены.')
            before = path.read_bytes() if path.exists() else None
            after = png_for_profile(person)
            if before == after:
                unchanged += 1
            else:
                plan.append((path, before, after))
        completed = []
        if options['apply']:
            try:
                for path, before, after in plan:
                    replace_png(path, after, root)
                    completed.append((path, before))
            except Exception as error:
                for path, before in reversed(completed):
                    if before is None:
                        assert path.resolve().parent == root
                        path.unlink(missing_ok=True)
                    else:
                        replace_png(path, before, root)
                raise CommandError('Не удалось обновить QR-коды; записанные файлы восстановлены.') from error
        self.stdout.write(json.dumps({'mode': 'apply' if options['apply'] else 'dry-run',
                                     'refresh': len(plan), 'unchanged': unchanged, 'without_stored_file': missing,
                                     'database_modified': False}, ensure_ascii=True))
