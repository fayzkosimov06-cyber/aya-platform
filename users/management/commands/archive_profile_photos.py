"""Reversible archive of files not referenced by any model. Dry-run by default."""
import hashlib
import json
import os
from pathlib import Path
import re
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from users.avatars import roots, is_referenced, archive_unused


class Command(BaseCommand):
    help='Проверить неиспользуемые фото; --apply переносит их в закрытый архив, сохраняя восстановление.'

    def add_arguments(self,parser):
        parser.add_argument('--apply',action='store_true')
        parser.add_argument('--restore',help='Номер записи закрытого архива (32 символа)')

    def handle(self,*args,**options):
        public,private=roots()
        if options['restore']:
            key=options['restore']
            if not re.fullmatch('[a-f0-9]{32}',key):raise CommandError('Неверный номер архивной записи.')
            records=list(private.glob('*/'+key+'.json'))
            if len(records)!=1:raise CommandError('Архивная запись не найдена.')
            record=records[0]
            if record.resolve()!=record:raise CommandError('Недопустимый путь архива.')
            data=json.loads(record.read_text())
            source=record.parent/data['file'];target=Path(settings.MEDIA_ROOT).absolute()/data['original']
            if (source.resolve()!=source or source.parent!=record.parent or target.resolve()!=target
                    or not target.is_relative_to(public) or target.exists()):
                raise CommandError('Нельзя восстановить фотографию по этому пути.')
            with source.open('rb') as stream:checksum=hashlib.file_digest(stream,'sha256').hexdigest()
            if checksum!=data['sha256']:raise CommandError('Контрольная сумма не совпадает.')
            if options['apply']:
                target.parent.mkdir(parents=True,exist_ok=True)
                os.replace(source,target);target.chmod(0o644)
            self.stdout.write(json.dumps({'restore':True,'applied':options['apply']}));return
        count=total=moved=0
        for path in sorted(public.rglob('*')) if public.exists() else []:
            if path.is_symlink() or path.resolve()!=path:raise CommandError('В хранилище есть ссылка. Перенос остановлен.')
            if not path.is_file():continue
            name=path.relative_to(Path(settings.MEDIA_ROOT).absolute()).as_posix()
            if not is_referenced(name,path):
                count+=1;total+=path.stat().st_size
                if options['apply'] and archive_unused(name):moved+=1
        self.stdout.write(json.dumps({'unreferenced_files':count,'bytes':total,'archived':moved,'applied':options['apply']}))
