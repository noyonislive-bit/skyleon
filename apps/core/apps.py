from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"
    verbose_name = "Core"

    def ready(self):
        from django.db.models.signals import post_migrate

        from .signals import top_up_sample_data

        post_migrate.connect(top_up_sample_data, sender=self, dispatch_uid="core.top_up_sample_data")
