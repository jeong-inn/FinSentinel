-- FinSentinel PostgreSQL Schema v2
-- 금융 이상거래탐지시스템(FDS) 파이프라인 결과 저장
-- 금융보안원 FDS 운영 가이드라인 참조

-- ============================================================
-- 1. 원본 거래 로그 + 분석 결과 (row-level)
-- ============================================================
CREATE TABLE IF NOT EXISTS transaction_events (
    id                  SERIAL PRIMARY KEY,
    timestamp           INTEGER NOT NULL,
    tx_datetime         TIMESTAMP,
    tx_hour             SMALLINT,
    branch_id           VARCHAR(30) NOT NULL,
    account_id          VARCHAR(10) NOT NULL,
    channel_id          VARCHAR(5) NOT NULL,
    scenario_id         VARCHAR(10) NOT NULL,
    -- 거래 정보
    tx_type             VARCHAR(15),
    customer_risk_level SMALLINT DEFAULT 2,
    counterparty_id     VARCHAR(20),
    -- 거래 파라미터
    tx_amount           NUMERIC(12,4) NOT NULL,
    response_time_ms    NUMERIC(10,4) NOT NULL,
    processing_time_ms  NUMERIC(10,4) NOT NULL,
    error_code          INTEGER DEFAULT 0,
    fraud_flag          INTEGER DEFAULT 0,
    -- rolling features
    tx_amount_roll_mean     NUMERIC(12,4),
    tx_amount_roll_std      NUMERIC(12,4),
    tx_amount_diff          NUMERIC(12,4),
    processing_time_diff    NUMERIC(10,4),
    -- FDS 탐지 결과
    anomaly_flag    INTEGER DEFAULT 0,
    anomaly_reason  TEXT DEFAULT 'normal',
    -- 상태 분류
    state           VARCHAR(15) DEFAULT 'NORMAL',
    -- 감사 컬럼
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_events_scenario ON transaction_events(scenario_id);
CREATE INDEX IF NOT EXISTS idx_events_account ON transaction_events(account_id);
CREATE INDEX IF NOT EXISTS idx_events_state ON transaction_events(state);
CREATE INDEX IF NOT EXISTS idx_events_anomaly ON transaction_events(anomaly_flag);
CREATE INDEX IF NOT EXISTS idx_events_datetime ON transaction_events(tx_datetime);
CREATE INDEX IF NOT EXISTS idx_events_risk ON transaction_events(customer_risk_level);

-- ============================================================
-- 2. 시나리오별 판정 결과
-- ============================================================
CREATE TABLE IF NOT EXISTS scenario_judgements (
    scenario_id         VARCHAR(10) PRIMARY KEY,
    total_count         INTEGER,
    fail_count          INTEGER,
    critical_count      INTEGER,
    warning_count       INTEGER,
    fail_ratio          NUMERIC(6,3),
    critical_ratio      NUMERIC(6,3),
    warning_ratio       NUMERIC(6,3),
    final_result        VARCHAR(20),
    final_reason        TEXT,
    recommended_action  VARCHAR(30),
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 3. 검증 결과 (expected vs actual)
-- ============================================================
CREATE TABLE IF NOT EXISTS validation_results (
    scenario_id             VARCHAR(10) PRIMARY KEY,
    description             TEXT,
    expected_final_result   VARCHAR(20),
    actual_final_result     VARCHAR(20),
    expected_action         VARCHAR(30),
    actual_action           VARCHAR(30),
    action_gap              INTEGER,
    result_match            BOOLEAN,
    action_match            BOOLEAN,
    keyword_match           BOOLEAN,
    ratio_match             BOOLEAN,
    validation_score        INTEGER,
    overall_match           BOOLEAN,
    release_gate            VARCHAR(20),
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 4. 서비스 품질 분석 (SPC/SQM) 결과
-- ============================================================
CREATE TABLE IF NOT EXISTS spc_analysis (
    id              SERIAL PRIMARY KEY,
    scenario_id     VARCHAR(10) NOT NULL,
    param           VARCHAR(30) NOT NULL,
    cpk             NUMERIC(10,4),
    ppk             NUMERIC(10,4),
    mean            NUMERIC(12,4),
    sigma           NUMERIC(12,4),
    ucl             NUMERIC(12,4),
    lcl             NUMERIC(12,4),
    rule1_count     INTEGER DEFAULT 0,
    ooc_count       INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(scenario_id, param)
);

-- ============================================================
-- 5. 원인 분석 결과
-- ============================================================
CREATE TABLE IF NOT EXISTS root_cause_analysis (
    scenario_id      VARCHAR(10) PRIMARY KEY,
    primary_cause    TEXT,
    secondary_signal TEXT,
    confidence       VARCHAR(10),
    evidence         TEXT,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 6. 야간배치 — 일일결산
-- ============================================================
CREATE TABLE IF NOT EXISTS batch_settlement (
    id                  SERIAL PRIMARY KEY,
    scenario_id         VARCHAR(10) NOT NULL,
    account_id          VARCHAR(10) NOT NULL,
    settlement_date     DATE,
    total_tx_count      INTEGER,
    deposit_count       INTEGER DEFAULT 0,
    deposit_amount      NUMERIC(14,2) DEFAULT 0,
    withdrawal_count    INTEGER DEFAULT 0,
    withdrawal_amount   NUMERIC(14,2) DEFAULT 0,
    transfer_count      INTEGER DEFAULT 0,
    transfer_amount     NUMERIC(14,2) DEFAULT 0,
    payment_count       INTEGER DEFAULT 0,
    payment_amount      NUMERIC(14,2) DEFAULT 0,
    total_amount        NUMERIC(14,2),
    net_amount          NUMERIC(14,2),
    avg_amount          NUMERIC(12,2),
    max_amount          NUMERIC(12,4),
    min_amount          NUMERIC(12,4),
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(scenario_id, account_id)
);

-- ============================================================
-- 7. 야간배치 — STR 후보
-- ============================================================
CREATE TABLE IF NOT EXISTS batch_str_candidates (
    id                      SERIAL PRIMARY KEY,
    scenario_id             VARCHAR(10) NOT NULL,
    anomaly_count           INTEGER,
    unique_rule_violations  INTEGER,
    affected_accounts       INTEGER,
    final_result            VARCHAR(20),
    recommended_action      VARCHAR(30),
    priority_score          INTEGER,
    priority                VARCHAR(10),
    str_status              VARCHAR(20) DEFAULT 'PENDING_REVIEW',
    reporting_deadline      VARCHAR(20),
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- 8. 데이터 품질 평가 (DQM)
-- ============================================================
CREATE TABLE IF NOT EXISTS dq_assessment (
    id          SERIAL PRIMARY KEY,
    dimension   VARCHAR(20) NOT NULL,
    score       NUMERIC(6,2),
    grade       VARCHAR(1),
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- SQL 분석 뷰
-- ============================================================

-- 시나리오별 이상 거래 비율 집계
CREATE OR REPLACE VIEW v_anomaly_ratio_by_scenario AS
SELECT
    scenario_id,
    COUNT(*) AS total_count,
    COUNT(*) FILTER (WHERE anomaly_flag = 1) AS anomaly_count,
    ROUND(AVG(anomaly_flag)::numeric, 4) AS anomaly_ratio
FROM transaction_events
GROUP BY scenario_id
ORDER BY anomaly_ratio DESC;

-- 계좌별 이상 거래 집중도
CREATE OR REPLACE VIEW v_anomaly_by_account AS
SELECT
    scenario_id,
    account_id,
    COUNT(*) AS total_tx,
    COUNT(*) FILTER (WHERE anomaly_flag = 1) AS anomaly_tx,
    ROUND(AVG(anomaly_flag)::numeric, 4) AS anomaly_ratio,
    ROUND(AVG(tx_amount)::numeric, 2) AS avg_tx_amount,
    MAX(tx_amount) AS max_tx_amount
FROM transaction_events
GROUP BY scenario_id, account_id
ORDER BY scenario_id, anomaly_ratio DESC;

-- 채널별 장애 분포
CREATE OR REPLACE VIEW v_channel_health AS
SELECT
    scenario_id,
    channel_id,
    COUNT(*) FILTER (WHERE anomaly_reason LIKE '%response_dropout%') AS dropout_count,
    COUNT(*) FILTER (WHERE anomaly_reason LIKE '%tx_error_detected%') AS error_count,
    COUNT(*) FILTER (WHERE anomaly_reason LIKE '%fraud_event%') AS fraud_count,
    ROUND(AVG(response_time_ms)::numeric, 2) AS avg_response_time,
    ROUND(AVG(processing_time_ms)::numeric, 2) AS avg_processing_time
FROM transaction_events
GROUP BY scenario_id, channel_id
ORDER BY scenario_id, channel_id;

-- WARNING 이상 상태가 3건 연속된 구간 탐지 (window function)
CREATE OR REPLACE VIEW v_consecutive_warning_streaks AS
SELECT scenario_id, account_id, state, streak_length, streak_start
FROM (
    SELECT
        scenario_id,
        account_id,
        state,
        COUNT(*) OVER (PARTITION BY scenario_id, grp) AS streak_length,
        MIN(timestamp) OVER (PARTITION BY scenario_id, grp) AS streak_start,
        ROW_NUMBER() OVER (PARTITION BY scenario_id, grp ORDER BY timestamp) AS rn
    FROM (
        SELECT *,
            SUM(CASE WHEN state != LAG(state) OVER (PARTITION BY scenario_id ORDER BY timestamp)
                     THEN 1 ELSE 0 END)
            OVER (PARTITION BY scenario_id ORDER BY timestamp) AS grp
        FROM transaction_events
    ) grouped
    WHERE state IN ('WARNING', 'CRITICAL', 'FAIL')
) streaks
WHERE rn = 1 AND streak_length >= 3
ORDER BY scenario_id, streak_start;

-- 서비스 품질 능력 요약 (Cpk < 1.33 = SLA 미달)
CREATE OR REPLACE VIEW v_spc_risk_summary AS
SELECT
    scenario_id,
    param,
    cpk,
    ppk,
    rule1_count,
    ooc_count,
    CASE
        WHEN cpk >= 1.33 THEN 'CAPABLE'
        WHEN cpk >= 1.00 THEN 'MARGINAL'
        ELSE 'INCAPABLE'
    END AS capability_status
FROM spc_analysis
ORDER BY cpk ASC;

-- 릴리즈 게이트 현황 대시보드
CREATE OR REPLACE VIEW v_release_gate_dashboard AS
SELECT
    v.scenario_id,
    v.actual_final_result AS result,
    v.validation_score,
    v.release_gate,
    v.overall_match,
    j.recommended_action,
    j.warning_ratio,
    j.critical_ratio
FROM validation_results v
JOIN scenario_judgements j ON v.scenario_id = j.scenario_id
ORDER BY
    CASE v.release_gate
        WHEN 'BLOCKED' THEN 1
        WHEN 'REVIEW_REQUIRED' THEN 2
        WHEN 'MONITORING_REQUIRED' THEN 3
        WHEN 'READY' THEN 4
    END;

-- 거래 유형별 이상 거래 분포 (FDS 규칙 효과 분석)
CREATE OR REPLACE VIEW v_anomaly_by_tx_type AS
SELECT
    scenario_id,
    tx_type,
    COUNT(*) AS total_tx,
    COUNT(*) FILTER (WHERE anomaly_flag = 1) AS anomaly_tx,
    ROUND(AVG(tx_amount)::numeric, 2) AS avg_amount,
    ROUND(AVG(CASE WHEN anomaly_flag = 1 THEN tx_amount END)::numeric, 2) AS avg_anomaly_amount
FROM transaction_events
WHERE tx_type IS NOT NULL
GROUP BY scenario_id, tx_type
ORDER BY scenario_id, tx_type;

-- 고위험 고객 거래 모니터링 (CDD 등급 4~5)
CREATE OR REPLACE VIEW v_high_risk_customer_activity AS
SELECT
    scenario_id,
    account_id,
    customer_risk_level,
    COUNT(*) AS tx_count,
    ROUND(AVG(tx_amount)::numeric, 2) AS avg_amount,
    MAX(tx_amount) AS max_amount,
    COUNT(*) FILTER (WHERE anomaly_flag = 1) AS anomaly_count
FROM transaction_events
WHERE customer_risk_level >= 4
GROUP BY scenario_id, account_id, customer_risk_level
ORDER BY customer_risk_level DESC, anomaly_count DESC;

-- STR 후보 현황 (야간배치 결과)
CREATE OR REPLACE VIEW v_str_pipeline_status AS
SELECT
    s.scenario_id,
    s.priority,
    s.priority_score,
    s.anomaly_count,
    s.str_status,
    s.reporting_deadline,
    j.final_result,
    j.recommended_action
FROM batch_str_candidates s
JOIN scenario_judgements j ON s.scenario_id = j.scenario_id
ORDER BY s.priority_score DESC;
