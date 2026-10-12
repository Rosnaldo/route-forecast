from io import StringIO

import pytest
from django.core.management import call_command


@pytest.mark.django_db
def test_wait_for_db():
    out = StringIO()
    call_command("wait_for_db", timeout=1, stdout=out)
    assert "Database available" in out.getvalue()
