from django.http import HttpResponse

from apps.accounts.decorators import employee_required


@employee_required
def dashboard(request):
    return HttpResponse("Portal dashboard (placeholder)")


@employee_required
def placeholder(request, **kwargs):
    return HttpResponse("Placeholder")
