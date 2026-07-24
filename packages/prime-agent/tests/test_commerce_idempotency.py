"""Tests for idempotent purchase_service execution.

Crash-point coverage:
  A  crash after sign, before submit  → status='signed'  → reuse stored sig, no re-sign
  B  crash after submit, before DB write → status='submitted' → skip entirely
  C  already completed                → status='completed' → skip entirely
  D  happy path: begin_commerce_job called before submit_commerce
  E  sign failure: no job row written to DB
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import hashlib

import pytest

import talos_agent.tools.commerce as commerce_mod
from talos_agent.db import LocalDB


# ── Helpers ──────────────────────────────────────────────────────────────────

_TALOS_ID = "seller-talos"
_SERVICE = "analytics"
_PAYLOAD = "{}"
_BUYER = "buyer-talos"


def _job_key() -> str:
    """Reproduce the key derivation from purchase_service."""
    raw = f"{_BUYER}:{_TALOS_ID}:{_SERVICE}:{_PAYLOAD}".encode()
    return hashlib.sha256(raw).hexdigest()[:24]


def _make_api(price: str = "1.00", payee: str = "GPAY...") -> MagicMock:
    api = MagicMock()
    api.get_service = AsyncMock(
        return_value=MagicMock(
            status_code=402,
            json=lambda: {"price": price, "payee": payee},
            text="",
        )
    )
    api.submit_commerce = AsyncMock(return_value={"jobId": "srv-job-1", "status": "submitted"})
    api.create_approval = AsyncMock(return_value={"id": "appr-1"})
    return api


def _make_signer(header: str = "x402-hdr") -> MagicMock:
    signer = MagicMock()
    signer.initialize = AsyncMock()
    signer.sign_payment = AsyncMock(
        return_value={"status": "signed", "payment_header": header}
    )
    return signer


def _make_settings(buyer: str = _BUYER) -> MagicMock:
    s = MagicMock()
    s.approval_threshold = "50"
    s.talos_id = buyer
    return s


def _ctx(api, db, settings, signer):
    return patch.multiple(
        "talos_agent.tools.commerce",
        _api=api,
        _db=db,
        _settings=settings,
        _get_signer=MagicMock(return_value=signer),
    )


# ── Crash-point A: signed but submit never happened ──────────────────────────

@pytest.mark.asyncio
async def test_resume_after_crash_at_submit(tmp_path: Path) -> None:
    """Process died after sign_payment but before submit_commerce.
    Next call must reuse the stored payment_sig and never re-sign."""
    db = LocalDB(path=tmp_path / "test.db")
    db.begin_commerce_job(
        job_id=_job_key(),
        talos_id=_TALOS_ID,
        service_type=_SERVICE,
        payment_sig="stored-hdr",
        price_usdc_units=1_000_000,
    )

    api = _make_api()
    signer = _make_signer()
    settings = _make_settings()

    with _ctx(api, db, settings, signer):
        result = await commerce_mod.purchase_service(_TALOS_ID, _SERVICE, _PAYLOAD)

    assert result["status"] == "submitted"
    assert result.get("resumed") is True
    signer.sign_payment.assert_not_called()
    api.submit_commerce.assert_called_once_with(
        _TALOS_ID, payment_header="stored-hdr", payload={}
    )


# ── Crash-points B & C: terminal states skip everything ──────────────────────

@pytest.mark.parametrize("terminal_status", ["submitted", "completed"])
@pytest.mark.asyncio
async def test_no_repayment_when_already_confirmed(
    tmp_path: Path, terminal_status: str
) -> None:
    """A job already in submitted or completed state must never trigger payment."""
    db = LocalDB(path=tmp_path / "test.db")
    db.begin_commerce_job(
        job_id=_job_key(),
        talos_id=_TALOS_ID,
        service_type=_SERVICE,
        payment_sig="old-hdr",
        price_usdc_units=1_000_000,
    )
    db.update_commerce_status(_job_key(), terminal_status)

    api = _make_api()
    signer = _make_signer()
    settings = _make_settings()

    with _ctx(api, db, settings, signer):
        result = await commerce_mod.purchase_service(_TALOS_ID, _SERVICE, _PAYLOAD)

    assert result["status"] == terminal_status
    assert result.get("resumed") is True
    signer.sign_payment.assert_not_called()
    api.submit_commerce.assert_not_called()
    api.get_service.assert_not_called()


# ── Happy path: begin_commerce_job happens before submit_commerce ─────────────

@pytest.mark.asyncio
async def test_happy_path_persists_sig_before_submit(tmp_path: Path) -> None:
    """Fresh purchase: the signed header is persisted (status=signed) before
    submit_commerce is called, so any crash between the two is recoverable."""
    db = LocalDB(path=tmp_path / "test.db")
    db.set_talos_config({"gtmBudget": 200})

    api = _make_api(price="1.00")
    signer = _make_signer(header="fresh-hdr")
    settings = _make_settings()

    call_order: list[str] = []

    original_begin = db.begin_commerce_job.__func__  # unbound for tracking
    original_submit = api.submit_commerce._mock_wraps  # not used — we wrap below

    def _tracking_begin(self_db, *a, **kw):
        call_order.append("begin")
        return LocalDB.begin_commerce_job(self_db, *a, **kw)

    async def _tracking_submit(*a, **kw):
        call_order.append("submit")
        return {"jobId": "srv-1", "status": "submitted"}

    db.begin_commerce_job = lambda *a, **kw: (_tracking_begin(db, *a, **kw))
    api.submit_commerce = AsyncMock(side_effect=_tracking_submit)

    with _ctx(api, db, settings, signer):
        result = await commerce_mod.purchase_service(_TALOS_ID, _SERVICE, _PAYLOAD)

    assert "error" not in result
    assert call_order.index("begin") < call_order.index("submit"), (
        "begin_commerce_job must be called before submit_commerce"
    )

    row = db._conn.execute(
        "SELECT payment_sig, status FROM commerce_queue WHERE job_id = ?",
        (_job_key(),),
    ).fetchone()
    assert row is not None
    assert row["payment_sig"] == "fresh-hdr"


# ── Sign failure: no job row must be written ──────────────────────────────────

@pytest.mark.asyncio
async def test_sign_error_does_not_write_job(tmp_path: Path) -> None:
    """If sign_payment fails, we must not persist a job row."""
    db = LocalDB(path=tmp_path / "test.db")
    db.set_talos_config({"gtmBudget": 200})

    api = _make_api()
    signer = _make_signer()
    signer.sign_payment = AsyncMock(return_value={"error": "signer unavailable"})
    settings = _make_settings()

    with _ctx(api, db, settings, signer):
        result = await commerce_mod.purchase_service(_TALOS_ID, _SERVICE, _PAYLOAD)

    assert "error" in result
    count = db._conn.execute("SELECT COUNT(*) FROM commerce_queue").fetchone()[0]
    assert count == 0
