from datetime import time, timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import servicios as agenda
from .models import Bloqueo, Clienta, HistorialReserva, HorarioAtencion, Profesional, Reserva, Servicio


def proximo_dia_habil(dias=2):
    d = timezone.localdate() + timedelta(days=dias)
    while d.weekday() >= 5:  # lunes a viernes, abierto 10 a 19
        d += timedelta(days=1)
    return d


class Base(TestCase):
    def setUp(self):
        self.masaje = Servicio.objects.get(nombre="Masaje relajante")      # 60 min
        self.cejas = Servicio.objects.get(nombre="Diseño de cejas")        # 30 min
        self.pro1 = Profesional.objects.first()
        self.pro2 = Profesional.objects.create(nombre="Camila", rol="Colaboradora")
        self.dia = proximo_dia_habil()

    def reservar(self, hora, servicio=None, telefono="912345678", profesional=None, fecha=None, **kw):
        return agenda.crear_reserva(nombre="Clienta", telefono=telefono, email="", servicio=servicio or self.masaje,
                                    fecha=fecha or self.dia, hora_inicio=hora, profesional=profesional,
                                    consentimiento=True, **kw)


class ReglaMismaFechaHora(Base):
    def test_no_permite_dos_reservas_mismo_dia_y_hora(self):
        self.reservar(time(10))
        with self.assertRaisesMessage(ValidationError, "Ya existe una reserva"):
            self.reservar(time(10), telefono="987654321")
        self.assertEqual(Reserva.objects.filter(fecha=self.dia, hora_inicio=time(10)).count(), 1)

    def test_tampoco_con_otra_profesional(self):
        self.reservar(time(11), profesional=self.pro1)
        with self.assertRaises(ValidationError):
            self.reservar(time(11), profesional=self.pro2, telefono="987654321")

    @override_settings(AGENDA={"INTERVALO_MIN": 30, "DIAS_ANTICIPACION": 30, "AGENDA_POR_PROFESIONAL": True})
    def test_misma_hora_prohibida_aunque_la_agenda_sea_por_profesional(self):
        self.reservar(time(12), profesional=self.pro1)
        with self.assertRaises(ValidationError):
            self.reservar(time(12), profesional=self.pro2, telefono="987654321")

    def test_la_base_de_datos_tambien_lo_impide(self):
        r = self.reservar(time(10))
        duplicada = Reserva(clienta=r.clienta, servicio=self.cejas, fecha=self.dia, hora_inicio=time(10), codigo="RG-99999")
        duplicada.calcular_fin()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Reserva.save(duplicada)  # sin pasar por las validaciones

    def test_cancelar_libera_la_hora(self):
        r = self.reservar(time(10))
        agenda.cambiar_estado(r, "cancelada")
        self.reservar(time(10), telefono="987654321")
        self.assertEqual(Reserva.objects.filter(fecha=self.dia, hora_inicio=time(10), estado="agendada").count(), 1)

    def test_no_se_puede_reactivar_si_la_hora_ya_se_tomo(self):
        r = self.reservar(time(10))
        agenda.cambiar_estado(r, "cancelada")
        self.reservar(time(10), telefono="987654321")
        with self.assertRaises(ValidationError):
            agenda.cambiar_estado(r, "agendada")


class ValidacionesDeHorario(Base):
    def test_no_permite_cruce_de_horarios(self):
        self.reservar(time(10))  # 10:00 a 11:00
        with self.assertRaisesMessage(ValidationError, "se cruza"):
            self.reservar(time(10, 30), servicio=self.cejas, telefono="987654321")

    def test_reserva_seguida_si_se_permite(self):
        self.reservar(time(10))
        self.reservar(time(11), telefono="987654321")

    @override_settings(AGENDA={"INTERVALO_MIN": 30, "DIAS_ANTICIPACION": 30, "AGENDA_POR_PROFESIONAL": True})
    def test_agenda_por_profesional_permite_cruce_con_otra(self):
        self.reservar(time(10), profesional=self.pro1)
        self.reservar(time(10, 30), profesional=self.pro2, telefono="987654321")
        with self.assertRaises(ValidationError):
            self.reservar(time(10, 30), profesional=self.pro1, servicio=self.cejas, telefono="955555555", fecha=self.dia)

    def test_fuera_del_horario(self):
        with self.assertRaisesMessage(ValidationError, "horario de atención"):
            self.reservar(time(9))
        with self.assertRaisesMessage(ValidationError, "horario de atención"):
            self.reservar(time(18, 30))  # terminaría 19:30

    def test_dia_cerrado(self):
        domingo = self.dia + timedelta(days=(6 - self.dia.weekday()))
        with self.assertRaisesMessage(ValidationError, "no atiende"):
            self.reservar(time(11), fecha=domingo)

    def test_hora_que_no_calza_con_bloques(self):
        with self.assertRaisesMessage(ValidationError, "bloques de 30 minutos"):
            self.reservar(time(10, 15))

    def test_fecha_pasada(self):
        with self.assertRaisesMessage(ValidationError, "ya pasó"):
            self.reservar(time(11), fecha=timezone.localdate() - timedelta(days=1))

    def test_demasiado_adelante(self):
        lejos = timezone.localdate() + timedelta(days=60)
        with self.assertRaisesMessage(ValidationError, "anticipación"):
            self.reservar(time(11), fecha=lejos)

    def test_bloqueo(self):
        Bloqueo.objects.create(fecha=self.dia, hora_inicio=time(13), hora_fin=time(14), motivo="almuerzo")
        with self.assertRaisesMessage(ValidationError, "bloqueado"):
            self.reservar(time(13))

    def test_telefono_invalido(self):
        with self.assertRaises(ValidationError):
            self.reservar(time(10), telefono="123")
        self.assertFalse(Clienta.objects.exists())

    def test_horas_disponibles_marcan_ocupadas(self):
        self.reservar(time(10))
        horas = dict(agenda.horas_del_dia(self.dia, self.cejas))
        self.assertFalse(horas[time(10)])
        self.assertFalse(horas[time(10, 30)])
        self.assertTrue(horas[time(11)])


class Trazabilidad(Base):
    def test_historial_de_creacion_y_cambios(self):
        r = self.reservar(time(10))
        agenda.cambiar_estado(r, "asistio")
        acciones = list(HistorialReserva.objects.filter(reserva=r).order_by("id").values_list("accion", flat=True))
        self.assertEqual(acciones, ["creada", "modificada"])
        self.assertIn("Agendada → Asistió", HistorialReserva.objects.filter(reserva=r).order_by("id").last().detalle)

    def test_intento_rechazado_queda_registrado(self):
        self.reservar(time(10))
        with self.assertRaises(ValidationError):
            self.reservar(time(10), telefono="987654321")
        self.assertTrue(HistorialReserva.objects.filter(accion="intento_rechazado").exists())

    def test_historial_no_se_edita_ni_borra(self):
        r = self.reservar(time(10))
        h = HistorialReserva.objects.get(reserva=r)
        h.detalle = "otro"
        with self.assertRaises(ValidationError):
            h.save()
        with self.assertRaises(ValidationError):
            h.delete()

    def test_usuario_del_panel_queda_registrado(self):
        u = User.objects.create_user("recepcion", password="x", is_staff=True)
        r = self.reservar(time(10), usuario=u, origen="panel", canal="whatsapp")
        self.assertEqual(r.creada_por, u)
        self.assertEqual(HistorialReserva.objects.get(reserva=r).usuario, u)


class Vistas(Base):
    def test_flujo_publico(self):
        url = reverse("reservar")
        r = self.client.get(url, {"servicio": self.masaje.pk, "fecha": self.dia.isoformat(), "hora": "10:00"})
        self.assertContains(r, "Tus datos")
        r = self.client.post(url, {"servicio": self.masaje.pk, "fecha": self.dia.isoformat(), "hora": "10:00",
                                   "nombre": "Marco", "telefono": "9 1111 2222", "consentimiento": "on"})
        self.assertEqual(r.status_code, 302)
        r = self.client.post(url, {"servicio": self.masaje.pk, "fecha": self.dia.isoformat(), "hora": "10:00",
                                   "nombre": "Otra", "telefono": "9 3333 4444", "consentimiento": "on"})
        self.assertContains(r, "Ya existe una reserva")

    def test_panel_requiere_ingreso(self):
        r = self.client.get(reverse("panel"))
        self.assertEqual(r.status_code, 302)
        User.objects.create_user("admin", password="x", is_staff=True)
        self.client.login(username="admin", password="x")
        self.assertEqual(self.client.get(reverse("panel")).status_code, 200)
        self.assertEqual(self.client.get(reverse("historial")).status_code, 200)
        self.assertEqual(self.client.get(reverse("exportar_csv")).status_code, 200)
