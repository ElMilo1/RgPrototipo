from django.contrib import admin

from .models import Bloqueo, Clienta, HistorialReserva, HorarioAtencion, Profesional, Reserva, Servicio


@admin.register(Servicio)
class ServicioAdmin(admin.ModelAdmin):
    list_display = ("nombre", "duracion_min", "precio", "activo")
    list_editable = ("duracion_min", "precio", "activo")


@admin.register(Profesional)
class ProfesionalAdmin(admin.ModelAdmin):
    list_display = ("nombre", "rol", "activo")
    list_editable = ("rol", "activo")


@admin.register(HorarioAtencion)
class HorarioAdmin(admin.ModelAdmin):
    list_display = ("dia_semana", "abierto", "apertura", "cierre")
    list_editable = ("abierto", "apertura", "cierre")

    def has_add_permission(self, request):
        return HorarioAtencion.objects.count() < 7

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Bloqueo)
class BloqueoAdmin(admin.ModelAdmin):
    list_display = ("fecha", "hora_inicio", "hora_fin", "profesional", "motivo")
    list_filter = ("fecha",)


class HistorialInline(admin.TabularInline):
    model = HistorialReserva
    extra = 0
    can_delete = False
    readonly_fields = ("fecha_hora", "accion", "detalle", "usuario", "origen")
    fields = readonly_fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Reserva)
class ReservaAdmin(admin.ModelAdmin):
    list_display = ("codigo", "fecha", "hora_inicio", "hora_fin", "clienta", "servicio", "profesional", "canal", "estado")
    list_filter = ("estado", "canal", "fecha", "profesional")
    search_fields = ("codigo", "clienta__nombre", "clienta__telefono")
    date_hierarchy = "fecha"
    readonly_fields = ("codigo", "hora_fin", "creada_en", "actualizada_en", "creada_por")
    autocomplete_fields = ("clienta",)
    inlines = [HistorialInline]

    def save_model(self, request, obj, form, change):
        obj.save(usuario=request.user, origen="administración")

    def has_delete_permission(self, request, obj=None):
        # Para mantener la trazabilidad las reservas no se borran: se cancelan.
        return False


@admin.register(Clienta)
class ClientaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "telefono", "email", "consentimiento_en", "creada_en")
    search_fields = ("nombre", "telefono")
    readonly_fields = ("creada_en",)


@admin.register(HistorialReserva)
class HistorialAdmin(admin.ModelAdmin):
    list_display = ("fecha_hora", "accion", "reserva", "usuario", "origen", "detalle")
    list_filter = ("accion", "origen")
    search_fields = ("reserva__codigo", "detalle")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
