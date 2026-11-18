from django import template
from django.utils.html import format_html

from desk import rules

register = template.Library()


@register.filter
def money(value):
    return rules.fmt_money(value)


@register.simple_tag
def pill(flag):
    cls = rules.FLAG_CLASS.get(flag, "ND")
    return format_html('<span class="pill fl-{}">{}</span>', cls, rules.FLAG_LABEL.get(flag, flag))


@register.simple_tag(takes_context=True)
def url_with(context, **kwargs):
    """Current query string with some parameters replaced (use None to drop one)."""
    q = context["request"].GET.copy()
    for k, v in kwargs.items():
        if v is None:
            q.pop(k, None)
        else:
            q[k] = v
    s = q.urlencode()
    return "?" + s if s else "?"


@register.filter
def get_item(d, key):
    return d.get(key)
