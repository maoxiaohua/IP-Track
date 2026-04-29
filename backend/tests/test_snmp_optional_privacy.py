from pydantic import ValidationError

from schemas.switch import SwitchCreate
from services.snmp_service import SNMPService


def test_create_snmp_auth_uses_auth_no_priv_when_priv_password_missing(monkeypatch):
    service = SNMPService()
    captured = {}

    def fake_usm_user_data(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"args": args, "kwargs": kwargs}

    monkeypatch.setattr("services.snmp_service.UsmUserData", fake_usm_user_data)

    result = service._create_snmp_auth(
        username="snmp-user",
        auth_protocol="SHA",
        auth_password="authpass123",
        priv_protocol=None,
        priv_password=None,
    )

    assert result["args"] == ("snmp-user",)
    assert result["kwargs"]["authKey"] == "authpass123"
    assert "privKey" not in result["kwargs"]
    assert "privProtocol" not in result["kwargs"]


def test_create_snmp_auth_preserves_privacy_when_password_present(monkeypatch):
    service = SNMPService()
    captured = {}

    def fake_usm_user_data(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"args": args, "kwargs": kwargs}

    monkeypatch.setattr("services.snmp_service.UsmUserData", fake_usm_user_data)

    result = service._create_snmp_auth(
        username="snmp-user",
        auth_protocol="SHA",
        auth_password="authpass123",
        priv_protocol="AES128",
        priv_password="privpass123",
    )

    assert result["args"] == ("snmp-user",)
    assert result["kwargs"]["authKey"] == "authpass123"
    assert result["kwargs"]["privKey"] == "privpass123"
    assert "privProtocol" in result["kwargs"]


def test_switch_create_allows_snmpv3_without_privacy_password():
    switch = SwitchCreate(
        name="test-switch",
        ip_address="10.0.0.1",
        vendor="cisco",
        snmp_version="3",
        snmp_username="snmp-user",
        snmp_auth_password="authpass123",
        snmp_priv_password=None,
    )

    assert switch.snmp_priv_password is None


def test_switch_create_rejects_short_privacy_password_when_provided():
    try:
        SwitchCreate(
            name="test-switch",
            ip_address="10.0.0.1",
            vendor="cisco",
            snmp_version="3",
            snmp_username="snmp-user",
            snmp_auth_password="authpass123",
            snmp_priv_password="short",
        )
    except ValidationError as exc:
        assert "snmp_priv_password" in str(exc)
    else:
        raise AssertionError("Expected validation error for short SNMP privacy password")


def test_switch_create_allows_snmpv2c_without_v3_passwords():
    switch = SwitchCreate(
        name="test-switch",
        ip_address="10.0.0.2",
        vendor="cisco",
        snmp_version="2c",
        snmp_community="public",
    )

    assert switch.snmp_version == "2c"
    assert switch.snmp_community == "public"
