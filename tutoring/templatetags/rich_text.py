from django import template

from tutoring.richtext import render_rich_text

register = template.Library()


@register.filter
def rich_note(value):
    return render_rich_text(value)
