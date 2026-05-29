"""Reset URL caches между тестами в telemetry/ — несколько тестов меняют
SUPERADMIN_ENABLED и перечитывают urlconf. Без сброса между тестами один
override может «протечь» в следующий тест.
"""
from importlib import reload

import pytest
from django.urls import clear_url_caches


@pytest.fixture(autouse=True)
def _reset_urlconf_after_each():
    yield
    from config import urls as cfg_urls
    clear_url_caches()
    reload(cfg_urls)
