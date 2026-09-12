"""Called by manage.py shell; credentials are supplied privately via env_file."""
import hashlib
import os
from accounts.models import Organization, User
from allauth.account.models import EmailAddress
from bots.models import Project, ApiKey

org, _ = Organization.objects.get_or_create(name='Echooo local')
project, _ = Project.objects.get_or_create(organization=org, name='Echooo')
ApiKey.objects.get_or_create(key_hash=hashlib.sha256(os.environ['ECHOOO_CONNECTOR_KEY'].encode()).hexdigest(),
    defaults={'project': project, 'name': 'Echooo local'})
user, created = User.objects.get_or_create(username='echooo',
    defaults={'organization': org, 'email': 'echooo@localhost', 'is_staff': True, 'is_superuser': True})
if created:
    user.set_password(os.environ['ECHOOO_ADMIN_PASSWORD'])
    user.save()
# This provisioned local address cannot receive email. Allauth's normal login
# requires a verified EmailAddress, even though Django admin login does not.
if user.email == 'echooo@localhost':
    EmailAddress.objects.update_or_create(user=user, email=user.email,
        defaults={'verified': True, 'primary': True})
print('Echooo connector project and local account are ready.')
