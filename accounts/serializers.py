from rest_framework import serializers
from .models import UserAuth


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserAuth
        fields = ['id', 'email', 'full_name', 'otp', 'is_verified','is_active','is_staff','is_superuser','date_joined']


# 'profile_pic'