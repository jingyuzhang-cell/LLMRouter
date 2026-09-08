-- R3 Multi-objective Router Dataset v1.1 - MySQL mirror DDL
-- Canonical source of truth is the JSONL files; sync is one-way JSONL -> MySQL (storage.py).
-- Engine InnoDB, utf8mb4 for full unicode prompts/answers.

CREATE TABLE IF NOT EXISTS r3_queries (
  query_id       VARCHAR(64)  NOT NULL,
  dataset        VARCHAR(32)  NOT NULL COMMENT 'gsm8k|mbpp|humaneval|mmlupro|arenahard',
  task_type      VARCHAR(16)  NOT NULL COMMENT 'math|code|knowledge|general',
  difficulty     VARCHAR(8)   NOT NULL COMMENT 'easy|medium|hard (derived, frozen)',
  query_text     MEDIUMTEXT   NOT NULL,
  ground_truth   MEDIUMTEXT   NULL,
  split          ENUM('train','test') NOT NULL,
  record_sha256  CHAR(64)     NOT NULL COMMENT 'sha256 of the canonical JSONL line',
  created_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (query_id),
  KEY idx_dataset_split (dataset, split),
  KEY idx_task_difficulty (task_type, difficulty)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS r3_responses (
  query_id       VARCHAR(64)  NOT NULL,
  model          VARCHAR(64)  NOT NULL COMMENT 'one of the 4 frozen pool slots',
  slot           ENUM('small','medium','large','reasoning') NOT NULL,
  answer         LONGTEXT     NULL,
  thinking       LONGTEXT     NULL,
  auto_score     FLOAT        NULL,
  auto_correct   TINYINT(1)   NULL,
  judge_score    FLOAT        NULL,
  judge          VARCHAR(32)  NULL,
  quality_final  FLOAT        NULL,
  quality_source VARCHAR(16)  NULL,
  tokens_input   INT UNSIGNED NULL,
  tokens_output  INT UNSIGNED NULL,
  tokens_estimated TINYINT(1) NOT NULL DEFAULT 0,
  price_in_pm    FLOAT        NULL,
  price_out_pm   FLOAT        NULL,
  cost_usd       DOUBLE       NULL,
  latency_total_ms DOUBLE     NULL,
  latency_ttft_ms  DOUBLE     NULL,
  latency_decode_ms DOUBLE    NULL,
  tokens_per_second DOUBLE    NULL,
  latency_source VARCHAR(24)  NULL COMMENT 'local_4090_vllm|dashscope_api|phase2_local_vllm',
  utility_json   JSON         NULL COMMENT '24 frozen (lam,mu) utility scores',
  status         ENUM('ok','failed','truncated','parse_failed') NOT NULL,
  PRIMARY KEY (query_id, model),
  KEY idx_model_status (model, status),
  KEY idx_quality (quality_final),
  CONSTRAINT fk_resp_query FOREIGN KEY (query_id) REFERENCES r3_queries(query_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS r3_collections (
  batch_id       VARCHAR(64)  NOT NULL COMMENT 'phase1 | phase2_latency | recompute_cost etc.',
  manifest_sha256 CHAR(64)    NOT NULL,
  n_queries      INT UNSIGNED NOT NULL,
  ok_rate        FLOAT        NOT NULL,
  price_table_sha256 CHAR(64) NOT NULL,
  protocol_id    VARCHAR(64)  NOT NULL COMMENT 'R3_COLLECTION_PROTOCOL_v1.x',
  notes          TEXT         NULL,
  created_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (batch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
