from datetime import time

from django.db import migrations


def cargar(apps, schema_editor):
    Horario = apps.get_model("reservas", "HorarioAtencion")
    Servicio = apps.get_model("reservas", "Servicio")
    Profesional = apps.get_model("reservas", "Profesional")
    for dia in range(7):
        abierto = dia != 6
        cierre = time(14) if dia == 5 else time(19)
        Horario.objects.get_or_create(dia_semana=dia, defaults={"abierto": abierto, "apertura": time(10), "cierre": cierre})
    for nombre, minutos in [("Masaje relajante", 60), ("Limpieza facial", 60), ("Manicure", 45),
                            ("Pedicure", 60), ("Corte y brushing", 60), ("Diseño de cejas", 30)]:
        Servicio.objects.get_or_create(nombre=nombre, defaults={"duracion_min": minutos})
    if not Profesional.objects.exists():
        Profesional.objects.create(nombre="Profesional 1", rol="Dueña")


class Migration(migrations.Migration):
    dependencies = [("reservas", "0001_initial")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
