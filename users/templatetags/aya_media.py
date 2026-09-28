from django import template
from users.about_content import video_embed_url
from users.social_links import social_url
register=template.Library()

@register.inclusion_tag('users/partials/video_card.html')
def video_card(file=None, url='', title='Видео', poster=None):
    safe_url = social_url(url)
    return {'file':file,'url':safe_url,'embed':video_embed_url(safe_url),'title':title or 'Видео','poster':poster}
