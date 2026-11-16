from .models import HorarioAtencion


def horario_pie(request):
    """Resume el horario de atención para el pie de las pantallas de la clienta."""
    grupos = []
    for h in HorarioAtencion.objects.filter(abierto=True).order_by("dia_semana"):
        texto = f"{h.apertura:%H:%M} a {h.cierre:%H:%M}"
        nombre = h.get_dia_semana_display()
        if grupos and grupos[-1][2] == texto and grupos[-1][3] == h.dia_semana - 1:
            grupos[-1][1], grupos[-1][3] = nombre, h.dia_semana
        else:
            grupos.append([nombre, nombre, texto, h.dia_semana])
    partes = [(f"{a} a {b.lower()}" if a != b else a) + f" {t}" for a, b, t, _ in grupos]
    return {"horario_pie": " · ".join(partes)}
