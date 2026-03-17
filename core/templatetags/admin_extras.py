from django import template


register = template.Library()


@register.filter
def initials(user):
    if not user or not getattr(user, "is_authenticated", False):
        return "US"

    base = (user.get_full_name() or "").strip() or user.get_username()
    parts = [part[0].upper() for part in base.split() if part]

    if len(parts) >= 2:
        return "".join(parts[:2])
    if len(parts) == 1 and len(base) >= 2:
        return base[:2].upper()
    if len(parts) == 1:
        return parts[0]
    return "US"
