"""Local storage implementing the small presigned-URL surface used upstream."""
from types import SimpleNamespace

from django.core import signing
from django.core.files.storage import FileSystemStorage


class LocalDebugStorage(FileSystemStorage):
    bucket_name = 'echooo-local-debug'

    def __init__(self):
        super().__init__(location='/attendee/local-debug')
        # BotDebugScreenshot.url calls this S3-style method even for local files.
        self.bucket = SimpleNamespace(meta=SimpleNamespace(client=self))

    def generate_presigned_url(self, operation, Params, ExpiresIn):
        if operation != 'get_object' or Params['Bucket'] != self.bucket_name:
            raise ValueError('Unsupported local storage operation')
        token = signing.dumps(Params['Key'], salt='echooo-debug')
        return '/echooo-debug/' + token
