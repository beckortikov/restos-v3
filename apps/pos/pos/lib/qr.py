import io

import segno


def render_qr_svg(url: str, scale: int = 8) -> bytes:
    """SVG QR-кода для url; H-уровень коррекции — устойчив к бликам на экране."""
    qr = segno.make(url, error="h")
    buf = io.BytesIO()
    qr.save(buf, kind="svg", scale=scale, border=2, xmldecl=False, svgns=True)
    return buf.getvalue()
