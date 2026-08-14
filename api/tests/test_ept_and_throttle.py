"""Behavioral tests for EPT verification and EI throttling.

These sign real ES256 tokens with a locally-generated key and verify against a
locally-served key set, so they exercise the ACTUAL crypto path with no network
dependency and no reliance on Eternitas being reachable.

This file exists because the suite it joins was ~86 "does the source contain
this string" assertions and zero that ran the auth decision — which is how a
live impersonation bypass passed every test on 2026-08-13.
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from api.app import ept as ept_mod
from api.app.auth import BAND_MULTIPLIER
from api.app.config import Settings
from api.app.ept import EptInvalid, verify_ept
from api.app.throttle import ACTION_BASE, limit_for

ISSUER = "eternitas.ai"
KID = "test-key-1"


@pytest.fixture
def signing(monkeypatch):
    """A real EC keypair; point the verifier's JWKS lookup at its public half."""
    key = ec.generate_private_key(ec.SECP256R1())

    class _FakeJWK:
        def __init__(self, k):
            self.key = k

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        def get_signing_key_from_jwt(self, token):
            header = jwt.get_unverified_header(token)
            if header.get("kid") != KID:
                raise Exception(f"unknown kid {header.get('kid')!r}")
            return _FakeJWK(key.public_key())

    monkeypatch.setattr(ept_mod, "_jwks_client", None)
    monkeypatch.setattr(ept_mod, "PyJWKClient", _FakeClient)
    return key


def _sign(key, claims, alg="ES256", kid=KID):
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": kid, "typ": "EPT"})


def _claims(**over):
    c = {
        "sub": "ET26-TEST-0001",
        "iss": ISSUER,
        "iat": int(time.time()) - 10,
        "exp": int(time.time()) + 3600,
    }
    c.update(over)
    return c


# ---- the property that was broken ----------------------------------------
def test_genuine_ept_is_accepted(signing):
    v = verify_ept(_sign(signing, _claims()), "https://api.eternitas.ai")
    assert v.passport == "ET26-TEST-0001"


def test_passport_comes_from_sub_not_a_passport_claim(signing):
    """Real EPTs put the passport in `sub`. The pre-fix code read `passport` /
    `sub_passport`, which no genuine EPT carries — so real agents were never
    recognised and only forged tokens ever worked."""
    tok = _sign(signing, _claims(sub="ET26-REAL-9999", passport="ET26-LIES-0000"))
    assert verify_ept(tok, "https://api.eternitas.ai").passport == "ET26-REAL-9999"


def test_alg_none_is_refused(signing):
    """The exact 2026-08-13 exploit."""
    import base64
    import json as _j

    def seg(d):
        return base64.urlsafe_b64encode(_j.dumps(d).encode()).rstrip(b"=").decode()

    forged = f"{seg({'alg':'none','typ':'EPT','kid':KID})}.{seg(_claims())}."
    with pytest.raises(EptInvalid):
        verify_ept(forged, "https://api.eternitas.ai")


def test_signature_from_a_different_key_is_refused(signing):
    attacker = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(EptInvalid):
        verify_ept(_sign(attacker, _claims()), "https://api.eternitas.ai")


def test_tampered_payload_is_refused(signing):
    tok = _sign(signing, _claims())
    h, _p, s = tok.split(".")
    import base64
    import json as _j

    evil = base64.urlsafe_b64encode(
        _j.dumps(_claims(sub="ET26-EVIL-0000")).encode()
    ).rstrip(b"=").decode()
    with pytest.raises(EptInvalid):
        verify_ept(f"{h}.{evil}.{s}", "https://api.eternitas.ai")


def test_expired_token_is_refused(signing):
    """Genuinely signed, genuinely expired — proves exp is enforced rather than
    the token merely failing to parse."""
    tok = _sign(signing, _claims(exp=int(time.time()) - 5, iat=int(time.time()) - 100))
    with pytest.raises(EptInvalid):
        verify_ept(tok, "https://api.eternitas.ai")


def test_wrong_issuer_is_refused(signing):
    """Correctly signed by a trusted key but claiming another issuer."""
    with pytest.raises(EptInvalid):
        verify_ept(_sign(signing, _claims(iss="evil.example.com")), "https://api.eternitas.ai")


def test_unknown_kid_is_refused(signing):
    with pytest.raises(EptInvalid):
        verify_ept(_sign(signing, _claims(), kid="attacker-key"), "https://api.eternitas.ai")


def test_missing_required_claims_are_refused(signing):
    for missing in ("sub", "exp"):
        c = _claims()
        c.pop(missing)
        with pytest.raises(EptInvalid):
            verify_ept(_sign(signing, c), "https://api.eternitas.ai")


def test_only_es256_is_ever_accepted():
    """Widening this list reopens algorithm confusion."""
    assert ept_mod.ALGORITHMS == ["ES256"]


# ---- the throttle that used to be dead code ------------------------------
def test_band_multiplier_is_actually_consumed():
    """BAND_MULTIPLIER was defined and read by nothing before this."""
    s = Settings()
    assert limit_for(s, "repo.create", "platinum") == s.rate_repo_creates_per_day * 10
    assert limit_for(s, "repo.create", "gold") == s.rate_repo_creates_per_day * 4
    assert limit_for(s, "repo.create", "standard") == s.rate_repo_creates_per_day
    assert limit_for(s, "repo.create", "watch") == s.rate_repo_creates_per_day // 2


def test_unknown_band_gets_standard_not_unlimited_and_not_zero():
    s = Settings()
    assert limit_for(s, "repo.create", "a-band-invented-tomorrow") == s.rate_repo_creates_per_day
    assert limit_for(s, "repo.create", None) == s.rate_repo_creates_per_day


def test_untrusted_band_is_read_only():
    assert BAND_MULTIPLIER["untrusted"] == 0


def test_every_throttled_action_has_a_configured_base():
    s = Settings()
    for action, field in ACTION_BASE.items():
        assert getattr(s, field) > 0, f"{action} has no positive base rate"


# ---- revocation enforced on the live trust path (not just the webhook) ----
def test_revoked_passport_is_refused_by_trust_decision():
    """A revoked passport returns HTTP 200, status=revoked, band=unproven,
    allowed=[] (verified live 2026-08-13). The decision must refuse it — the
    old code returned band 'unproven' and seated the agent."""
    from api.app.auth import PassportNotInGoodStanding, decide_trust

    revoked = {"status": "revoked", "band": "unproven", "allowed_actions": []}
    with pytest.raises(PassportNotInGoodStanding):
        decide_trust(revoked, "ET26-NJQT-QMR0")


def test_active_passport_is_accepted_by_trust_decision():
    from api.app.auth import decide_trust

    active = {"status": "active", "band": "gold", "allowed_actions": ["read", "send"]}
    band, actions = decide_trust(active, "ET26-1EF9-VJAN")
    assert band == "gold" and actions == ("read", "send")


def test_unknown_or_missing_status_fails_closed():
    from api.app.auth import PassportNotInGoodStanding, decide_trust

    for body in ({"band": "gold"}, {"status": "suspended"}, {"status": "frozen"},
                 {"status": ""}, {}):
        with pytest.raises(PassportNotInGoodStanding):
            decide_trust(body, "ET26-X")
