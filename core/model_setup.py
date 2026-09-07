"""Fetch configured models at image build time or warm them before serving."""
from .kyc_ocr import configured_kyc_languages
from .ocr_engine import _get_ocr


def warm_up() -> None:
    for language in dict.fromkeys(("en", *configured_kyc_languages())):
        _get_ocr(language)


if __name__ == "__main__":
    warm_up()
