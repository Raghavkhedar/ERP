from django.urls import path

from . import views

app_name = "plans"

urlpatterns = [
    path("today/", views.today, name="today"),
    path("<int:user_id>/export/", views.export_plans, name="export"),
    path("<int:user_id>/<int:year>/<int:month>/<int:day>/", views.view, name="view"),
]
