import secrets
import string


def new_team_pin(length=6):
    return "".join(secrets.choice(string.digits) for _ in range(length))


def new_qr_token():
    return secrets.token_urlsafe(36)
