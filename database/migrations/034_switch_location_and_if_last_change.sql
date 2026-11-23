-- 交换机位置：人工标注的机房/机柜/楼层，用于列表展示与按位置排序。
ALTER TABLE switches ADD COLUMN IF NOT EXISTS location VARCHAR(100);

-- ifLastChange（IF-MIB 1.3.6.1.2.1.2.2.1.9）是「距设备启动的百分之一秒数」，
-- 采集时配合 sysUpTime 换算成绝对时间落库，用来判断端口闲置多长。
-- last_change_ticks 保留原始值，便于排查换算结果。
ALTER TABLE switch_interfaces ADD COLUMN IF NOT EXISTS last_change_ticks BIGINT;
ALTER TABLE switch_interfaces ADD COLUMN IF NOT EXISTS last_change_at TIMESTAMPTZ;
