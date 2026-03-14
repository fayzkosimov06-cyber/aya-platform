# users/templatetags/site_stats.py
from django import template

register = template.Library()

@register.simple_tag
def get_site_stats():
    """Цифры сайта из AboutPage -> AboutStatItem (первые 3 активные)."""
    try:
        from users.models import AboutPage
        about = AboutPage.objects.filter(pk=1).first()
        if not about:
            return {"volunteers": "135+", "events": "280+", "years": "10"}

        stats_qs = getattr(about, "stat_items", None)
        if stats_qs is not None:
            items = list(stats_qs.filter(is_active=True).order_by("order", "id")[:3])
            if items:
                vals = [it.number for it in items]
                while len(vals) < 3:
                    vals.append("0")
                return {"volunteers": vals[0], "events": vals[1], "years": vals[2]}

        return {
            "volunteers": getattr(about, "stat_1_num", "135+") or "135+",
            "events": getattr(about, "stat_2_num", "280+") or "280+",
            "years": getattr(about, "stat_3_num", "10") or "10",
        }
    except Exception:
        return {"volunteers": "135+", "events": "280+", "years": "10"}
