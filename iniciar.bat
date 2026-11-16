@echo off
REM Instala y abre el sistema de reservas de RG Beauty Spa
if not exist .venv python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python manage.py migrate
if not exist .creado (
  echo.
  echo Crea el usuario de la duena para entrar al panel:
  .venv\Scripts\python manage.py createsuperuser
  echo listo> .creado
)
start http://127.0.0.1:8000/
.venv\Scripts\python manage.py runserver
