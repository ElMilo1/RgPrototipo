from django import template

register = template.Library()

DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
DIAS_LARGOS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


@register.filter
def dia_corto(d):
    return DIAS[d.weekday()]


@register.filter
def mes_corto(d):
    return MESES[d.month - 1][:3].capitalize()


@register.filter
def fecha_larga(d):
    return f"{DIAS_LARGOS[d.weekday()]}, {d.day} de {MESES[d.month - 1]}"


@register.filter
def hm(t):
    return t.strftime("%H:%M") if t else ""


@register.simple_tag(takes_context=True)
def qs(context, **cambios):
    """Arma la querystring del flujo de reserva conservando servicio, profesional y fecha."""
    base = {"servicio": getattr(context.get("servicio"), "pk", ""), "profesional": context.get("pid", ""),
            "fecha": context["fecha"].isoformat() if context.get("fecha") else ""}
    base.update(cambios)
    partes = []
    for k, v in base.items():
        if v in (None, ""):
            continue
        if hasattr(v, "isoformat") and k == "fecha":
            v = v.isoformat()
        elif hasattr(v, "strftime"):
            v = v.strftime("%H:%M")
        partes.append(f"{k}={v}")
    return "?" + "&".join(partes)


@register.filter
def fono(tel):
    """569XXXXXXXX -> +56 9 XXXX XXXX"""
    t = str(tel or "")
    return f"+56 9 {t[3:7]} {t[7:]}" if len(t) == 11 and t.startswith("569") else (f"+{t}" if t else "")
