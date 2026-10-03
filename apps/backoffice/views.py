from django.http import HttpResponse

from apps.accounts.decorators import staff_required


@staff_required
def dashboard(request):
    return HttpResponse("Admin dashboard (placeholder)")


@staff_required
def placeholder(request, **kwargs):
    return HttpResponse("Placeholder")
