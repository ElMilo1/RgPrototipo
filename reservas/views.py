import csv
from datetime import date, datetime, timedelta

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import servicios as agenda
from .forms import BuscarReservaForm, ReservaPanelForm, ReservaPublicaForm
from .models import HistorialReserva, Profesional, Reserva, Servicio, normalizar_telefono


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


# ===================== Público =====================
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

    form = ReservaPublicaForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if not (servicio and fecha and hora):
            messages.error(request, "Elige servicio, día y hora antes de confirmar.")
        else:
            try:
                reserva = agenda.crear_reserva(
                    nombre=form.cleaned_data["nombre"], telefono=form.cleaned_data["telefono"],
                    email=form.cleaned_data["email"], servicio=servicio, fecha=fecha, hora_inicio=hora,
                    profesional=profesional, canal="web", consentimiento=True, origen="web pública")
                request.session["ultima_reserva"] = reserva.codigo
                return redirect("confirmacion", codigo=reserva.codigo)
            except ValidationError as e:
                for m in e.messages:
                    messages.error(request, m)

    horas = agenda.horas_del_dia(fecha, servicio, profesional) if (servicio and fecha) else []
    return render(request, "reservas/reservar.html", {
        "servicios": servicios, "profesionales": profesionales, "servicio": servicio, "profesional": profesional,
        "dias": dias, "fecha": fecha, "hora": hora, "horas": horas, "form": form,
    })


def confirmacion(request, codigo):
    reserva = get_object_or_404(Reserva.objects.select_related("servicio", "profesional", "clienta"), codigo=codigo)
    if request.session.get("ultima_reserva") != codigo and not request.user.is_staff:
        return redirect("mis_reservas")
    return render(request, "reservas/confirmacion.html", {"r": reserva})


def mis_reservas(request):
    form = BuscarReservaForm(request.GET or None)
    reservas = None
    if form.is_valid():
        tel = normalizar_telefono(form.cleaned_data["telefono"])
        reservas = Reserva.objects.filter(clienta__telefono=tel, estado="agendada",
                                          fecha__gte=timezone.localdate()).select_related("servicio", "profesional")
    return render(request, "reservas/mis_reservas.html", {"form": form, "reservas": reservas})


@require_POST
def cancelar_publica(request, codigo):
    tel = normalizar_telefono(request.POST.get("telefono"))
    reserva = get_object_or_404(Reserva, codigo=codigo, clienta__telefono=tel, estado="agendada")
    agenda.cambiar_estado(reserva, "cancelada", origen="web pública", detalle="Cancelada por la clienta.")
    messages.success(request, f"Tu reserva {codigo} quedó cancelada y la hora se liberó.")
    return redirect(f"/mis-reservas/?telefono={tel[2:]}")


# ===================== Panel =====================
@staff_member_required(login_url="login")
def panel(request):
    fecha = _fecha(request.GET.get("fecha"), timezone.localdate())
    reservas = Reserva.objects.filter(fecha=fecha).select_related("clienta", "servicio", "profesional")
    manana = timezone.localdate() + timedelta(days=1)
    recordatorios = Reserva.objects.filter(fecha=manana, estado="agendada").select_related("clienta", "servicio")
    return render(request, "reservas/panel.html", {
        "fecha": fecha, "anterior": fecha - timedelta(days=1), "siguiente": fecha + timedelta(days=1),
        "reservas": reservas, "kpi": agenda.indicadores(fecha), "recordatorios": recordatorios,
    })


@staff_member_required(login_url="login")
@require_POST
def cambiar_estado(request, pk):
    reserva = get_object_or_404(Reserva, pk=pk)
    estado = request.POST.get("estado")
    if estado not in dict(Reserva.ESTADOS):
        messages.error(request, "Estado no válido.")
    else:
        try:
            agenda.cambiar_estado(reserva, estado, usuario=request.user, origen="panel")
            messages.success(request, f"{reserva.codigo}: estado cambiado a {reserva.get_estado_display().lower()}.")
        except (ValidationError, IntegrityError) as e:
            msgs = e.messages if isinstance(e, ValidationError) else ["Ya existe una reserva para ese día y esa hora."]
            for m in msgs:
                messages.error(request, f"{reserva.codigo}: {m}")
    return redirect(f"/panel/?fecha={reserva.fecha.isoformat()}")


@staff_member_required(login_url="login")
def nueva_reserva(request):
    inicial = {"fecha": _fecha(request.GET.get("fecha"), timezone.localdate())}
    form = ReservaPanelForm(request.POST or None, initial=inicial)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            r = agenda.crear_reserva(nombre=d["nombre"], telefono=d["telefono"], email=d["email"], servicio=d["servicio"],
                                     fecha=d["fecha"], hora_inicio=d["hora_inicio"], profesional=d["profesional"],
                                     canal=d["canal"], notas=d["notas"], usuario=request.user, origen="panel")
            messages.success(request, f"Reserva {r.codigo} guardada: {r.fecha:%d-%m-%Y} a las {r.hora_inicio:%H:%M}.")
            return redirect(f"/panel/?fecha={r.fecha.isoformat()}")
        except ValidationError as e:
            for m in e.messages:
                form.add_error(None, m)
    return render(request, "reservas/nueva.html", {"form": form})


@staff_member_required(login_url="login")
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


@staff_member_required(login_url="login")
def exportar_csv(request):
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="reservas-{timezone.localdate():%Y-%m-%d}.csv"'
    resp.write("﻿")
    w = csv.writer(resp, delimiter=";")
    w.writerow(["Código", "Fecha", "Inicio", "Término", "Clienta", "Celular", "Servicio", "Profesional", "Canal",
                "Estado", "Creada", "Creada por"])
    for r in Reserva.objects.select_related("clienta", "servicio", "profesional", "creada_por"):
        w.writerow([r.codigo, r.fecha.isoformat(), f"{r.hora_inicio:%H:%M}", f"{r.hora_fin:%H:%M}", r.clienta.nombre,
                    "+" + r.clienta.telefono, r.servicio.nombre, r.profesional.nombre if r.profesional else "",
                    r.get_canal_display(), r.get_estado_display(), timezone.localtime(r.creada_en).strftime("%Y-%m-%d %H:%M"),
                    r.creada_por.username if r.creada_por else "clienta (web)"])
    return resp
