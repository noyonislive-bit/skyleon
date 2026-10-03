from django.conf import settings
from django.db import models, transaction


class SiteSetting(models.Model):
    """Key/value settings editable from Admin → Settings (company info, notification emails …)."""

    key = models.CharField(max_length=100, primary_key=True)
    value = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.key


class Counter(models.Model):
    """Atomic named counters, e.g. the running employee ID number."""

    key = models.CharField(max_length=100, primary_key=True)
    value = models.PositiveIntegerField(default=0)

    @classmethod
    def next(cls, key: str) -> int:
        with transaction.atomic():
            counter, _ = cls.objects.select_for_update().get_or_create(key=key)
            counter.value += 1
            counter.save(update_fields=["value"])
            return counter.value


class AuditLog(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_logs")
    action = models.CharField(max_length=100)  # e.g. "employee.approve"
    entity_type = models.CharField(max_length=50, blank=True)
    entity_id = models.CharField(max_length=50, blank=True)
    meta = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["entity_type", "entity_id"])]

    def __str__(self):
        return f"{self.action} {self.entity_type}:{self.entity_id}"
