from services.cli_service import CLIService


def test_preview_template_match_falls_back_to_builtin_cisco_template():
    cli_service = CLIService()

    result = cli_service.preview_template_match(
        vendor="cisco",
        model="WS-C4506",
        name="CNHZ-L2-DXB1F-1C407-C4506-RF-SW11",
        templates=[],
    )

    assert result is not None
    assert result["source"] == "builtin"
    assert result["template"]["device_type"] == "cisco_ios"
    assert result["template"]["model_pattern"] == "*"


def test_preview_template_match_prefers_higher_priority_database_template():
    cli_service = CLIService()
    templates = [
        {
            "id": 11,
            "vendor": "cisco",
            "model_pattern": "*",
            "device_type": "cisco_ios",
            "arp_command": "show ip arp",
            "arp_parser_type": "cisco_ios",
            "mac_command": "show mac address-table",
            "mac_parser_type": "cisco_ios",
            "priority": 100,
            "enabled": True,
            "is_builtin": False,
        },
        {
            "id": 12,
            "vendor": "cisco",
            "model_pattern": "ws-c4506*",
            "name_pattern": "*c4506*",
            "device_type": "cisco_ios",
            "arp_command": "show ip arp",
            "arp_parser_type": "cisco_ios",
            "mac_command": "show mac address-table",
            "mac_parser_type": "cisco_ios",
            "priority": 250,
            "enabled": True,
            "is_builtin": False,
        },
    ]

    result = cli_service.preview_template_match(
        vendor="cisco",
        model="WS-C4506",
        name="CNHZ-L2-DXB1F-1C407-C4506-RF-SW11",
        templates=templates,
    )

    assert result is not None
    assert result["source"] == "database"
    assert result["template"]["id"] == 12
    assert result["template"]["model_pattern"] == "ws-c4506*"


def test_preview_template_match_supports_substring_model_patterns():
    cli_service = CLIService()
    templates = [
        {
            "id": 21,
            "vendor": "cisco",
            "model_pattern": "4506",
            "device_type": "cisco_ios",
            "arp_command": "show ip arp",
            "arp_parser_type": "cisco_ios",
            "mac_command": "show mac address-table",
            "mac_parser_type": "cisco_ios",
            "priority": 180,
            "enabled": True,
            "is_builtin": False,
        }
    ]

    result = cli_service.preview_template_match(
        vendor="cisco",
        model="WS-C4506",
        name="CNHZ-L2-DXB1F-1C407-C4506-RF-SW11",
        templates=templates,
    )

    assert result is not None
    assert result["source"] == "database"
    assert result["template"]["id"] == 21
