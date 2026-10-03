import logging

from django.http import HttpResponseServerError, JsonResponse
from django.shortcuts import render

logger = logging.getLogger(__name__)

# Used when even the styled 500 page cannot be rendered (e.g. the database is down and the
# context processors that read site settings fail too).
PLAIN_500 = ("<!doctype html><meta charset=utf-8><title>Error 500</title>"
             "<div style='font-family:system-ui,sans-serif;max-width:32rem;margin:15vh auto;padding:0 1rem;color:#121c17'>"
             "<h1>Something went wrong · কিছু একটা সমস্যা হয়েছে</h1>"
             "<p>Please try again in a moment. · একটু পরে আবার চেষ্টা করুন।</p><p><a href='/'>Home</a></p></div>")


def error_404(request, exception=None):
    return render(request, "errors/404.html", status=404)


def error_403(request, exception=None):
    return render(request, "errors/403.html", status=403)


def error_500(request):
    try:
        return render(request, "errors/500.html", status=500)
    except Exception:  # never let the error page itself fail
        logger.exception("Could not render the 500 page")
        return HttpResponseServerError(PLAIN_500)


def health(request):
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute("SELECT 1")
    return JsonResponse({"status": "ok"})
