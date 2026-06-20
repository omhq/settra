import base64


def base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def quote_ident(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'
