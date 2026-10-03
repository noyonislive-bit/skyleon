from django.conf import settings
from django.utils.functional import SimpleLazyObject

from . import site_settings


def site(request):
    return {
        "brand": site_settings.BRAND,
        "company": SimpleLazyObject(site_settings.company),
        "APP_URL": settings.APP_URL,
        "DEBUG": settings.DEBUG,
    }
