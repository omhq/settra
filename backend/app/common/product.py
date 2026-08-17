import os

DEFAULT_PRODUCT_NAME = "Settra"

PRODUCT_NAME = os.getenv("PRODUCT_NAME", DEFAULT_PRODUCT_NAME).strip()

if not PRODUCT_NAME:
    PRODUCT_NAME = DEFAULT_PRODUCT_NAME

AI_CLIENT_DESCRIPTION = (
    f"Use {PRODUCT_NAME} to make sheet data available to automated agents. "
    "It reads current values through governed semantic models, without "
    "repeated exports or uploads."
)
