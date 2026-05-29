import os

API_BASE_URL: str = os.environ.get("RESTOS_API_URL", "http://127.0.0.1:8000").rstrip("/")
RESTAURANT_ID: int = int(os.environ.get("RESTOS_RESTAURANT_ID", "1"))

SSE_RECONNECT_DELAY_S: float = float(os.environ.get("RESTOS_SSE_RECONNECT_S", "2"))
HTTP_TIMEOUT_S: float = float(os.environ.get("RESTOS_HTTP_TIMEOUT_S", "10"))
HTTP_RETRIES: int = int(os.environ.get("RESTOS_HTTP_RETRIES", "3"))

KEYRING_SERVICE: str = os.environ.get("RESTOS_KEYRING_SERVICE", "restos-cashier")

AUTO_LOCK_MIN: int = int(os.environ.get("RESTOS_AUTO_LOCK_MIN", "30"))

PAIR_URL: str = os.environ.get("RESTOS_PAIR_URL", "").strip()


def get_pair_url() -> str:
    """URL, который попадает в QR для подключения планшета.

    Если задан `RESTOS_PAIR_URL` — используем как есть (override).
    Иначе — собираем `http://<lan-ip>:<port>/`, где порт берём из API_BASE_URL
    (если backend на 8001, QR тоже на 8001 — иначе планшет получит
    Connection refused).
    """
    if PAIR_URL:
        return PAIR_URL
    from urllib.parse import urlparse

    from pos.lib.net import detect_lan_ip

    parsed = urlparse(API_BASE_URL)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    scheme = parsed.scheme or "http"
    return f"{scheme}://{detect_lan_ip()}:{port}/"
