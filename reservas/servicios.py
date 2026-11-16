"""Lógica de agenda: horas disponibles y creación segura de reservas."""
from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import (ESTADOS_ACTIVOS, Bloqueo, Clienta, HistorialReserva, HorarioAtencion, Profesional, Reserva,
                     normalizar_telefono)


def dias_reservables():
    hoy = timezone.localdate()
    abiertos = set(HorarioAtencion.objects.filter(abierto=True).values_list("dia_semana", flat=True))
    return [hoy + timedelta(days=i) for i in range(settings.AGENDA["DIAS_ANTICIPACION"] + 1)
            if (hoy + timedelta(days=i)).weekday() in abiertos]


def horas_del_dia(fecha, servicio, profesional=None):
    """Devuelve [(hora, libre)] para ese día y servicio."""
    horario = HorarioAtencion.objects.filter(dia_semana=fecha.weekday(), abierto=True).first()
    if not horario or not servicio:
        return []
    paso = settings.AGENDA["INTERVALO_MIN"]
    ahora = timezone.localtime()
    resultado = []
    actual = datetime.combine(fecha, horario.apertura)
    limite = datetime.combine(fecha, horario.cierre)
    while actual + timedelta(minutes=servicio.duracion_min) <= limite:
        inicio = actual.time()
        if not (fecha == ahora.date() and inicio <= ahora.time()) and fecha >= ahora.date():
            prueba = Reserva(fecha=fecha, hora_inicio=inicio, servicio=servicio, profesional=profesional)
            prueba.calcular_fin()
            libre = prueba.reserva_que_choca() is None and prueba.bloqueo_que_choca() is None
            resultado.append((inicio, libre))
        actual += timedelta(minutes=paso)
    return resultado


def asignar_profesional(fecha, inicio, servicio):
    """Si la clienta no elige, toma la primera profesional libre."""
    for pro in Profesional.objects.filter(activo=True):
        prueba = Reserva(fecha=fecha, hora_inicio=inicio, servicio=servicio, profesional=pro)
        prueba.calcular_fin()
        if prueba.reserva_que_choca() is None and prueba.bloqueo_que_choca() is None:
            return pro
    return Profesional.objects.filter(activo=True).first()


def crear_reserva(*, nombre, telefono, email, servicio, fecha, hora_inicio, profesional=None, canal="web",
                  notas="", consentimiento=False, usuario=None, origen="web pública"):
    """Valida y guarda la reserva dentro de una transacción.

    Si otra persona tomó la misma hora un instante antes, la restricción única de la base de datos
    lo impide y se informa como error de validación. Los intentos rechazados quedan en el historial.
    """
    telefono = normalizar_telefono(telefono)
    try:
        with transaction.atomic():
            clienta, _ = Clienta.objects.get_or_create(telefono=telefono, defaults={"nombre": nombre, "email": email})
            clienta.nombre = nombre or clienta.nombre
            if email:
                clienta.email = email
            if consentimiento:
                clienta.consentimiento_en = timezone.now()
            clienta.full_clean()
            clienta.save()
            if profesional is None:
                profesional = asignar_profesional(fecha, hora_inicio, servicio)
            reserva = Reserva(clienta=clienta, servicio=servicio, profesional=profesional, fecha=fecha,
                              hora_inicio=hora_inicio, canal=canal, notas=notas)
            reserva.full_clean(validate_constraints=False)
            reserva.save(usuario=usuario, origen=origen)
            return reserva
    except IntegrityError:
        error = ValidationError("Ya existe una reserva para ese día y esa hora. Elige otra hora.")
    except ValidationError as e:
        error = e
    HistorialReserva.registrar(None, "intento_rechazado", usuario, origen,
                               f"{fecha:%d-%m-%Y} {hora_inicio:%H:%M} · {getattr(servicio, 'nombre', '')} · "
                               f"+{telefono} · {'; '.join(error.messages)}")
    raise error


def cambiar_estado(reserva, estado, usuario=None, origen="panel", detalle=""):
    reserva.estado = estado
    if estado in ESTADOS_ACTIVOS:
        reserva.full_clean(validate_constraints=False)
    reserva.save(usuario=usuario, origen=origen, detalle=detalle)
    return reserva


def indicadores(fecha):
    reservas = list(Reserva.objects.filter(fecha=fecha).select_related("servicio", "profesional"))
    activas = sorted([r for r in reservas if r.activa], key=lambda r: r.hora_inicio)
    horario = HorarioAtencion.objects.filter(dia_semana=fecha.weekday(), abierto=True).first()
    a_min = lambda t: t.hour * 60 + t.minute
    disponibles = (a_min(horario.cierre) - a_min(horario.apertura)) if horario else 0
    if settings.AGENDA["AGENDA_POR_PROFESIONAL"]:
        disponibles *= max(1, Profesional.objects.filter(activo=True).count())
    reservados = sum(a_min(r.hora_fin) - a_min(r.hora_inicio) for r in activas)
    grupos = {}
    for r in activas:
        clave = r.profesional_id if settings.AGENDA["AGENDA_POR_PROFESIONAL"] else 0
        grupos.setdefault(clave, []).append(r)
    muerto = traslapes = 0
    for lista in grupos.values():
        for a, b in zip(lista, lista[1:]):
            muerto += max(0, a_min(b.hora_inicio) - a_min(a.hora_fin))
        for i, a in enumerate(lista):
            for b in lista[i + 1:]:
                if a.hora_inicio < b.hora_fin and b.hora_inicio < a.hora_fin:
                    traslapes += 1
    return {
        "ocupacion": round(reservados / disponibles * 100) if disponibles else 0,
        "reservas": len(activas),
        "cancelaciones": sum(r.estado == "cancelada" for r in reservas),
        "no_show": sum(r.estado == "no_show" for r in reservas),
        "tiempo_muerto": muerto,
        "traslapes": traslapes,
    }
