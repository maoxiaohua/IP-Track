-- Migration: Add snmp_profile_id to switches (SNMP 模板引用)
-- Version: 028
-- Date: 2026-09-18
-- Description:
--   让交换机可以「引用」一条 snmp_profiles 记录，而不是各自复制一份 SNMP 凭据。
--   此前每台交换机的 username/auth_protocol/加密口令都单独存一份，改一次口令要
--   逐台改 200 多台；一旦漏改或改错，症状是设备侧回 WrongDigest，和「口令配错」
--   完全一样，极难排查。改成引用之后，口令只在模板上维护一处。
--
--   本迁移只加列和索引，**不回填历史数据**。原因：回填意味着把 200 多台的凭据
--   静默指向某一条模板，如果其中有设备本来就用着不同的账号口令，这一下就会把
--   它们全部改错 —— 正是本次要消灭的那类问题。挂接历史设备走显式动作
--   （POST /api/v1/snmp-profiles/{id}/adopt，带 dry_run 预览），由人在界面上确认。
--
--   引用语义：snmp_profile_id 非空时，该交换机的 SNMP 凭据一律取自模板，
--   交换机自身的 snmp_username/snmp_auth_protocol/*_encrypted 列被忽略
--   （但保留不动，便于随时解绑回退）。

ALTER TABLE switches
ADD COLUMN IF NOT EXISTS snmp_profile_id INTEGER
    REFERENCES snmp_profiles(id) ON DELETE SET NULL;

-- 按模板反查交换机（模板列表统计「使用中的交换机数」、删除模板前的引用检查）走这个索引
CREATE INDEX IF NOT EXISTS ix_switches_snmp_profile_id
    ON switches (snmp_profile_id);

COMMENT ON COLUMN switches.snmp_profile_id IS
    '引用的 SNMP 凭据模板 ID；非空时凭据以模板为准，本表的 snmp_* 凭据列被忽略';
