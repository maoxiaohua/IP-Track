-- Migration: 放宽 snmp_profiles 的 priv_protocol 取值约束，接纳 AES-128
-- Version: 029
-- Date: 2026-09-18
-- Description:
--   用户在模板编辑页把加密协议从 AES 改成 AES-128，保存时报：
--     CheckViolationError: new row for relation "snmp_profiles"
--     violates check constraint "snmp_profiles_priv_protocol_check"
--
--   成因是这一列的取值清单在三处各写了一份，而其中一处漏了一个值：
--     * 约束（本文件的修复对象，建表时匿名 CHECK 自动命名为
--       snmp_profiles_priv_protocol_check）—— 只有 DES / AES / AES-192 / AES-256
--     * 前端下拉框 views/SNMPProfiles.vue —— 第一项就是 AES-128，还标着
--       「(Recommended)」；同一屏的认证协议下拉里 SHA-224 / SHA-256 / SHA-384 /
--       SHA-512 都是带连字符的写法
--     * 服务层 services/snmp_service.py 的 PRIV_PROTOCOL_MAP —— 本来就同时认
--       AES 和 AES128，两者归一化后映射到同一个对象 usmAesCfb128Protocol
--
--   也就是说：约束漏掉的恰好是界面首推、且运行时完全支持的那个写法。三处里
--   有两处认同一个值，只有约束不认，所以修约束而不是改界面。
--
--   本迁移**只放宽约束、不改动任何数据**：
--     - 原有的 AES / DES / AES-192 / AES-256 一律保留，已存在的行（当前库里
--       priv_protocol = 'AES'）不受影响；
--     - 新增的 AES-128 与原有的 AES 在运行期解析成同一个协议对象
--       （normalize_protocol_key 去掉连字符后都是 AES128），所以放行它不会让
--       任何一台设备的实际认证参数发生变化。
--
--   注意 database/init/09_enhance_ipam_solarwinds.sql 里的建表语句同步改了：
--   新装的库走 init 脚本、升级的库走本迁移，两边必须一致，否则新装的库能存
--   AES-128、升级的库不能，同一份代码在两个环境行为不同。

-- 先删后建，可重复执行。约束是建表时由 PostgreSQL 自动命名的，名字固定。
ALTER TABLE snmp_profiles
DROP CONSTRAINT IF EXISTS snmp_profiles_priv_protocol_check;

ALTER TABLE snmp_profiles
ADD CONSTRAINT snmp_profiles_priv_protocol_check
CHECK (
    priv_protocol IS NULL
    OR priv_protocol::text IN ('DES', 'AES', 'AES-128', 'AES-192', 'AES-256')
);

COMMENT ON CONSTRAINT snmp_profiles_priv_protocol_check ON snmp_profiles IS
    '加密协议取值清单，顺序与前端下拉框一致。AES 与 AES-128 是同一算法的两种写法，'
    '运行期经 normalize_protocol_key 归一化后等价，两个都留着是为了兼容已有数据。';
