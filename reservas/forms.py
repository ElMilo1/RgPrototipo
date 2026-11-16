from django import forms

from .models import Profesional, Reserva, Servicio, normalizar_telefono


class DatosClientaForm(forms.Form):
    nombre = forms.CharField(max_length=100)
    telefono = forms.CharField(label="Celular", max_length=20, widget=forms.TextInput(attrs={"placeholder": "9 1234 5678", "inputmode": "tel"}))
    email = forms.EmailField(label="Correo (opcional)", required=False)

    def clean_telefono(self):
        tel = normalizar_telefono(self.cleaned_data["telefono"])
        if not tel and not self.fields["telefono"].required:
            return ""
        if len(tel) != 11 or not tel.startswith("569"):
            raise forms.ValidationError("Ingresa un celular chileno válido, por ejemplo 9 1234 5678.")
        return tel


class ReservaPublicaForm(DatosClientaForm):
    consentimiento = forms.BooleanField(
        label="Acepto que usen mi nombre y celular solo para mis reservas.",
        error_messages={"required": "Para reservar necesitamos que aceptes el uso de tus datos."})


class ReservaPanelForm(DatosClientaForm):
    telefono = forms.CharField(label="Celular (opcional)", max_length=20, required=False)
    servicio = forms.ModelChoiceField(queryset=Servicio.objects.filter(activo=True))
    profesional = forms.ModelChoiceField(queryset=Profesional.objects.filter(activo=True), required=False,
                                         empty_label="Asignar automáticamente")
    fecha = forms.DateField(widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}), input_formats=["%Y-%m-%d"])
    hora_inicio = forms.TimeField(label="Hora", widget=forms.TimeInput(format="%H:%M", attrs={"type": "time", "step": 1800}), input_formats=["%H:%M"])
    canal = forms.ChoiceField(choices=[c for c in Reserva.CANALES if c[0] != "web"])
    notas = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))


class BuscarReservaForm(forms.Form):
    telefono = forms.CharField(label="Celular con que reservaste", max_length=20,
                               widget=forms.TextInput(attrs={"placeholder": "9 1234 5678", "inputmode": "tel"}))


class SolicitudForm(forms.Form):
    nombre = forms.CharField(max_length=100)
    telefono = forms.CharField(label="Celular", max_length=20)
    servicio = forms.ModelChoiceField(queryset=Servicio.objects.filter(activo=True), required=False, empty_label="No sé todavía")
    preferencia = forms.ChoiceField(label="¿Cuándo te acomoda?", choices=[("manana", "Mañana (10:00 a 13:00)"), ("tarde", "Tarde (14:00 a 19:00)"), ("cualquiera", "Me da lo mismo")])
    consentimiento = forms.BooleanField(label="Acepto que usen mi nombre y celular solo para coordinar esta reserva.",
                                        error_messages={"required": "Necesitamos tu autorización para contactarte."})

    def clean_telefono(self):
        tel = normalizar_telefono(self.cleaned_data["telefono"])
        if len(tel) != 11 or not tel.startswith("569"):
            raise forms.ValidationError("Ingresa un celular chileno válido, por ejemplo 9 1234 5678.")
        return tel
