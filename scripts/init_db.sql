-- 光影鉴赏家 Agent 长期记忆表（与业务表同库 shineconnoisseur，前缀 agent_）
-- 注意：服务启动时也会自动执行 CREATE TABLE IF NOT EXISTS，此文件供手动初始化/DBA 参考

CREATE TABLE IF NOT EXISTS agent_user_profile (
  user_id          BIGINT PRIMARY KEY COMMENT '关联 user.id',
  genre_prefs      JSON COMMENT '类型偏好 {"科幻":3,"剧情":1} 频次加权',
  actor_prefs      JSON COMMENT '演员偏好频次',
  director_prefs   JSON COMMENT '导演偏好频次',
  region_prefs     JSON COMMENT '地区偏好频次',
  rating_tendency  JSON COMMENT '打分倾向 {"avg":7.2,"count":4,"min":5,"max":9}',
  scene_prefs      JSON COMMENT '对话中提取的场景偏好 {"date":1}',
  watch_prefs      JSON COMMENT '年代/语言等观影偏好（对话提取）',
  profile_summary  VARCHAR(500) COMMENT '画像摘要（注入 system prompt）',
  updated_at       DATETIME COMMENT '最近重算时间',
  INDEX idx_profile_updated (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS agent_preference_event (
  id         BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id    BIGINT NOT NULL COMMENT '关联 user.id',
  source     TINYINT COMMENT '1=收藏 2=影评 3=对话',
  item_type  VARCHAR(20) COMMENT 'genre|actor|director|region|rating|scene|watch',
  item_value VARCHAR(100),
  weight     INT DEFAULT 1,
  created_at DATETIME,
  KEY idx_event_user_time (user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
