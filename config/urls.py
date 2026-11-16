from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

admin.site.site_header = "RG Beauty Spa · Administración"
admin.site.site_title = "RG Beauty Spa"
admin.site.index_title = "Configuración del sistema de reservas"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("ingresar/", auth_views.LoginView.as_view(template_name="reservas/login.html"), name="login"),
    path("salir/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("reservas.urls")),
]
