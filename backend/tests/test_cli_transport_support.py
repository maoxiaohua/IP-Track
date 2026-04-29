from unittest.mock import Mock

from services.cli_service import CLIService


def test_normalize_cli_connection_settings_uses_telnet_defaults():
    cli_service = CLIService()

    transport, port = cli_service.normalize_cli_connection_settings(
        "telnet",
        None,
        port_was_explicit=False,
    )

    assert transport == "telnet"
    assert port == 23


def test_normalize_cli_connection_settings_preserves_explicit_port():
    cli_service = CLIService()

    transport, port = cli_service.normalize_cli_connection_settings(
        "telnet",
        20023,
        port_was_explicit=True,
    )

    assert transport == "telnet"
    assert port == 20023


def test_resolve_transport_device_type_prefers_vendor_telnet_driver():
    cli_service = CLIService()

    assert cli_service._resolve_transport_device_type("cisco_ios", "telnet") == "cisco_ios_telnet"
    assert cli_service._resolve_transport_device_type("juniper_junos", "telnet") == "juniper_junos_telnet"
    assert cli_service._resolve_transport_device_type("nokia_sros", "telnet") == "nokia_sros_telnet"


def test_resolve_transport_device_type_falls_back_to_generic_telnet():
    cli_service = CLIService()

    assert cli_service._resolve_transport_device_type("dell_os10", "telnet") == "generic_telnet"
    assert cli_service._resolve_transport_device_type("dell_force10", "telnet") == "generic_telnet"


def test_invalid_cli_transport_falls_back_to_ssh_defaults():
    cli_service = CLIService()

    transport, port = cli_service.normalize_cli_connection_settings(
        "serial-console",
        None,
        port_was_explicit=False,
    )

    assert transport == "ssh"
    assert port == 22


def test_disable_paging_uses_vendor_specific_command():
    cli_service = CLIService()
    connection = Mock()

    cli_service._disable_paging(connection, "cisco_ios", "10.0.0.1")

    connection.send_command_timing.assert_called_once_with(
        "terminal length 0",
        delay_factor=2,
        max_loops=50,
    )


def test_execute_command_prefers_timing_for_telnet():
    cli_service = CLIService()
    connection = Mock()
    connection.send_command_timing.return_value = "ok"

    output = cli_service._execute_command(
        connection,
        "show version",
        device_type="cisco_ios",
        transport="telnet",
    )

    assert output == "ok"
    connection.send_command.assert_not_called()


def test_execute_command_falls_back_to_timing_when_prompt_detection_fails():
    cli_service = CLIService()
    connection = Mock()
    connection.send_command.side_effect = RuntimeError("Pattern not detected")
    connection.send_command_timing.return_value = "ok"

    output = cli_service._execute_command(
        connection,
        "show version",
        device_type="cisco_ios",
        transport="ssh",
    )

    assert output == "ok"
    connection.send_command.assert_called_once_with("show version", read_timeout=90)
