from datetime import date, datetime, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

ESTADOS_ACTIVOS = ("agendada", "asistio", "no_show")

validar_telefono = RegexValidator(
    regex=r"^569\d{8}$",
    message="Ingresa un celular chileno válido, por ejemplo 9 1234 5678.",
)


def normalizar_telefono(valor):
    """Deja el celular como 569XXXXXXXX sin importar cómo lo escriban."""
    digitos = "".join(c for c in str(valor or "") if c.isdigit())
    if len(digitos) == 9 and digitos.startswith("9"):
        digitos = "56" + digitos
    elif len(digitos) == 8:
        digitos = "569" + digitos
    return digitos


class Servicio(models.Model):
    nombre = models.CharField(max_length=80, unique=True)
    duracion_min = models.PositiveIntegerField("duración (min)", validators=[MinValueValidator(15)])
    precio = models.PositiveIntegerField("precio ($)", default=0)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return f"{self.nombre} ({self.duracion_min} min)"


class Profesional(models.Model):
    nombre = models.CharField(max_length=80)
    rol = models.CharField(max_length=60, blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre"]
        verbose_name_plural = "profesionales"

    def __str__(self):
        return self.nombre


class HorarioAtencion(models.Model):
    DIAS = [(0, "Lunes"), (1, "Martes"), (2, "Miércoles"), (3, "Jueves"), (4, "Viernes"), (5, "Sábado"), (6, "Domingo")]
    dia_semana = models.PositiveSmallIntegerField(choices=DIAS, unique=True)
    abierto = models.BooleanField(default=True)
    apertura = models.TimeField(default="10:00")
    cierre = models.TimeField(default="19:00")

    class Meta:
        ordering = ["dia_semana"]
        verbose_name = "horario de atención"
        verbose_name_plural = "horarios de atención"

    def clean(self):
        if self.abierto and self.apertura >= self.cierre:
            raise ValidationError("La hora de cierre debe ser posterior a la de apertura.")

    def __str__(self):
        if not self.abierto:
            return f"{self.get_dia_semana_display()}: cerrado"
        return f"{self.get_dia_semana_display()}: {self.apertura:%H:%M} a {self.cierre:%H:%M}"


class Bloqueo(models.Model):
    """Horario en que no se atiende (almuerzo, trámite, feriado)."""
    fecha = models.DateField()
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()
    profesional = models.ForeignKey(Profesional, null=True, blank=True, on_delete=models.CASCADE,
                                    help_text="Vacío = bloquea a todo el spa.")
    motivo = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["fecha", "hora_inicio"]

    def clean(self):
        if self.hora_inicio and self.hora_fin and self.hora_inicio >= self.hora_fin:
            raise ValidationError("La hora de término debe ser posterior a la de inicio.")

    def __str__(self):
        return f"{self.fecha:%d-%m-%Y} {self.hora_inicio:%H:%M}–{self.hora_fin:%H:%M} {self.motivo}"


class Clienta(models.Model):
    nombre = models.CharField(max_length=100)
    telefono = models.CharField("celular", max_length=11, unique=True, null=True, blank=True, validators=[validar_telefono])
    email = models.EmailField(blank=True)
    consentimiento_en = models.DateTimeField("consentimiento de datos", null=True, blank=True)
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return f"{self.nombre} (+{self.telefono})" if self.telefono else self.nombre


class Reserva(models.Model):
    CANALES = [("web", "Web"), ("whatsapp", "WhatsApp"), ("instagram", "Instagram"),
               ("telefono", "Teléfono"), ("presencial", "Presencial")]
    ESTADOS = [("agendada", "Agendada"), ("asistio", "Asistió"), ("no_show", "No llegó"), ("cancelada", "Cancelada")]

    codigo = models.CharField(max_length=12, unique=True, editable=False)
    clienta = models.ForeignKey(Clienta, on_delete=models.PROTECT, related_name="reservas")
    servicio = models.ForeignKey(Servicio, on_delete=models.PROTECT)
    profesional = models.ForeignKey(Profesional, on_delete=models.PROTECT, null=True, blank=True)
    fecha = models.DateField()
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField(editable=False)
    canal = models.CharField(max_length=12, choices=CANALES, default="web")
    estado = models.CharField(max_length=10, choices=ESTADOS, default="agendada")
    notas = models.TextField(blank=True)
    confirmada_en = models.DateTimeField("asistencia confirmada por la clienta", null=True, blank=True, editable=False)
    creada_en = models.DateTimeField(auto_now_add=True)
    actualizada_en = models.DateTimeField(auto_now=True)
    creada_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name="reservas_creadas", editable=False)

    class Meta:
        ordering = ["fecha", "hora_inicio"]
        constraints = [
            # Regla del negocio: dos reservas vigentes no pueden tener el mismo día y la misma hora.
            models.UniqueConstraint(fields=["fecha", "hora_inicio"], condition=Q(estado__in=ESTADOS_ACTIVOS),
                                    name="una_reserva_por_dia_y_hora",
                                    violation_error_message="Ya existe una reserva para ese día y esa hora."),
            models.CheckConstraint(condition=Q(hora_fin__gt=models.F("hora_inicio")), name="fin_despues_de_inicio"),
        ]
        indexes = [models.Index(fields=["fecha", "estado"])]

    def __str__(self):
        return f"{self.codigo} · {self.fecha:%d-%m-%Y} {self.hora_inicio:%H:%M} · {self.clienta.nombre}"

    # ---------- utilidades ----------
    @staticmethod
    def sumar_minutos(hora, minutos):
        return (datetime.combine(date.today(), hora) + timedelta(minutes=minutos)).time()

    def calcular_fin(self):
        if self.hora_inicio and self.servicio_id:
            self.hora_fin = self.sumar_minutos(self.hora_inicio, self.servicio.duracion_min)

    @property
    def activa(self):
        return self.estado in ESTADOS_ACTIVOS

    # ---------- validaciones de horario ----------
    def clean(self):
        errores = []
        if not (self.fecha and self.hora_inicio and self.servicio_id):
            return
        self.calcular_fin()
        reglas = settings.AGENDA
        ahora = timezone.localtime()

        es_nueva_o_reprogramada = self._cambio_horario()

        if es_nueva_o_reprogramada and self.activa:
            if self.fecha < ahora.date() or (self.fecha == ahora.date() and self.hora_inicio <= ahora.time()):
                errores.append("No se puede reservar en una fecha u hora que ya pasó.")
            if self.fecha > ahora.date() + timedelta(days=reglas["DIAS_ANTICIPACION"]):
                errores.append(f"Solo se puede reservar con hasta {reglas['DIAS_ANTICIPACION']} días de anticipación.")

        if self.hora_fin <= self.hora_inicio:
            errores.append("El servicio termina después de medianoche.")

        if es_nueva_o_reprogramada and self.activa:
            minutos = self.hora_inicio.hour * 60 + self.hora_inicio.minute
            if self.hora_inicio.second or minutos % reglas["INTERVALO_MIN"]:
                errores.append(f"La hora debe calzar con bloques de {reglas['INTERVALO_MIN']} minutos (por ejemplo 10:00 o 10:30).")

            horario = HorarioAtencion.objects.filter(dia_semana=self.fecha.weekday()).first()
            if not horario or not horario.abierto:
                errores.append("El spa no atiende ese día.")
            elif self.hora_inicio < horario.apertura or self.hora_fin > horario.cierre:
                errores.append(f"La reserva debe quedar dentro del horario de atención ({horario.apertura:%H:%M} a {horario.cierre:%H:%M}).")

            if not self.servicio.activo:
                errores.append("Ese servicio no está disponible.")
            if self.profesional_id and not self.profesional.activo:
                errores.append("Esa profesional no está disponible.")
            choque = self.reserva_que_choca()
            if choque:
                if choque.hora_inicio == self.hora_inicio:
                    errores.append(f"Ya existe una reserva el {self.fecha:%d-%m-%Y} a las {self.hora_inicio:%H:%M}. Elige otra hora.")
                else:
                    errores.append(f"La hora se cruza con otra reserva ({choque.hora_inicio:%H:%M} a {choque.hora_fin:%H:%M}). Elige otra hora.")
            bloqueo = self.bloqueo_que_choca()
            if bloqueo:
                errores.append(f"Ese horario está bloqueado ({bloqueo.hora_inicio:%H:%M} a {bloqueo.hora_fin:%H:%M}{', ' + bloqueo.motivo if bloqueo.motivo else ''}).")

        if errores:
            raise ValidationError(errores)

    def _cambio_horario(self):
        if not self.pk:
            return True
        previa = Reserva.objects.filter(pk=self.pk).values("fecha", "hora_inicio", "estado").first()
        return not previa or (previa["fecha"], previa["hora_inicio"]) != (self.fecha, self.hora_inicio) or previa["estado"] not in ESTADOS_ACTIVOS

    def reserva_que_choca(self):
        qs = Reserva.objects.filter(fecha=self.fecha, estado__in=ESTADOS_ACTIVOS).exclude(pk=self.pk)
        # Misma fecha y misma hora: siempre prohibido
        igual = qs.filter(hora_inicio=self.hora_inicio).first()
        if igual:
            return igual
        cruces = qs.filter(hora_inicio__lt=self.hora_fin, hora_fin__gt=self.hora_inicio)
        if settings.AGENDA["AGENDA_POR_PROFESIONAL"] and self.profesional_id:
            cruces = cruces.filter(Q(profesional_id=self.profesional_id) | Q(profesional__isnull=True))
        return cruces.first()

    def bloqueo_que_choca(self):
        qs = Bloqueo.objects.filter(fecha=self.fecha, hora_inicio__lt=self.hora_fin, hora_fin__gt=self.hora_inicio)
        if self.profesional_id:
            qs = qs.filter(Q(profesional__isnull=True) | Q(profesional_id=self.profesional_id))
        else:
            qs = qs.filter(profesional__isnull=True) if settings.AGENDA["AGENDA_POR_PROFESIONAL"] else qs
        return qs.first()

    # ---------- guardado con trazabilidad ----------
    def save(self, *args, usuario=None, origen="", detalle="", **kwargs):
        self.calcular_fin()
        anterior = None
        if self.pk:
            anterior = Reserva.objects.filter(pk=self.pk).first()
        if not self.codigo:
            ultimo = Reserva.objects.order_by("-id").values_list("id", flat=True).first() or 0
            self.codigo = f"RG-{ultimo + 1:05d}"
        if not self.pk and usuario and usuario.is_authenticated:
            self.creada_por = usuario
        super().save(*args, **kwargs)

        if anterior is None:
            HistorialReserva.registrar(self, "creada", usuario, origen,
                                       detalle or f"{self.servicio.nombre} el {self.fecha:%d-%m-%Y} a las {self.hora_inicio:%H:%M} por {self.get_canal_display()}")
            return
        cambios = []
        for campo, etiqueta in [("estado", "estado"), ("fecha", "fecha"), ("hora_inicio", "hora"),
                                ("servicio_id", "servicio"), ("profesional_id", "profesional"), ("notas", "notas")]:
            antes, despues = getattr(anterior, campo), getattr(self, campo)
            if antes != despues:
                if campo == "estado":
                    antes, despues = dict(self.ESTADOS)[antes], dict(self.ESTADOS)[despues]
                elif campo == "servicio_id":
                    antes, despues = anterior.servicio.nombre, self.servicio.nombre
                elif campo == "profesional_id":
                    antes = anterior.profesional.nombre if anterior.profesional else "sin asignar"
                    despues = self.profesional.nombre if self.profesional else "sin asignar"
                cambios.append(f"{etiqueta}: {antes} → {despues}")
        if cambios:
            accion = "cancelada" if self.estado == "cancelada" and anterior.estado != "cancelada" else "modificada"
            HistorialReserva.registrar(self, accion, usuario, origen, "; ".join(cambios) + (f". {detalle}" if detalle else ""))


class HistorialReserva(models.Model):
    """Registro inalterable de todo lo que le pasa a una reserva."""
    ACCIONES = [("creada", "Creada"), ("modificada", "Modificada"), ("cancelada", "Cancelada"), ("intento_rechazado", "Intento rechazado")]
    reserva = models.ForeignKey(Reserva, null=True, blank=True, on_delete=models.PROTECT, related_name="historial")
    accion = models.CharField(max_length=20, choices=ACCIONES)
    detalle = models.TextField()
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    origen = models.CharField(max_length=30, blank=True, help_text="web pública, panel, administración")
    fecha_hora = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha_hora", "-id"]
        verbose_name = "registro del historial"
        verbose_name_plural = "historial de reservas"

    def __str__(self):
        return f"{self.fecha_hora:%d-%m-%Y %H:%M} {self.get_accion_display()} {self.reserva.codigo if self.reserva else ''}"

    @classmethod
    def registrar(cls, reserva, accion, usuario=None, origen="", detalle=""):
        return cls.objects.create(reserva=reserva, accion=accion, detalle=detalle, origen=origen,
                                  usuario=usuario if usuario and usuario.is_authenticated else None)

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("El historial no se puede modificar.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("El historial no se puede borrar.")


class SolicitudWhatsApp(models.Model):
    """Clienta que prefiere que el spa la contacte para darle hora (reserva asistida)."""
    PREFERENCIAS = [("manana", "Mañana (10:00 a 13:00)"), ("tarde", "Tarde (14:00 a 19:00)"), ("cualquiera", "Me da lo mismo")]
    nombre = models.CharField(max_length=100)
    telefono = models.CharField("celular", max_length=11, validators=[validar_telefono])
    servicio = models.ForeignKey(Servicio, null=True, blank=True, on_delete=models.SET_NULL)
    preferencia = models.CharField(max_length=12, choices=PREFERENCIAS, default="cualquiera")
    creada_en = models.DateTimeField(auto_now_add=True)
    atendida = models.BooleanField(default=False)
    reserva = models.ForeignKey(Reserva, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["atendida", "creada_en"]
        verbose_name = "solicitud por WhatsApp"
        verbose_name_plural = "solicitudes por WhatsApp"

    def __str__(self):
        return f"{self.nombre} (+{self.telefono})"
