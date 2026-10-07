from io import BytesIO

import qrcode


def render_qr(payload):
    image = qrcode.make(payload)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def scan_url(token):
    """Use the canonical event URL so TLS proxy/Host headers cannot poison printed QRs."""
    from flask import current_app, request
    base = current_app.config.get("PUBLIC_BASE_URL") or request.host_url
    return base.rstrip("/") + "/scan/" + token
