-- 035: 交换机配置备份模块
-- 幂等：所有建表/加列都带 IF NOT EXISTS，vendor 约束先删后建。
-- 设计要点：
--   * config_blobs 按 sha256 内容寻址存正文，内容未变不新增记录，避免每天存一份同样的配置；
--   * config_backups 记录每一次备份尝试（running/success/failed/unsupported），失败原因也留档；
--   * 备份是**只读**操作，绝不向设备下发写配置命令。

-- 备份正文（内容寻址）
CREATE TABLE IF NOT EXISTS config_blobs (
    sha256      VARCHAR(64) PRIMARY KEY,
    content     TEXT NOT NULL,
    size_bytes  INTEGER NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 备份记录/版本
CREATE TABLE IF NOT EXISTS config_backups (
    id                SERIAL PRIMARY KEY,
    switch_id         INTEGER NOT NULL REFERENCES switches(id) ON DELETE CASCADE,
    status            VARCHAR(20) NOT NULL,          -- running | success | failed | unsupported
    trigger_source    VARCHAR(20) NOT NULL,          -- manual | scheduled
    sha256            VARCHAR(64) REFERENCES config_blobs(sha256) ON DELETE SET NULL,
    size_bytes        INTEGER,
    file_path         TEXT,
    device_type       VARCHAR(50),
    command           VARCHAR(200),
    message           TEXT,
    started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at       TIMESTAMPTZ,
    duration_ms       INTEGER
);

CREATE INDEX IF NOT EXISTS idx_config_backups_switch_started
    ON config_backups (switch_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_config_backups_status_started
    ON config_backups (status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_config_backups_sha256
    ON config_backups (sha256);

-- 每台交换机的备份开关/间隔覆盖/命令覆盖（留空则走预设计表与全局默认）
ALTER TABLE switches ADD COLUMN IF NOT EXISTS backup_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE switches ADD COLUMN IF NOT EXISTS backup_interval_minutes INTEGER;
ALTER TABLE switches ADD COLUMN IF NOT EXISTS backup_device_type VARCHAR(50);
ALTER TABLE switches ADD COLUMN IF NOT EXISTS backup_config_command VARCHAR(200);

-- 全局默认（可在配置备份页面修改）
INSERT INTO system_settings (key, value, data_type, description, is_configurable, is_sensitive)
VALUES
    ('config_backup_interval_minutes', '1440', 'integer',
     '交换机配置备份全局默认间隔（分钟），单台可覆盖', true, false),
    ('config_backup_retention_versions', '30', 'integer',
     '每台交换机保留的配置版本数（按内容去重后）', true, false)
ON CONFLICT (key) DO NOTHING;

-- 放开 vendor 白名单，覆盖市面主流品牌
DO $$
DECLARE
    con_name text;
BEGIN
    FOR con_name IN
        SELECT c.conname
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE t.relname = 'switches'
          AND n.nspname = current_schema()
          AND c.contype = 'c'
          AND c.conname = 'switches_vendor_check'
    LOOP
        EXECUTE format('ALTER TABLE switches DROP CONSTRAINT %I', con_name);
    END LOOP;
END
$$;

ALTER TABLE switches
    ADD CONSTRAINT switches_vendor_check
    CHECK (vendor IN (
        'cisco', 'dell', 'alcatel', 'juniper', 'arista', 'hpe', 'huawei', 'h3c',
        'fortinet', 'extreme', 'aruba', 'mikrotik', 'paloalto', 'other'
    ))
    NOT VALID;

ALTER TABLE switches VALIDATE CONSTRAINT switches_vendor_check;
