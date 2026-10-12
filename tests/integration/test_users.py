import pytest

from apps.users.models import User
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_create_user_normalises_email_and_hashes_password():
    user = User.objects.create_user(email="Someone@EXAMPLE.com", password="pw-12345!")
    assert user.email == "Someone@example.com"  # domain part lowercased
    assert user.password != "pw-12345!" and user.check_password("pw-12345!")
    assert not user.is_staff


def test_create_superuser():
    admin = User.objects.create_superuser(email="admin@example.com", password="x")
    assert admin.is_staff and admin.is_superuser


def test_email_is_required():
    with pytest.raises(ValueError):
        User.objects.create_user(email="", password="x")


def test_admin_login_and_changelist(client):
    admin = UserFactory(is_staff=True, is_superuser=True)
    client.force_login(admin)
    response = client.get("/admin/users/user/")
    assert response.status_code == 200
    assert admin.email.encode() in response.content
