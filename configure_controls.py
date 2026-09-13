"""Enable AYA controls while preserving the operator's existing settings and secrets."""
from pathlib import Path
import re
p=Path(__file__).parent/'aya_platform/settings.py'
s=p.read_text(encoding='utf-8')
name='users.control_middleware.ControlMiddleware'
if name in s:
 print('Проверка полномочий уже подключена.')
else:
 pattern=r'([\'\"]django\.contrib\.auth\.middleware\.AuthenticationMiddleware[\'\"]\s*,)'
 updated,n=re.subn(pattern,r"\1\n    'users.control_middleware.ControlMiddleware',",s,count=1)
 if not n:raise SystemExit('Добавьте users.control_middleware.ControlMiddleware в MIDDLEWARE после AuthenticationMiddleware вручную.')
 p.with_suffix('.py.before-controls').write_text(s,encoding='utf-8')
 p.write_text(updated,encoding='utf-8');print('Проверка полномочий подключена. Прежние настройки сохранены рядом с settings.py.')
