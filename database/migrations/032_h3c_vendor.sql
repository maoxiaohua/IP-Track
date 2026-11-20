-- 032: 放开 switches.vendor 的 CHECK，支持 H3C（Comware）
-- 幂等：重复执行会先删掉旧约束再重建。
-- 注意：database/migrations 不会自动执行，升级时需手工 psql 应用本文件。

DO $$
DECLARE
    con_name text;
BEGIN
    -- 约束是建表时内联定义的（未命名），名称由 PostgreSQL 自动生成，
    -- 这里按「作用在 switches 表、类型 check、定义里含 vendor」来定位。
    FOR con_name IN
        SELECT c.conname
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE t.relname = 'switches'
          AND n.nspname = current_schema()
          AND c.contype = 'c'
          AND pg_get_constraintdef(c.oid) ILIKE '%vendor%'
    LOOP
        EXECUTE format('ALTER TABLE switches DROP CONSTRAINT %I', con_name);
    END LOOP;
END
$$;

-- NOT VALID + VALIDATE：建约束只取瞬时锁，校验是只读扫描，不阻塞写入。
ALTER TABLE switches
    ADD CONSTRAINT switches_vendor_check
    CHECK (vendor IN ('cisco', 'dell', 'alcatel', 'juniper', 'h3c'))
    NOT VALID;

ALTER TABLE switches VALIDATE CONSTRAINT switches_vendor_check;
