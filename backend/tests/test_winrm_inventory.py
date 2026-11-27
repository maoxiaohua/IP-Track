"""WinRM 硬件采集：输出解析 + 与 WMI 通路的结果合并。

两条通路（WMI / WinRM）字段口径必须一致，且 hardware_source 要跟随
真正提供 SN 的那条通路，避免前端来源标签说谎。
"""

import pytest

from services.winrm_inventory_service import (
    _extract_json_object,
    parse_hardware_payload,
)
from services.hardware_inventory_service import _merge_hardware


# ---------- JSON 提取 ----------

def test_extract_json_tolerates_noise():
    text = "PS C:\\> run\n{\"BiosSerial\":\"ABC123\"}\ntrailing"
    assert _extract_json_object(text) == {'BiosSerial': 'ABC123'}


def test_extract_json_rejects_garbage():
    assert _extract_json_object('') is None
    assert _extract_json_object('no json here') is None
    assert _extract_json_object('{broken') is None
    assert _extract_json_object('["a"]') is None


# ---------- 字段优先级 ----------

def test_parse_prefers_bios_serial():
    raw = b'{"BiosSerial":"SN001","ProductId":"PID1","BaseboardSerial":"MB1"}'
    result = parse_hardware_payload(raw)
    assert result['serial_number'] == 'SN001'
    assert result['hardware_source'] == 'winrm'


def test_parse_falls_back_to_product_then_baseboard():
    raw = b'{"BiosSerial":null,"ProductId":"PID1","BaseboardSerial":"MB1"}'
    assert parse_hardware_payload(raw)['serial_number'] == 'PID1'
    raw = b'{"BiosSerial":"","ProductId":null,"BaseboardSerial":"MB1"}'
    assert parse_hardware_payload(raw)['serial_number'] == 'MB1'


def test_parse_model_and_vendor_priority():
    raw = (
        b'{"ProductName":"OptiPlex 7080","SystemModel":"7080",'
        b'"SystemManufacturer":"Dell Inc.","ProductVendor":"Dell"}'
    )
    result = parse_hardware_payload(raw)
    assert result['device_model'] == 'OptiPlex 7080'
    assert result['hardware_vendor'] == 'Dell Inc.'


def test_parse_filters_placeholder_values():
    # 主板常见占位符必须被 clean_hardware_value 过滤，不能当 SN 落库
    raw = (b'{"BiosSerial":"To Be Filled By O.E.M.",'
           b'"ProductId":"System Serial Number","BaseboardSerial":"00000000"}')
    result = parse_hardware_payload(raw)
    # 全部是占位符 → 没有任何有效字段，整体返回 None
    assert result is None


def test_parse_takes_first_value_of_list():
    # ConvertTo-Json 对集合属性可能输出数组，只取第一个
    raw = b'{"BiosSerial":["SN001","SN002"]}'
    assert parse_hardware_payload(raw)['serial_number'] == 'SN001'


def test_parse_utf16_output():
    text = '{"BiosSerial":"SN-UTF16"}'
    raw = b'\xff\xfe' + text.encode('utf-16-le')
    assert parse_hardware_payload(raw)['serial_number'] == 'SN-UTF16'


def test_parse_returns_none_without_serial_or_model():
    assert parse_hardware_payload(b'{"BiosSerial":null,"ProductName":""}') is None
    assert parse_hardware_payload(b'') is None


def test_parse_model_only_is_kept():
    result = parse_hardware_payload(b'{"ProductName":"Laptop"}')
    assert result['serial_number'] is None
    assert result['device_model'] == 'Laptop'


# ---------- 两条通路合并 ----------

def test_merge_prefers_base_serial():
    base = {'serial_number': 'WMI-SN', 'device_model': None,
            'hardware_vendor': None, 'hardware_source': 'wmi'}
    extra = {'serial_number': 'WINRM-SN', 'device_model': 'ModelX',
             'hardware_vendor': 'Dell', 'hardware_source': 'winrm'}
    merged = _merge_hardware(base, extra)
    assert merged['serial_number'] == 'WMI-SN'
    assert merged['hardware_source'] == 'wmi'
    assert merged['device_model'] == 'ModelX'


def test_merge_source_follows_serial_provider():
    base = {'serial_number': None, 'device_model': 'FromWmi',
            'hardware_vendor': None, 'hardware_source': 'wmi'}
    extra = {'serial_number': 'WINRM-SN', 'device_model': None,
             'hardware_vendor': None, 'hardware_source': 'winrm'}
    merged = _merge_hardware(base, extra)
    assert merged['serial_number'] == 'WINRM-SN'
    assert merged['device_model'] == 'FromWmi'
    assert merged['hardware_source'] == 'winrm'


def test_merge_handles_missing_sides():
    base = {'serial_number': 'SN', 'hardware_source': 'wmi'}
    assert _merge_hardware(None, None) is None
    assert _merge_hardware(base, None) == base
    assert _merge_hardware(None, base)['serial_number'] == 'SN'
