from __future__ import annotations

import base64
import csv
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mock_api.app import create_app
from mock_api.config import PROJECT_ROOT, Settings

REFERENCE = PROJECT_ROOT / "data" / "reference"
# What the mock API served for the last real run: the weekend-viewing copy if it exists.
SERVED = (
    PROJECT_ROOT / "data" / "source" if (PROJECT_ROOT / "data" / "source").is_dir() else REFERENCE
)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return replace(Settings.from_env(), chaos=False, preload=False)


@pytest.fixture(scope="session")
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture(scope="session")
def mri_auth(settings: Settings) -> dict[str, str]:
    user = (
        f"{settings.mri_client_id}/{settings.mri_database}/"
        f"{settings.mri_user}/{settings.mri_partner_key}"
    )
    token = base64.b64encode(f"{user}:{settings.mri_password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture(scope="session")
def fixflo_auth(settings: Settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.fixflo_token}"}


@pytest.fixture(scope="session")
def engage_auth(settings: Settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.engage_token}"}


def read_reference(table: str) -> tuple[list[str], list[list[str]]]:
    with (REFERENCE / "extracts" / f"{table}.csv").open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        return header, list(reader)


def sample(rel: str) -> Path:
    return REFERENCE / "api_samples" / rel
