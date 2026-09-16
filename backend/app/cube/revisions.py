import hashlib


def model_content_revision(content: str) -> str:
    """Match the authored YAML fingerprint attached to Cube's compiler snapshot."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
