"""Private production API/dashboard, reached over Docker or an SSH tunnel."""
from .production import *

DEBUG = False
ALLOWED_HOSTS = ['attendee-api', 'localhost', '127.0.0.1']
DATABASES = {'default': {
    'ENGINE': 'django.db.backends.postgresql', 'NAME': 'attendee', 'USER': 'attendee',
    'PASSWORD': os.environ['POSTGRES_PASSWORD'], 'HOST': 'postgres', 'PORT': '5432',
}}
ROOT_URLCONF = 'attendee.echooo_urls'
STORAGES['bot_debug_screenshots'] = {'BACKEND': 'attendee.echooo_debug.LocalDebugStorage'}
