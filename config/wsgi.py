"""WSGI de RG Beauty Spa. Vercel lo usa como punto de entrada."""
import logging
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()

# En Vercel no hay paso de despliegue con acceso a la base, así que al arrancar cada instancia
# se aplican las migraciones pendientes (si no hay nada nuevo, solo toma unas consultas).
if os.environ.get("VERCEL") and os.environ.get("DATABASE_URL"):
    try:
        from django.core.management import call_command
        call_command("preparar_produccion")
    except Exception:  # otra instancia pudo migrar al mismo tiempo; la app sigue funcionando
        logging.getLogger(__name__).exception("No se pudo preparar la base al arrancar")

app = application
