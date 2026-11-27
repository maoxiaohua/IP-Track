-- Migration: 039 按账号保存的界面偏好（列显示选择）
-- Version: 039
-- Date: 2026-11-26
-- Description: user_ui_preferences 表；幂等，可重复执行

CREATE TABLE IF NOT EXISTS user_ui_preferences (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    pref_key VARCHAR(80) NOT NULL,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_ui_preferences_user_key UNIQUE (user_id, pref_key)
);

CREATE INDEX IF NOT EXISTS idx_user_ui_preferences_user_id
    ON user_ui_preferences(user_id);
