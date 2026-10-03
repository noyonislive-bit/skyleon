from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.urls import reverse
from django.utils import timezone


class Role(models.TextChoices):
    SUPER_ADMIN = "super_admin", "Super Admin"
    PROJECT_MANAGER = "project_manager", "Project Manager"
    TRAINER = "trainer", "Trainer / QA"
    EMPLOYEE = "employee", "Employee"
    CLIENT = "client", "Client"


STAFF_ROLES = {Role.SUPER_ADMIN, Role.PROJECT_MANAGER, Role.TRAINER}


class UserStatus(models.TextChoices):
    PENDING = "pending", "Pending approval"
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"


class Organization(models.Model):
    """A client company. Groundwork for the phase-2 client portal."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=120, unique=True)
    contact_email = models.EmailField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("role", Role.EMPLOYEE)
        extra.setdefault("status", UserStatus.PENDING)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.update(role=Role.SUPER_ADMIN, status=UserStatus.ACTIVE, is_staff=True, is_superuser=True)
        extra.setdefault("name", "Administrator")
        user = self._create_user(email, password, **extra)
        if not user.employee_id:
            user.assign_employee_id()
        return user


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    employee_id = models.CharField(max_length=20, unique=True, null=True, blank=True)
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=40, blank=True)
    location = models.CharField(max_length=120, blank=True)
    title = models.CharField("Job title", max_length=120, blank=True)
    bio = models.TextField(blank=True)
    skills = models.JSONField(default=list, blank=True)

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.EMPLOYEE, db_index=True)
    status = models.CharField(max_length=20, choices=UserStatus.choices, default=UserStatus.PENDING, db_index=True)
    organization = models.ForeignKey(Organization, null=True, blank=True, on_delete=models.SET_NULL, related_name="users")

    # Django internals: is_active is kept in sync with `status` (suspended → inactive).
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False, help_text="Can open the low-level Django admin (/django-admin/).")

    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    suspended_at = models.DateTimeField(null=True, blank=True)
    date_joined = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["name"]

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} <{self.email}>"

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        self.is_active = self.status != UserStatus.SUSPENDED
        super().save(*args, **kwargs)

    # ── Convenience ────────────────────────────────────────────────────────
    def get_full_name(self):
        return self.name

    def get_short_name(self):
        return self.name.split(" ")[0] if self.name else self.email

    @property
    def first_name(self):
        return self.get_short_name()

    @property
    def initials(self):
        parts = [p for p in self.name.split() if p][:2]
        return "".join(p[0].upper() for p in parts) or self.email[:1].upper()

    @property
    def is_staff_role(self) -> bool:
        return self.role in STAFF_ROLES

    @property
    def is_super_admin(self) -> bool:
        return self.role == Role.SUPER_ADMIN

    @property
    def is_employee(self) -> bool:
        return self.role == Role.EMPLOYEE

    @property
    def is_client(self) -> bool:
        return self.role == Role.CLIENT

    @property
    def is_pending(self) -> bool:
        return self.status == UserStatus.PENDING

    @property
    def is_approved(self) -> bool:
        return self.status == UserStatus.ACTIVE

    def has_perm_code(self, code: str) -> bool:
        from .permissions import has_permission

        return has_permission(self, code)

    def home_url(self) -> str:
        if self.role == Role.CLIENT:
            return reverse("clients:dashboard")
        if self.role in STAFF_ROLES:
            return reverse("backoffice:dashboard")
        return reverse("portal:dashboard")

    def assign_employee_id(self, save=True):
        from apps.core.models import Counter

        number = Counter.next("employee_id")
        self.employee_id = f"{settings.EMPLOYEE_ID_PREFIX}-{number:04d}"
        if save:
            self.save(update_fields=["employee_id", "updated_at"])
        return self.employee_id
