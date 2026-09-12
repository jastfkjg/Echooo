"""Local-only Attendee dashboard; never expose this development server publicly."""
from .development import *

ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'api']
DATABASES['default'].update(NAME='attendee', USER='attendee', PASSWORD=os.environ['POSTGRES_PASSWORD'])
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
ROOT_URLCONF = 'attendee.echooo_urls'
# Error screenshots/logs stay local; normal meeting audio is stored by Echooo.
STORAGES['bot_debug_screenshots'] = {'BACKEND': 'attendee.echooo_debug.LocalDebugStorage'}
