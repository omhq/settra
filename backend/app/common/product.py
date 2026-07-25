import os

DEFAULT_PRODUCT_NAME = "Settra"

PRODUCT_NAME = os.getenv("PRODUCT_NAME", DEFAULT_PRODUCT_NAME).strip()

if not PRODUCT_NAME:
    PRODUCT_NAME = DEFAULT_PRODUCT_NAME

AI_CLIENT_DESCRIPTION = (
    f"Use {PRODUCT_NAME} to answer business questions with live data from the "
    "tools your business already uses. It can bring information together and "
    "remember business rules you approve, without repeated exports or uploads."
)
