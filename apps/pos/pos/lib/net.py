import socket


def detect_lan_ip() -> str:
    """LAN-IP машины кассы для генерации QR-pairing-URL планшету.

    Использует UDP-socket "connect" к публичному IP без отправки пакетов —
    стандартный трюк для получения исходящего интерфейса. При недоступности
    сети возвращает 127.0.0.1.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()
