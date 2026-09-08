from django.apps import apps
from django.core.management import call_command


def test_chores_app_is_installed():
    assert apps.is_installed("chores")


def test_system_check_passes():
    call_command("check")


def test_home_page_loads(client):
    response = client.get("/")
    assert response.status_code == 200
