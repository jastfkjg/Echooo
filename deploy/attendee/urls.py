from django.contrib.auth.decorators import login_required
from django.core import signing
from django.http import FileResponse, Http404
from django.urls import path

from attendee.urls import urlpatterns as upstream
from bots.models import BotDebugScreenshot


@login_required
def debug_file(request, token):
    try:
        name = signing.loads(token, salt='echooo-debug', max_age=1800)
    except signing.BadSignature:
        raise Http404
    artifact = BotDebugScreenshot.objects.filter(file=name,
        bot_event__bot__project__organization=request.user.organization).first()
    if not artifact or not artifact.file.storage.exists(name):
        raise Http404
    return FileResponse(artifact.file.open('rb'), as_attachment=not name.endswith('.png'))


urlpatterns = [path('echooo-debug/<str:token>', debug_file), *upstream]
