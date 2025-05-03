from django.contrib import admin
from .models import UserAuth
# Register your models here.

@admin.register(UserAuth)
class UserAuthAdmin(admin.ModelAdmin):
    list_display = ['email', 'full_name', 'is_verified', 'is_staff', 'is_superuser']
    search_fields = ['email', 'first_name', 'last_name']
    list_filter = ['is_verified', 'is_staff', 'is_superuser']