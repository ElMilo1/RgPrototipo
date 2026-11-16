from django.urls import path

from . import views

urlpatterns = [
    path("", views.reservar, name="reservar"),
    path("reserva/<str:codigo>/", views.confirmacion, name="confirmacion"),
    path("reserva/<str:codigo>/recordatorio/", views.recordatorio, name="recordatorio"),
    path("whatsapp/", views.asistida, name="asistida"),
    path("mis-reservas/", views.mis_reservas, name="mis_reservas"),
    path("mis-reservas/<str:codigo>/cancelar/", views.cancelar_publica, name="cancelar_publica"),
    path("panel/", views.panel, name="panel"),
    path("panel/nueva/", views.nueva_reserva, name="nueva_reserva"),
    path("panel/reserva/<int:pk>/estado/", views.cambiar_estado, name="cambiar_estado"),
    path("panel/solicitud/<int:pk>/descartar/", views.descartar_solicitud, name="descartar_solicitud"),
    path("panel/historial/", views.historial, name="historial"),
    path("panel/exportar.csv", views.exportar_csv, name="exportar_csv"),
]
