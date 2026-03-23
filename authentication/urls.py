# authentication/urls.py

from django.urls import path

from authentication.views import (
    EmailVerifyView,
    LoginView,
    LogoutView,
    OTPSendView,
    OTPVerifyView,
    PasswordChangeView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    PhoneVerifyView,
    RegisterView,
)

app_name = "authentication"

urlpatterns = [
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),

    path("otp/send/", OTPSendView.as_view(), name="otp-send"),
    path("otp/verify/", OTPVerifyView.as_view(), name="otp-verify"),

    path("verify/email/", EmailVerifyView.as_view(), name="email-verify"),
    path("verify/phone/", PhoneVerifyView.as_view(), name="phone-verify"),

    path("password/change/", PasswordChangeView.as_view(), name="password-change"),
    path("password/reset/request/", PasswordResetRequestView.as_view(), name="password-reset-request"),
    path("password/reset/confirm/", PasswordResetConfirmView.as_view(), name="password-reset-confirm"),
]