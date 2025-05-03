from django.urls import path
from . import views

urlpatterns = [
    path('signup/', views.signup, name='signup'),
    path('login/', views.login, name='login'),
    path('get_user_profile/', views.user_profile, name='get_user_profile'),
    path('verify_email/', views.verify_email, name='verify_email'),
    path('resend_otp/', views.resend_otp, name='resend_otp'),
    path('change_password/', views.change_password, name='change_password'),
    path('forgot_password/', views.forgot_password, name='forgot_password'),
    path('logout/', views.logout, name='logout'),
    path('update_user_profile/', views.update_user_profile, name='update_user_profile'),
    path('all_user_list/', views.all_user_list, name='all_user_list')
]
