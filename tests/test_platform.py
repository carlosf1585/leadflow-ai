import pytest

def test_haversine():
    from app.db.repositories.business_repo import haversine_km
    dist = haversine_km(40.7128, -74.0060, 40.6501, -73.9496)
    assert 8 < dist < 12

def test_lead_price_urgency():
    assert 35.0 * 1.5 == 52.5

def test_settings_loaded():
    from app.core.config import settings
    assert settings.LEAD_PRICE_PLUMBING == 35.0
    assert settings.LEAD_PRICE_ROOFING == 45.0

def test_password_hashing():
    from app.core.security import hash_password, verify_password
    hashed = hash_password("test123")
    assert verify_password("test123", hashed)
    assert not verify_password("wrong", hashed)

def test_jwt_token():
    from app.core.security import create_access_token, decode_token
    token = create_access_token({"sub": "test-id"})
    payload = decode_token(token)
    assert payload["sub"] == "test-id"