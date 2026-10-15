# Create your models here.
from django.contrib.auth.models import AbstractUser
from simple_history.models import HistoricalRecords


class User(AbstractUser):
    history = HistoricalRecords(excluded_fields=["password", "last_login"])
