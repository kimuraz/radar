"""# Celery/Django HOW-TO:
http://celery.readthedocs.io/en/latest/getting-started/first-steps-with-celery.html
http://celery.readthedocs.org/en/latest/django/first-steps-with-django.html
"""

from __future__ import absolute_import, unicode_literals
import os
from celery import Celery

# DJANGO_SETTINGS_MODULE já deve estar configurado como uma variável de ambiente.
# os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings.defaults')

app = Celery('radar_parlamentar')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django app configs.
app.autodiscover_tasks()