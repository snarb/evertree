"""Explicit component fixtures, with no application startup or Git repository."""

import pytest


@pytest.fixture
async def app(tmp_path):
    from tests.support.component import component_app

    async with component_app(tmp_path / "agent") as app:
        yield app


@pytest.fixture
async def agent(app):
    return app
