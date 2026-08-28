-- PROJECT2 MySQL 테이블 생성문
-- 생성 순서: manager -> top_area -> area -> Gold Feature
-- 이 파일 하나로 전체 테이블과 대시보드 View를 생성한다.
-- run_id가 없는 기존 테이블을 자동으로 변경하는 증분 migration 파일은 제공하지 않는다.

CREATE TABLE IF NOT EXISTS manager (
    manager_id VARCHAR(9) NOT NULL,
    run_id VARCHAR(100) NOT NULL,
    manager_name VARCHAR(100) NOT NULL,
    manager_department_name VARCHAR(100) NOT NULL,
    manager_position_name VARCHAR(10) NOT NULL,
    manager_hire_datetime DATETIME NOT NULL,
    manager_active_yn CHAR(1) NOT NULL,

    PRIMARY KEY (manager_id),
    INDEX idx_manager_run_id (run_id),
    CONSTRAINT chk_manager_active_yn
        CHECK (manager_active_yn IN ('Y', 'N'))
-- InnoDB: 외래키와 트랜잭션을 사용할 수 있는 MySQL 저장 엔진
-- utf8mb4: 한글 등 다양한 문자를 저장하기 위한 문자 집합
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS top_area (
    top_business_area_id VARCHAR(9) NOT NULL,
    run_id VARCHAR(100) NOT NULL,
    top_business_area_name VARCHAR(100) NOT NULL,
    top_business_area_level_code VARCHAR(3) NOT NULL,
    top_business_area_registration_datetime DATETIME NOT NULL,

    PRIMARY KEY (top_business_area_id),
    INDEX idx_top_area_run_id (run_id),
    CONSTRAINT chk_top_area_level_code
        CHECK (top_business_area_level_code = 'TOP')
-- InnoDB: 외래키와 트랜잭션을 사용할 수 있는 MySQL 저장 엔진
-- utf8mb4: 한글 등 다양한 문자를 저장하기 위한 문자 집합
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


CREATE TABLE IF NOT EXISTS area (
    business_area_id VARCHAR(9) NOT NULL,
    run_id VARCHAR(100) NOT NULL,
    business_area_name VARCHAR(100) NOT NULL,
    manager_id VARCHAR(9) NOT NULL,
    parent_business_area_id VARCHAR(9) NULL,
    top_business_area_id VARCHAR(9) NOT NULL,
    business_area_registration_datetime DATETIME NOT NULL,

    PRIMARY KEY (business_area_id),

    CONSTRAINT fk_area_manager
        FOREIGN KEY (manager_id)
        REFERENCES manager (manager_id),

    CONSTRAINT fk_area_parent
        FOREIGN KEY (parent_business_area_id)
        REFERENCES top_area (top_business_area_id),

    CONSTRAINT fk_area_top
        FOREIGN KEY (top_business_area_id)
        REFERENCES top_area (top_business_area_id),

    INDEX idx_area_manager_id (manager_id),
    INDEX idx_area_parent_id (parent_business_area_id),
    INDEX idx_area_top_id (top_business_area_id),
    INDEX idx_area_run_id (run_id)
-- InnoDB: 위의 FK 제약조건과 트랜잭션을 지원한다.
-- utf8mb4: 한글 등 다양한 문자를 저장한다.
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- 특정 run_id 시점의 Manager 한 명을 한 행으로 요약한 AI 분석용 Gold다.
-- Silver 원장은 그대로 보존하고, 담당 Area·Top·Parent 수와 기간 Feature만 저장한다.
CREATE TABLE IF NOT EXISTS gold_manager_assignment_features (
    run_id VARCHAR(100) NOT NULL,
    as_of_datetime DATETIME NOT NULL,
    manager_id VARCHAR(9) NOT NULL,
    manager_department_name VARCHAR(100) NOT NULL,
    manager_position_name VARCHAR(10) NOT NULL,
    manager_active_flag TINYINT UNSIGNED NOT NULL,
    manager_tenure_days INT UNSIGNED NOT NULL,
    managed_area_count INT UNSIGNED NOT NULL,
    managed_top_area_count INT UNSIGNED NOT NULL,
    managed_parent_area_count INT UNSIGNED NOT NULL,
    top_level_area_count INT UNSIGNED NOT NULL,
    average_area_age_days DECIMAL(10, 2) NOT NULL,
    max_area_age_days INT UNSIGNED NOT NULL,
    cross_top_area_flag TINYINT UNSIGNED NOT NULL,
    feature_version VARCHAR(20) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (run_id, manager_id),
    INDEX idx_gold_manager_id (manager_id),
    INDEX idx_gold_as_of_datetime (as_of_datetime),
    INDEX idx_gold_cross_top_flag (cross_top_area_flag),

    CONSTRAINT chk_gold_manager_active_flag
        CHECK (manager_active_flag IN (0, 1)),
    CONSTRAINT chk_gold_cross_top_flag
        CHECK (cross_top_area_flag IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- 파이프라인 1회 실행(run_id)마다 대시보드가 사용할 사실값을 보관한다.
-- 적재율 등 KPI는 이 값들을 조회한 Django service 계층에서 계산한다.
CREATE TABLE IF NOT EXISTS pipeline_run_summary (
    run_id VARCHAR(100) NOT NULL,
    raw_row_count INT UNSIGNED NOT NULL DEFAULT 0,
    standardization_accepted_count INT UNSIGNED NOT NULL DEFAULT 0,
    standardization_rejected_count INT UNSIGNED NOT NULL DEFAULT 0,
    final_accepted_count INT UNSIGNED NOT NULL DEFAULT 0,
    final_rejected_count INT UNSIGNED NOT NULL DEFAULT 0,
    manager_target_count INT UNSIGNED NOT NULL DEFAULT 0,
    manager_loaded_count INT UNSIGNED NOT NULL DEFAULT 0,
    top_area_target_count INT UNSIGNED NOT NULL DEFAULT 0,
    top_area_loaded_count INT UNSIGNED NOT NULL DEFAULT 0,
    area_target_count INT UNSIGNED NOT NULL DEFAULT 0,
    area_loaded_count INT UNSIGNED NOT NULL DEFAULT 0,
    started_at DATETIME(6) NOT NULL,
    completed_at DATETIME(6) NULL,
    batch_status ENUM('RUNNING', 'SUCCESS', 'PARTIAL_FAILURE', 'FAILED') NOT NULL,
    error_message TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id),
    INDEX idx_pipeline_run_status_started (batch_status, started_at),
    INDEX idx_pipeline_run_completed_at (completed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- 대시보드에는 run_id를 숨기고 업무 컬럼만 제공한다.
CREATE OR REPLACE VIEW dashboard_area_view AS
SELECT
    a.business_area_id,
    a.business_area_name,
    a.manager_id,
    m.manager_name,
    m.manager_department_name,
    m.manager_position_name,
    m.manager_hire_datetime,
    m.manager_active_yn,
    a.parent_business_area_id,
    p.top_business_area_name AS parent_business_area_name,
    a.top_business_area_id,
    t.top_business_area_name,
    t.top_business_area_level_code,
    a.business_area_registration_datetime,
    t.top_business_area_registration_datetime
FROM area AS a
JOIN manager AS m
  ON a.manager_id = m.manager_id
LEFT JOIN top_area AS p
  ON a.parent_business_area_id = p.top_business_area_id
JOIN top_area AS t
  ON a.top_business_area_id = t.top_business_area_id;


-- 외부 대시보드 repository가 배치별 사실값을 직접 읽는 전용 뷰이다.
CREATE OR REPLACE VIEW dashboard_pipeline_run_view AS
SELECT
    run_id,
    raw_row_count,
    standardization_accepted_count,
    standardization_rejected_count,
    final_accepted_count,
    final_rejected_count,
    manager_target_count,
    manager_loaded_count,
    top_area_target_count,
    top_area_loaded_count,
    area_target_count,
    area_loaded_count,
    started_at,
    completed_at,
    batch_status,
    error_message,
    created_at,
    updated_at
FROM pipeline_run_summary;


-- 최신 SUCCESS run의 Gold Feature만 노출하고 내부 계보키 run_id는 숨긴다.
CREATE OR REPLACE VIEW dashboard_gold_manager_assignment_view AS
SELECT
    g.manager_id,
    g.manager_department_name,
    g.manager_position_name,
    g.manager_active_flag,
    g.manager_tenure_days,
    g.managed_area_count,
    g.managed_top_area_count,
    g.managed_parent_area_count,
    g.top_level_area_count,
    g.average_area_age_days,
    g.max_area_age_days,
    g.cross_top_area_flag
FROM gold_manager_assignment_features AS g
JOIN pipeline_run_summary AS current_run
  ON g.run_id = current_run.run_id
LEFT JOIN pipeline_run_summary AS newer_run
  ON newer_run.batch_status = 'SUCCESS'
 AND (
        newer_run.completed_at > current_run.completed_at
        OR (
            newer_run.completed_at = current_run.completed_at
            AND newer_run.run_id > current_run.run_id
        )
    )
WHERE current_run.batch_status = 'SUCCESS'
  AND newer_run.run_id IS NULL;
