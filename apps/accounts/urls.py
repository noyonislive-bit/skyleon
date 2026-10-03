from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("client/login/", views.login_view, {"portal": "client"}, name="client_login"),
    path("logout/", views.logout_view, name="logout"),
    path("signup/", views.signup_view, name="signup"),
    path("account/welcome/", views.after_login, name="after_login"),
    path("account/pending/", views.pending_view, name="pending"),
    path("password/forgot/", views.PasswordResetView.as_view(), name="password_reset"),
    path("password/forgot/sent/", views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path("password/set/<uidb64>/<token>/", views.PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("password/set/done/", views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),
]
