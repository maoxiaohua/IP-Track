-- Migration: 038 IPAM 硬件资产识别（SN / 设备型号）
-- Version: 038
-- Date: 2026-11-24
-- Description: 在线 IP 的 SN、型号、硬件厂商与采集来源/时间；幂等，可重复执行

-- 硬件资产字段（SN 采集自 SNMP ENTITY-MIB / Printer-MIB / HOST-RESOURCES 或 Windows WMI）
ALTER TABLE ip_addresses ADD COLUMN IF NOT EXISTS serial_number VARCHAR(200);
ALTER TABLE ip_addresses ADD COLUMN IF NOT EXISTS device_model VARCHAR(200);
ALTER TABLE ip_addresses ADD COLUMN IF NOT EXISTS hardware_vendor VARCHAR(200);
ALTER TABLE ip_addresses ADD COLUMN IF NOT EXISTS hardware_source VARCHAR(32);
ALTER TABLE ip_addresses ADD COLUMN IF NOT EXISTS hardware_collected_at TIMESTAMPTZ;
ALTER TABLE ip_addresses ADD COLUMN IF NOT EXISTS hardware_attempted_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_ip_addresses_serial_number ON ip_addresses(serial_number);
CREATE INDEX IF NOT EXISTS idx_ip_addresses_device_model ON ip_addresses(device_model);

-- 硬件盘点全局设置（口令类一律以 Fernet 密文存储，键名带 _encrypted）
INSERT INTO system_settings (key, value, data_type, description, is_configurable, is_sensitive)
VALUES
    ('hardware_inventory_enabled', 'true', 'boolean',
     'IPAM 硬件资产(SN/型号)自动采集开关', true, false),
    ('hardware_inventory_retry_hours', '24', 'integer',
     '硬件采集失败后的重试间隔(小时)', true, false),
    ('hardware_inventory_wmi_concurrency', '1', 'integer',
     'WMI 采集并发数(建议串行，避免域账号锁定)', true, false),
    ('hardware_inventory_wmi_max_per_sweep', '50', 'integer',
     '每轮 WMI 采集处理的最大 IP 数', true, false),
    ('snmp_default_community_encrypted', '', 'string',
     '未绑定 SNMP 模板时尝试的默认团体字(Fernet 密文)', false, true),
    ('wmi_domain', '', 'string',
     'Windows WMI 域(留空表示本机账号)', false, false),
    ('wmi_username', '', 'string',
     'Windows WMI 用户名', false, false),
    ('wmi_password_encrypted', '', 'string',
     'Windows WMI 口令(Fernet 密文)', false, true)
ON CONFLICT (key) DO NOTHING;
