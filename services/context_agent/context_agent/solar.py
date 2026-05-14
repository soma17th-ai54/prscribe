from __future__ import annotations

import os


def solar_api_key() -> str:
    api_key = os.getenv("SOLAR_API_KEY") or os.getenv("UPSTAGE_API_KEY")
    if not api_key:
        raise RuntimeError("SOLAR_API_KEY or UPSTAGE_API_KEY is required.")
    return api_key
