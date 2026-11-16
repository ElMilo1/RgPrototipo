import csv
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import servicios as agenda
from .forms import BuscarReservaForm, ReservaPanelForm, ReservaPublicaForm, SolicitudForm
from .models import (HistorialReserva, HorarioAtencion, Profesional, Reserva, Servicio, SolicitudWhatsApp,
                     normalizar_telefono)

staff = staff_member_required(login_url="login")


def _fecha(valor, defecto=None):
    try:
        return date.fromisoformat(valor)
    except (TypeError, ValueError):
        return defecto


def _hora(valor):
    try:
        return datetime.strptime(valor, "%H:%M").time()
    except (TypeError, ValueError):
        return None


def _por_id(qs, valor):
    return qs.filter(pk=int(valor)).first() if str(valor or "").isdigit() else None


def _url(nombre, **params):
    limpio = {k: v for k, v in params.items() if v not in (None, "")}
    return reverse(nombre) + ("?" + "&".join(f"{k}={v}" for k, v in limpio.items()) if limpio else "")


# ===================== Vista clienta =====================
def reservar(request):
    servicios = Servicio.objects.filter(activo=True)
    profesionales = Profesional.objects.filter(activo=True)
    datos = request.POST if request.method == "POST" else request.GET
    servicio = _por_id(servicios, datos.get("servicio"))
    profesional = _por_id(profesionales, datos.get("profesional"))
    dias = agenda.dias_reservables()
    fecha = _fecha(datos.get("fecha"))
    if fecha not in dias:
        fecha = dias[0] if dias else None
    hora = _hora(datos.get("hora"))
    paso = 1 if not servicio or datos.get("paso") == "1" else (3 if hora else 2)

    ctx = {"servicios": servicios, "profesionales": profesionales, "servicio": servicio, "profesional": profesional,
           "dias": dias, "fecha": fecha, "hora": hora, "paso": paso,
           "pid": profesional.pk if profesional else ""}

    if paso == 2:
        horas = agenda.horas_del_dia(fecha, servicio, profesional) if fecha else []
        ctx["manana"] = [(h, l) for h, l in horas if h < time(13)]
        ctx["tarde"] = [(h, l) for h, l in horas if h >= time(13)]
        ocupada = _hora(request.GET.get("ocupada"))
        if ocupada:
            ctx["ocupada"] = ocupada
            ctx["alternativas"] = agenda.horas_libres_cercanas(fecha, servicio, profesional, ocupada)
            HistorialReserva.registrar(None, "intento_rechazado", None, "web pública",
                                       f"{fecha:%d-%m-%Y} {ocupada:%H:%M} · {servicio.nombre} · la clienta tocó una hora ocupada")

    if paso == 3:
        inicial = request.session.get("datos_clienta", {})
        form = ReservaPublicaForm(request.POST or None, initial=inicial)
        if request.method == "POST" and form.is_valid():
            try:
                reserva = agenda.crear_reserva(
                    nombre=form.cleaned_data["nombre"], telefono=form.cleaned_data["telefono"],
                    email=form.cleaned_data["email"], servicio=servicio, fecha=fecha, hora_inicio=hora,
                    profesional=profesional, canal="web", consentimiento=True, origen="web pública")
                request.session["ultima_reserva"] = reserva.codigo
                request.session.pop("datos_clienta", None)
                return redirect("confirmacion", codigo=reserva.codigo)
            except ValidationError as e:
                ctx["errores"] = e.messages
        ctx["form"] = form
    return render(request, "reservas/reservar.html", ctx)


def _reserva_de_la_sesion(request, codigo):
    reserva = get_object_or_404(Reserva.objects.select_related("servicio", "profesional", "clienta"), codigo=codigo)
    if request.session.get("ultima_reserva") != codigo and not request.user.is_staff:
        return None
    return reserva


def confirmacion(request, codigo):
    reserva = _reserva_de_la_sesion(request, codigo)
    if not reserva:
        return redirect("mis_reservas")
    return render(request, "reservas/confirmacion.html", {"r": reserva})


def recordatorio(request, codigo):
    """Simula el recordatorio que llega por WhatsApp 24 horas antes."""
    reserva = _reserva_de_la_sesion(request, codigo)
    if not reserva:
        return redirect("mis_reservas")
    respuesta = None
    if request.method == "POST" and reserva.estado == "agendada":
        accion = request.POST.get("accion")
        if accion == "confirmar":
            reserva.confirmada_en = timezone.now()
            Reserva.objects.filter(pk=reserva.pk).update(confirmada_en=reserva.confirmada_en)
            HistorialReserva.registrar(reserva, "modificada", None, "recordatorio", "La clienta confirmó su asistencia.")
            respuesta = "confirmar"
        elif accion in ("cancelar", "cambiar"):
            agenda.cambiar_estado(reserva, "cancelada", origen="recordatorio",
                                  detalle="Cancelada por la clienta desde el recordatorio." if accion == "cancelar"
                                  else "La clienta pidió cambiar día u hora.")
            if accion == "cambiar":
                request.session["datos_clienta"] = {"nombre": reserva.clienta.nombre,
                                                    "telefono": reserva.clienta.telefono[2:] if reserva.clienta.telefono else ""}
                messages.success(request, "Tu hora anterior quedó liberada. Elige un nuevo día y hora.")
                return redirect(_url("reservar", servicio=reserva.servicio_id, profesional=reserva.profesional_id or "",
                                     fecha=reserva.fecha.isoformat()))
            respuesta = "cancelar"
    return render(request, "reservas/recordatorio.html", {"r": reserva, "respuesta": respuesta})


def asistida(request):
    form = SolicitudForm(request.POST or None)
    enviada = False
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        SolicitudWhatsApp.objects.create(nombre=d["nombre"], telefono=d["telefono"], servicio=d["servicio"],
                                         preferencia=d["preferencia"])
        enviada = True
        form = SolicitudForm()
    return render(request, "reservas/asistida.html", {"form": form, "enviada": enviada})


def mis_reservas(request):
    form = BuscarReservaForm(request.GET or None)
    reservas = None
    if form.is_valid():
        tel = normalizar_telefono(form.cleaned_data["telefono"])
        reservas = Reserva.objects.filter(clienta__telefono=tel, estado="agendada",
                                          fecha__gte=timezone.localdate()).select_related("servicio", "profesional", "clienta")
    return render(request, "reservas/mis_reservas.html", {"form": form, "reservas": reservas})


@require_POST
def cancelar_publica(request, codigo):
    tel = normalizar_telefono(request.POST.get("telefono"))
    reserva = get_object_or_404(Reserva, codigo=codigo, clienta__telefono=tel, estado="agendada")
    agenda.cambiar_estado(reserva, "cancelada", origen="web pública", detalle="Cancelada por la clienta.")
    messages.success(request, f"Tu reserva {codigo} quedó cancelada y la hora se liberó.")
    return redirect(f"/mis-reservas/?telefono={tel[2:]}")


# ===================== Panel de la dueña =====================
def _a_min(t):
    return t.hour * 60 + t.minute


def _linea_de_tiempo(fecha, reservas):
    horario = HorarioAtencion.objects.filter(dia_semana=fecha.weekday(), abierto=True).first()
    if not horario:
        return None, []
    ini, fin = _a_min(horario.apertura), _a_min(horario.cierre)
    total = fin - ini
    pct = lambda m: round((m - ini) / total * 100, 3)
    filas = []
    pros = list(Profesional.objects.filter(activo=True))
    grupos = [(p, [r for r in reservas if r.profesional_id == p.pk]) for p in pros]
    sin = [r for r in reservas if r.profesional_id is None or r.profesional_id not in {p.pk for p in pros}]
    if sin:
        grupos.append((None, sin))
    for pro, lista in grupos:
        activas = sorted([r for r in lista if r.activa], key=lambda r: r.hora_inicio)
        huecos = []
        for a, b in zip(activas, activas[1:]):
            if b.hora_inicio > a.hora_fin:
                huecos.append({"left": pct(_a_min(a.hora_fin)), "width": pct(_a_min(b.hora_inicio)) - pct(_a_min(a.hora_fin)),
                               "min": _a_min(b.hora_inicio) - _a_min(a.hora_fin)})
        bloques = [{"r": r, "left": pct(_a_min(r.hora_inicio)),
                    "width": pct(_a_min(r.hora_fin)) - pct(_a_min(r.hora_inicio))} for r in sorted(lista, key=lambda r: r.hora_inicio)]
        filas.append({"pro": pro, "bloques": bloques, "huecos": huecos})
    eje = [time(h) for h in range(-(-ini // 60), fin // 60 + 1)]
    return {"apertura": horario.apertura, "cierre": horario.cierre, "eje": eje}, filas


def _horas_select(fecha):
    horario = HorarioAtencion.objects.filter(dia_semana=fecha.weekday(), abierto=True).first()
    if not horario:
        return []
    paso = settings.AGENDA["INTERVALO_MIN"]
    actual, limite, salida = datetime.combine(fecha, horario.apertura), datetime.combine(fecha, horario.cierre), []
    while actual < limite:
        salida.append(actual.time())
        actual += timedelta(minutes=paso)
    return salida


@staff
def panel(request):
    hoy = timezone.localdate()
    fecha = _fecha(request.GET.get("fecha"), hoy)
    reservas = list(Reserva.objects.filter(fecha=fecha).select_related("clienta", "servicio", "profesional"))
    info, filas = _linea_de_tiempo(fecha, reservas)
    kpi = agenda.indicadores(fecha)
    kpi["web"] = sum(1 for r in reservas if r.activa and r.canal == "web")
    kpi["otros"] = kpi["reservas"] - kpi["web"]
    kpi["pct_cancel"] = round(kpi["cancelaciones"] / len(reservas) * 100) if reservas else 0
    kpi["min_res"] = sum(_a_min(r.hora_fin) - _a_min(r.hora_inicio) for r in reservas if r.activa)
    kpi["min_disp"] = 0
    if info:
        kpi["min_disp"] = _a_min(info["cierre"]) - _a_min(info["apertura"])
        if settings.AGENDA["AGENDA_POR_PROFESIONAL"]:
            kpi["min_disp"] *= max(1, Profesional.objects.filter(activo=True).count())
    dias = [hoy + timedelta(days=i) for i in range(8)]
    if fecha not in dias:
        dias = [fecha] + dias[:7]
    solicitud = _por_id(SolicitudWhatsApp.objects.filter(atendida=False), request.GET.get("solicitud"))
    inicial = {}
    if solicitud:
        inicial = {"nombre": solicitud.nombre, "telefono": solicitud.telefono[2:], "canal": "whatsapp",
                   "servicio": solicitud.servicio_id}
    return render(request, "reservas/panel.html", {
        "fecha": fecha, "dias": dias, "hoy": hoy, "kpi": kpi, "info": info, "filas": filas,
        "servicios": Servicio.objects.filter(activo=True), "profesionales": Profesional.objects.filter(activo=True),
        "canales": [c for c in Reserva.CANALES if c[0] != "web"], "horas": _horas_select(fecha),
        "solicitudes": SolicitudWhatsApp.objects.filter(atendida=False).select_related("servicio"),
        "solicitud": solicitud, "inicial": inicial,
        "manana": Reserva.objects.filter(fecha=hoy + timedelta(days=1), estado="agendada").select_related("clienta", "servicio"),
        "colores": [("Web", "web"), ("WhatsApp", "whatsapp"), ("Instagram", "instagram"), ("Teléfono", "telefono"), ("Presencial", "presencial")],
    })


@staff
@require_POST
def nueva_reserva(request):
    form = ReservaPanelForm(request.POST)
    fecha = _fecha(request.POST.get("fecha"), timezone.localdate())
    sol_id = request.POST.get("solicitud", "")
    volver = _url("panel", fecha=fecha.isoformat(), solicitud=sol_id)
    if not form.is_valid():
        for campo, errores in form.errors.items():
            for e in errores:
                etiqueta = f"{form.fields[campo].label}: " if campo in form.fields else ""
                messages.error(request, etiqueta + e, extra_tags="manual")
        return redirect(volver)
    d = form.cleaned_data
    try:
        r = agenda.crear_reserva(nombre=d["nombre"], telefono=d["telefono"], email=d["email"], servicio=d["servicio"],
                                 fecha=d["fecha"], hora_inicio=d["hora_inicio"], profesional=d["profesional"],
                                 canal=d["canal"], notas=d["notas"], usuario=request.user, origen="panel")
    except ValidationError as e:
        for m in e.messages:
            messages.error(request, f"No se guardó: {m}", extra_tags="manual")
        return redirect(volver)
    sol = _por_id(SolicitudWhatsApp.objects.all(), sol_id)
    if sol:
        sol.atendida, sol.reserva = True, r
        sol.save()
    messages.success(request, f"Reserva {r.codigo} guardada a las {r.hora_inicio:%H:%M}. La hora ya no aparece libre en la página de reservas.",
                     extra_tags="manual")
    return redirect(_url("panel", fecha=fecha.isoformat()))


@staff
@require_POST
def descartar_solicitud(request, pk):
    s = get_object_or_404(SolicitudWhatsApp, pk=pk)
    s.atendida = True
    s.save()
    return redirect(_url("panel", fecha=request.POST.get("fecha", "")))


@staff
@require_POST
def cambiar_estado(request, pk):
    reserva = get_object_or_404(Reserva, pk=pk)
    estado = request.POST.get("estado")
    if estado not in dict(Reserva.ESTADOS):
        messages.error(request, "Estado no válido.")
    else:
        try:
            agenda.cambiar_estado(reserva, estado, usuario=request.user, origen="panel")
            messages.success(request, f"{reserva.codigo}: {reserva.get_estado_display().lower()}.")
        except (ValidationError, IntegrityError) as e:
            msgs = e.messages if isinstance(e, ValidationError) else ["Ya existe una reserva para ese día y esa hora."]
            for m in msgs:
                messages.error(request, f"{reserva.codigo}: {m}")
    return redirect(_url("panel", fecha=reserva.fecha.isoformat()))


@staff
def historial(request):
    qs = HistorialReserva.objects.select_related("reserva", "usuario")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(reserva__codigo__icontains=q) | qs.filter(detalle__icontains=q)
    accion = request.GET.get("accion")
    if accion:
        qs = qs.filter(accion=accion)
    pagina = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(request, "reservas/historial.html", {"pagina": pagina, "q": q, "accion": accion,
                                                       "acciones": HistorialReserva.ACCIONES})


@staff
def exportar_csv(request):
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="reservas-{timezone.localdate():%Y-%m-%d}.csv"'
    resp.write("﻿")
    w = csv.writer(resp, delimiter=";")
    w.writerow(["Código", "Fecha", "Inicio", "Término", "Clienta", "Celular", "Servicio", "Profesional", "Canal",
                "Estado", "Confirmó asistencia", "Creada", "Creada por"])
    for r in Reserva.objects.select_related("clienta", "servicio", "profesional", "creada_por"):
        w.writerow([r.codigo, r.fecha.isoformat(), f"{r.hora_inicio:%H:%M}", f"{r.hora_fin:%H:%M}", r.clienta.nombre,
                    "+" + r.clienta.telefono if r.clienta.telefono else "", r.servicio.nombre,
                    r.profesional.nombre if r.profesional else "", r.get_canal_display(), r.get_estado_display(),
                    "Sí" if r.confirmada_en else "", timezone.localtime(r.creada_en).strftime("%Y-%m-%d %H:%M"),
                    r.creada_por.username if r.creada_por else "clienta (web)"])
    return resp
