#!/bin/sh
# Instala y abre el sistema de reservas de RG Beauty Spa
set -e
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
if [ ! -f .creado ]; then
  echo "Crea el usuario de la dueña para entrar al panel:"
  .venv/bin/python manage.py createsuperuser
  touch .creado
fi
.venv/bin/python manage.py runserver
