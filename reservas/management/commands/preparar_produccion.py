import os

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Aplica migraciones, crea el usuario de la dueña y, si se pide, carga reservas de ejemplo."

    def handle(self, *args, **kw):
        call_command("migrate", interactive=False, verbosity=0)
        usuario = os.environ.get("DJANGO_SUPERUSER_USERNAME")
        clave = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
        if usuario and clave:
            User = get_user_model()
            if not User.objects.filter(username=usuario).exists():
                User.objects.create_superuser(usuario, os.environ.get("DJANGO_SUPERUSER_EMAIL", ""), clave)
        if os.environ.get("CARGAR_DEMO") == "1":
            from reservas.models import Reserva
            if not Reserva.objects.exists():
                call_command("cargar_demo", verbosity=0)
