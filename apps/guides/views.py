from django.http import HttpResponse

from apps.accounts.decorators import employee_required, permission_required_code


@employee_required
def guide_list(request):
    return HttpResponse("Work guides (coming soon)")


@permission_required_code("content.manage")
def manage_list(request):
    return HttpResponse("Manage guides (coming soon)")
