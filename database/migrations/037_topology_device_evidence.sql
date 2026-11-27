-- 未纳管节点分类的置信度与判定依据（幂等，可重复执行）
ALTER TABLE topology_unknown_nodes
  ADD COLUMN IF NOT EXISTS device_confidence SMALLINT,
  ADD COLUMN IF NOT EXISTS device_reasons JSONB;
