from django.urls import path

from . import views

app_name = "backoffice"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("employees/<int:pk>/", views.placeholder, name="employee_detail"),
]
