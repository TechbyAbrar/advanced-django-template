from django.db import models
from django.contrib.auth.models import AbstractBaseUser,PermissionsMixin
from django.utils import timezone
from datetime import timedelta
from accounts.managers import UserManager
import random
import string

class UserAuth(AbstractBaseUser,PermissionsMixin):
    class Meta:
        verbose_name_plural = "User"
    user_id = models.AutoField(primary_key=True)
    email = models.EmailField(unique=True, null=True, blank=True)
    phone = models.CharField(
        max_length=15,
        unique=True,
        null=True,
        blank=True,
        validators=[RegexValidator(r"^\+?\d{9,15}$", message="Phone number must be valid")]
    )
    username = models.CharField(max_length=50, unique=True, null=True, blank=True)
    full_name = models.CharField(max_length=100, null=True, blank=True)
    
    dob = models.DateField(blank=True, null=True)

    profile_pic = models.ImageField(
        upload_to="profile/",
        default="profile/profile.png",
        null=True,
        blank=True,
        validators=[validate_image],
    )

    otp = models.CharField(max_length=6, blank=True, null=True)
    otp_expired = models.DateTimeField(blank=True, null=True)

    is_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    
    is_online = models.BooleanField(default=False)
    last_login = models.DateTimeField(blank=True, null=True)
    last_activity = models.DateTimeField(blank=True, null=True, db_index=True)
    
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    # Required by Django
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"] # Fields required when creating superuser 
    # "username", "phone"
    objects = UserManager()

    def __str__(self):
        return self.username or self.email or self.phone or f"User-{self.pk}"
    
    def set_otp(self, otp: str = None, expiry_minutes: int = 30) -> None:
        self.otp = otp or generate_otp()
        self.otp_expired = get_otp_expiry(expiry_minutes)
        
    def is_otp_valid(self, otp: str) -> bool:
        return self.otp == otp and self.otp_expired and timezone.now() <= self.otp_expired
    
    def get_age(self):
        if not self.dob:
            return None

        today = date.today()
        age = today.year - self.dob.year

        if (today.month, today.day) < (self.dob.month, self.dob.day):
            age -= 1

        return age