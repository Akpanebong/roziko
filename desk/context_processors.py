from . import services


def desk(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    ctx = {"P": user.perm_set, "role_label": user.get_role_display(), "today": services.today()}
    try:
        ctx["alert_badge"] = services.alert_counts(user)["badge"]
    except Exception:  # never let the badge break a page
        ctx["alert_badge"] = 0
    return ctx
