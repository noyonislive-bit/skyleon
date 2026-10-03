from django.shortcuts import render

from apps.accounts.decorators import permission_required_code


@permission_required_code("client_portal.access")
def dashboard(request):
    projects = request.user.organization.projects.all() if request.user.organization_id else []
    return render(request, "clients/dashboard.html", {"projects": projects})
