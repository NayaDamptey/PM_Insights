"""Mock API settings, read from the environment / ``.env``."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    # MRI (Qube v1 and MRIAPIServices): Basic ClientID/Database/User/PartnerKey:Password
    mri_client_id: str
    mri_database: str
    mri_user: str
    mri_partner_key: str
    mri_password: str
    # FixFlo v2: Bearer token
    fixflo_token: str
    # Engage: MRI publishes no API reference for Engage, so a bearer token stands in
    # until the real scheme is known. Only auth.py needs to change when it is.
    engage_token: str
    # chaos*: answer a share of requests with 429 so client retry/backoff gets exercised.
    # preload: read every CSV at start-up (~20 s) so the first API calls are not slow.
    chaos: bool
    chaos_rate: float
    chaos_seed: int | None
    retry_after_seconds: int
    preload: bool

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> Settings:
        load_dotenv(env_file or PROJECT_ROOT / ".env", override=False)

        def req(name: str) -> str:
            value = os.getenv(name)
            if not value:
                raise RuntimeError(f"{name} is not set. Copy .env.example to .env and fill it in.")
            return value

        seed = os.getenv("MOCK_CHAOS_SEED")
        return cls(
            data_dir=Path(os.getenv("MOCK_DATA_DIR") or PROJECT_ROOT / "data" / "reference"),
            mri_client_id=req("MRI_CLIENT_ID"),
            mri_database=req("MRI_DATABASE"),
            mri_user=req("MRI_WEB_SERVICES_USER"),
            mri_partner_key=req("MRI_PARTNER_KEY"),
            mri_password=req("MRI_PASSWORD"),
            fixflo_token=req("FIXFLO_API_TOKEN"),
            engage_token=req("ENGAGE_API_TOKEN"),
            chaos=_bool(os.getenv("MOCK_CHAOS")),
            chaos_rate=float(os.getenv("MOCK_CHAOS_RATE") or 0.02),
            chaos_seed=int(seed) if seed else None,
            retry_after_seconds=int(os.getenv("MOCK_RETRY_AFTER_SECONDS") or 1),
            preload=_bool(os.getenv("MOCK_PRELOAD"), default=True),
        )
