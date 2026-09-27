import re
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator


def social_url(value, network=None):
    value=(value or '').strip()
    if not value:return ''
    if network=='instagram' and re.fullmatch(r'@?[A-Za-z0-9._]+',value):
        value='https://www.instagram.com/'+value.lstrip('@')+'/'
    try:
        URLValidator(schemes=['http','https'])(value)
    except ValidationError:
        return ''
    return value
