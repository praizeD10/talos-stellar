"""Tests for idempotent purchase_service — crash-point and restart coverage.

State machine:
  (none) → signed → submitted → completed

Crash points:
  A  after sign_payment, before submit_commerce   → status=signed  → reuse stored sig
  B  after submit_commerce, before DB commit       → status=submitted → skip
  C  already completed                             → status=completed → skip
  D  happy path: begin_commerce_job called before submit_commerce
  E  sign failure: no row persisted
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import talos_agent.tools.commerce as commerce_mod
from talos_agent.db import LocalDB


# ── Helpers ──────────────────────────────────────────────────────────────────

_BUYER = "buyer-talos"
_SELLER = "seller-talos"
_SERVICE = "analytics"
_PAYLOAD = "{}"


def _job_key() -> str:
    raw = f"{_BUYER}:{_SELLER}:{_SERVICE}:{_PAYLOAD}".encode()
    return hashlib.sha256(raw).hexdigest()[:24]


def _api(price: str = "1.00", payee: str = "GPAY...") -> MagicMock:
    m = MagicMock()
    m.get_service = AsyncMock(
        return_value=MagicMock(
            status_code=402,
            json=lambda: {"price": price, "payee": payee},
            text="",
        )
    )
    m.submit_commerce = AsyncMock(return_value={"jobId": "srv-1", "status": "submitted"})
    m.create_approval = AsyncMock(return_value={"id": "appr-1"})
    return m


def _signer(header: str = "hdr") -> MagicMock:
    m = MagicMock()
    m.initialize = AsyncMock()
    m.sign_payment = AsyncMock(return_value={"status": "signed", "payment_header": header})
    return m


def _settings(buyer: str = _BUYER) -> MagicMock:
    m = MagicMock()
    m.approval_threshold = "50"
    m.talos_id = buyer
    return m


def _patch(api, db, settings, signer):
    return patch.multiple(
        "talos_agent.tools.commerce",
        _api=api,
        _db=db,
        _settings=settings,
        _get_signer=MagicMock(return_value=signer),
    )


# ── A: crash after sign, before submit ───────────────────────────────────────

@pytest.mark.asyncio
async def test_resume_after_crash_at_submit(tmp_path: Path) -> None:
    """status=signed → reuse stored sig, never call sign_payment again."""
    db = LocalDB(path=tmp_path / "test.db")
    db.begin_commerce_job(
        job_id=_job_key(),
        talos_id=_SELLER,
        service_type=_SERVICE,
        payment_sig="stored-hdr",
        price_usdc_units=1_000_000,
    )

    api = _api()
    signer = _signer()

    with _patch(api, db, _settings(), signer):
        result = await commerce_mod.purchase_service(_SELLER, _SERVICE, _PAYLOAD)

    assert result["status"] == "submitted"
    assert result.get("resumed") is True
    signer.sign_payment.assert_not_called()
    api.submit_commerce.assert_called_once_with(
        _SELLER, payment_header="stored-hdr", payload={}
    )


# ── B & C: terminal states skip all network calls ────────────────────────────

@pytest.mark.parametrize("terminal", ["submitted", "completed"])
@pytest.mark.asyncio
async def test_no_repayment_for_confirmed_job(tmp_path: Path, terminal: str) -> None:
    db = LocalDB(path=tmp_path / "test.db")
    db.begin_commerce_job(
        job_id=_job_key(),
        talos_id=_SELLER,
        service_type=_SERVICE,
        payment_sig="old-hdr",
        price_usdc_units=1_000_000,
    )
    db.update_commerce_status(_job_key(), terminal)

    api = _api()
    signer = _signer()

    with _patch(api, db, _settings(), signer):
        result = await commerce_mod.purchase_service(_SELLER, _SERVICE, _PAYLOAD)

    assert result["status"] == terminal
    assert result.get("resumed") is True
    signer.sign_payment.assert_not_called()
    api.submit_commerce.assert_not_called()
    api.get_service.assert_not_called()


# ── D: begin_commerce_job called before submit_commerce ──────────────────────

@pytest.mark.asyncio
async def test_happy_path_persists_sig_before_submit(tmp_path: Path) -> None:
    db = LocalDB(path=tmp_path / "test.db")
    db.set_talos_config({"gtmBudget": 200})

    api = _api(price="1.00")
    signer = _signer(header="fresh-hdr")

    call_order: list[str] = []

    orig_begin = LocalDB.begin_commerce_job

    def tracking_begin(self, *a, **kw):
        call_order.append("begin")
        return orig_begin(self, *a, **kw)

    async def tracking_submit(*a, **kw):
        call_order.append("submit")
        return {"jobId": "srv-1", "status": "submitted"}

    db.begin_commerce_job = lambda *a, **kw: tracking_begin(db, *a, **kw)
    api.submit_commerce = AsyncMock(side_effect=tracking_submit)

    with _patch(api, db, _settings(), signer):
        result = await commerce_mod.purchase_service(_SELLER, _SERVICE, _PAYLOAD)

    assert "error" not in result
    assert call_order.index("begin") < call_order.index("submit"), (
        "begin_commerce_job must be called before submit_commerce"
    )

    row = db._conn.execute(
        "SELECT payment_sig FROM commerce_queue WHERE job_id = ?", (_job_key(),)
    ).fetchone()
    assert row is not None
    assert row["payment_sig"] == "fresh-hdr"


# ── E: sign failure leaves no row ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sign_failure_writes_no_job_row(tmp_path: Path) -> None:
    db = LocalDB(path=tmp_path / "test.db")
    db.set_talos_config({"gtmBudget": 200})

    api = _api()
    signer = _signer()
    signer.sign_payment = AsyncMock(return_value={"error": "signer unavailable"})

    with _patch(api, db, _settings(), signer):
        result = await commerce_mod.purchase_service(_SELLER, _SERVICE, _PAYLOAD)

    assert "error" in result
    count = db._conn.execute("SELECT COUNT(*) FROM commerce_queue").fetchone()[0]
    assert count == 0
