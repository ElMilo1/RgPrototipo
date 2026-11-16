import random
from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand

from reservas import servicios as agenda
from reservas.models import Profesional, Reserva, Servicio

NOMBRES = ["Valentina", "Carolina", "Francisca", "Javiera", "Constanza", "Paula", "Daniela", "Fernanda",
           "Catalina", "Antonia", "Gloria", "Patricia", "Rosa", "Camila"]
CANALES = ["whatsapp", "whatsapp", "whatsapp", "instagram", "instagram", "telefono", "presencial", "web"]


class Command(BaseCommand):
    help = "Carga reservas de ejemplo para demostrar el sistema (se marcan con la nota 'demo')."

    def add_arguments(self, parser):
        parser.add_argument("--dias", type=int, default=6)
        parser.add_argument("--borrar", action="store_true", help="Cancela las reservas de ejemplo en vez de crearlas.")

    def handle(self, *args, dias, borrar, **kw):
        if borrar:
            n = 0
            for r in Reserva.objects.filter(notas="demo").exclude(estado="cancelada"):
                agenda.cambiar_estado(r, "cancelada", origen="demo", detalle="Reserva de ejemplo retirada.")
                n += 1
            self.stdout.write(self.style.SUCCESS(f"{n} reservas de ejemplo canceladas."))
            return
        if Profesional.objects.filter(activo=True).count() < 2:
            Profesional.objects.create(nombre="Profesional 2", rol="Colaboradora")
        rnd = random.Random(7)
        servicios = list(Servicio.objects.filter(activo=True))
        creadas = 0
        for fecha in agenda.dias_reservables()[:dias]:
            meta, intentos = rnd.randint(3, 6), 0
            hechas = 0
            while hechas < meta and intentos < 30 and servicios:
                intentos += 1
                s = rnd.choice(servicios)
                libres = [h for h, libre in agenda.horas_del_dia(fecha, s) if libre]
                if not libres:
                    continue
                try:
                    agenda.crear_reserva(nombre=rnd.choice(NOMBRES), telefono=f"9{rnd.randint(10000000, 99999999)}", email="",
                                         servicio=s, fecha=fecha, hora_inicio=rnd.choice(libres), canal=rnd.choice(CANALES),
                                         notas="demo", consentimiento=True, origen="demo")
                    creadas += 1
                    hechas += 1
                except ValidationError:
                    pass
        self.stdout.write(self.style.SUCCESS(f"{creadas} reservas de ejemplo creadas."))
