-- 网络不可达的交换机暂停计划备份，等 TCP 探测恢复可达后自动继续。
ALTER TABLE switches ADD COLUMN IF NOT EXISTS backup_unreachable BOOLEAN NOT NULL DEFAULT FALSE;
