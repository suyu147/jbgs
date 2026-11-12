
/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

CREATE DATABASE /*!32312 IF NOT EXISTS*/ `career_insight` /*!40100 DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci */ /*!80016 DEFAULT ENCRYPTION='N' */;

USE `career_insight`;
DROP TABLE IF EXISTS `agent_messages`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `agent_messages` (
  `id` varchar(64) NOT NULL,
  `session_id` varchar(64) NOT NULL,
  `role` varchar(16) NOT NULL,
  `content` text NOT NULL,
  `evidence` json NOT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_agent_messages_session_id` (`session_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `agent_sessions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `agent_sessions` (
  `id` varchar(64) NOT NULL,
  `title` varchar(255) NOT NULL,
  `context` json NOT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `alembic_version`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `alembic_version` (
  `version_num` varchar(32) NOT NULL,
  PRIMARY KEY (`version_num`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `app_users`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `app_users` (
  `id` varchar(64) NOT NULL,
  `username` varchar(80) NOT NULL,
  `password_hash` varchar(255) NOT NULL,
  `display_name` varchar(120) NOT NULL,
  `role` varchar(24) NOT NULL,
  `is_active` tinyint(1) NOT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `ix_app_users_username` (`username`),
  KEY `ix_app_users_role` (`role`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `audit_logs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `audit_logs` (
  `id` varchar(64) NOT NULL,
  `action` varchar(80) NOT NULL,
  `target_type` varchar(80) NOT NULL,
  `target_id` varchar(80) NOT NULL,
  `detail` json NOT NULL,
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `dataset_registry`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `dataset_registry` (
  `id` varchar(64) NOT NULL,
  `name` varchar(255) NOT NULL,
  `category` varchar(80) NOT NULL,
  `path` text NOT NULL,
  `record_count` bigint NOT NULL,
  `version` varchar(80) NOT NULL,
  `usage_boundary` varchar(80) NOT NULL,
  `sha256` varchar(64) NOT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `dataset_revisions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `dataset_revisions` (
  `id` varchar(64) NOT NULL,
  `dataset_id` varchar(64) NOT NULL,
  `file_name` varchar(255) NOT NULL,
  `file_path` text NOT NULL,
  `record_count` bigint NOT NULL,
  `version` varchar(80) NOT NULL,
  `sha256` varchar(64) NOT NULL,
  `sync_status` varchar(24) NOT NULL,
  `sync_result` json NOT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_dataset_revisions_dataset_id` (`dataset_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `evaluation_runs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `evaluation_runs` (
  `id` varchar(64) NOT NULL,
  `suite` varchar(80) NOT NULL,
  `metrics` json NOT NULL,
  `passed` tinyint(1) NOT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `favorite_jobs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `favorite_jobs` (
  `id` varchar(64) NOT NULL,
  `user_id` varchar(64) NOT NULL,
  `role_id` varchar(80) NOT NULL,
  `role_name` varchar(255) NOT NULL,
  `role_field` varchar(255) NOT NULL DEFAULT '',
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_favorite_jobs_user_role` (`user_id`,`role_id`),
  KEY `ix_favorite_jobs_user_id` (`user_id`),
  KEY `ix_favorite_jobs_role_id` (`role_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `learning_paths`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `learning_paths` (
  `id` varchar(64) NOT NULL,
  `match_report_id` varchar(64) NOT NULL,
  `stages` json NOT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_learning_paths_match_report_id` (`match_report_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `match_reports`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `match_reports` (
  `id` varchar(64) NOT NULL,
  `resume_id` varchar(64) NOT NULL,
  `role_id` varchar(80) NOT NULL,
  `role_name` varchar(255) NOT NULL,
  `score` float NOT NULL,
  `result` json NOT NULL,
  `algorithm_version` varchar(40) NOT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_match_reports_role_id` (`role_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `processing_tasks`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `processing_tasks` (
  `id` varchar(64) NOT NULL,
  `task_type` varchar(40) NOT NULL,
  `status` varchar(24) NOT NULL,
  `progress` int NOT NULL,
  `result` json NOT NULL,
  `error` text NOT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `resume_profiles`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `resume_profiles` (
  `id` varchar(64) NOT NULL,
  `user_id` varchar(64) NOT NULL DEFAULT '',
  `file_name` varchar(255) NOT NULL,
  `file_path` text NOT NULL,
  `education` varchar(80) NOT NULL,
  `experience_years` float DEFAULT NULL,
  `certificates` json NOT NULL,
  `raw_text` text NOT NULL,
  `confirmed` tinyint(1) NOT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_resume_profiles_user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `talent_assessment_candidates`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `talent_assessment_candidates` (
  `id` varchar(64) NOT NULL,
  `batch_id` varchar(64) NOT NULL,
  `candidate_code` varchar(32) NOT NULL,
  `file_name` varchar(255) NOT NULL DEFAULT '',
  `file_size` bigint NOT NULL DEFAULT '0',
  `resume_id` varchar(64) NOT NULL DEFAULT '',
  `match_report_id` varchar(64) NOT NULL DEFAULT '',
  `status` varchar(24) NOT NULL DEFAULT 'completed',
  `score` float DEFAULT NULL,
  `result` json NOT NULL,
  `error` text NOT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_talent_assessment_candidates_batch_id` (`batch_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `talent_assessment_batches`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `talent_assessment_batches` (
  `id` varchar(64) NOT NULL,
  `user_id` varchar(64) NOT NULL,
  `role_id` varchar(80) NOT NULL,
  `role_name` varchar(255) NOT NULL DEFAULT '',
  `settings` json NOT NULL,
  `status` varchar(24) NOT NULL DEFAULT 'running',
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_talent_assessment_batches_user_id` (`user_id`),
  KEY `ix_talent_assessment_batches_role_id` (`role_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `user_workspace_profiles`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `user_workspace_profiles` (
  `user_id` varchar(64) NOT NULL,
  `audience` varchar(24) NOT NULL DEFAULT 'seeker',
  `profile` json NOT NULL,
  `hr_evaluation_settings` json NOT NULL,
  `work_style_assessment` json NOT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `resume_skills`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `resume_skills` (
  `id` varchar(64) NOT NULL,
  `resume_id` varchar(64) NOT NULL,
  `skill_id` varchar(80) NOT NULL,
  `skill_name` varchar(160) NOT NULL,
  `evidence` text NOT NULL,
  `confidence` float NOT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_resume_skills_resume_id` (`resume_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
CREATE TABLE IF NOT EXISTS `pipeline_batches` (
  `id` varchar(64) NOT NULL,
  `source_type` varchar(32) NOT NULL,
  `source_name` varchar(255) NOT NULL DEFAULT '',
  `dataset_name` varchar(255) NOT NULL DEFAULT '',
  `status` varchar(24) NOT NULL DEFAULT 'received',
  `stage` varchar(40) NOT NULL DEFAULT 'ingest',
  `retry_count` int NOT NULL DEFAULT 0,
  `statistics` json NOT NULL,
  `metadata_json` json NOT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_pipeline_batches_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS `pipeline_stage_logs` (
  `id` varchar(64) NOT NULL,
  `batch_id` varchar(64) NOT NULL,
  `stage` varchar(40) NOT NULL,
  `status` varchar(24) NOT NULL,
  `statistics` json NOT NULL,
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_pipeline_stage_logs_batch_id` (`batch_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS `raw_records` (
  `id` varchar(64) NOT NULL,
  `batch_id` varchar(64) NOT NULL,
  `source_record_id` varchar(255) NOT NULL DEFAULT '',
  `node_type` varchar(64) NOT NULL DEFAULT '',
  `source_canonical` varchar(255) NOT NULL DEFAULT '',
  `company_name` varchar(255) NOT NULL DEFAULT '',
  `title` varchar(500) NOT NULL DEFAULT '',
  `content` text NOT NULL,
  `raw_payload` json NOT NULL,
  `source_locator` json NOT NULL,
  `metadata_json` json NOT NULL,
  `content_sha256` varchar(64) NOT NULL,
  `observation_count` int NOT NULL DEFAULT 1,
  `duplicate_count` int NOT NULL DEFAULT 0,
  `duplicate_of` varchar(64) NOT NULL DEFAULT '',
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_raw_records_batch_id` (`batch_id`),
  KEY `ix_raw_records_source_record_id` (`source_record_id`),
  KEY `ix_raw_records_content_sha256` (`content_sha256`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS `extracted_records` (
  `id` varchar(64) NOT NULL,
  `batch_id` varchar(64) NOT NULL,
  `raw_record_id` varchar(64) NOT NULL,
  `parser_name` varchar(80) NOT NULL DEFAULT '',
  `parser_version` varchar(40) NOT NULL DEFAULT '',
  `data` json NOT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`), UNIQUE KEY `uq_extracted_batch_raw` (`batch_id`,`raw_record_id`),
  KEY `ix_extracted_records_batch_id` (`batch_id`), KEY `ix_extracted_records_raw_record_id` (`raw_record_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS `normalized_records` (
  `id` varchar(64) NOT NULL,
  `batch_id` varchar(64) NOT NULL,
  `raw_record_id` varchar(64) NOT NULL,
  `data` json NOT NULL,
  `linker_version` varchar(40) NOT NULL DEFAULT '',
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`), UNIQUE KEY `uq_normalized_batch_raw` (`batch_id`,`raw_record_id`),
  KEY `ix_normalized_records_batch_id` (`batch_id`), KEY `ix_normalized_records_raw_record_id` (`raw_record_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS `entity_links` (
  `id` varchar(64) NOT NULL,
  `batch_id` varchar(64) NOT NULL,
  `raw_record_id` varchar(64) NOT NULL,
  `entity_type` varchar(40) NOT NULL,
  `surface_form` varchar(500) NOT NULL,
  `normalized_surface_form` varchar(500) NOT NULL,
  `entity_id` varchar(255) DEFAULT NULL,
  `confidence` double NOT NULL DEFAULT 0,
  `status` varchar(24) NOT NULL,
  `candidates` json NOT NULL,
  `entity_origin` varchar(24) NOT NULL DEFAULT 'asset',
  `linker_version` varchar(40) NOT NULL DEFAULT '',
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`), UNIQUE KEY `uq_entity_links_batch_raw_type_surface` (`batch_id`,`raw_record_id`,`entity_type`,`normalized_surface_form`),
  KEY `ix_entity_links_batch_id` (`batch_id`), KEY `ix_entity_links_raw_record_id` (`raw_record_id`),
  KEY `ix_entity_links_entity_type` (`entity_type`), KEY `ix_entity_links_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS `feature_snapshots` (
  `id` varchar(64) NOT NULL,
  `period_key` varchar(32) NOT NULL,
  `granularity` varchar(16) NOT NULL DEFAULT 'month',
  `cohort_key` varchar(255) NOT NULL,
  `cohort_basis` varchar(16) NOT NULL DEFAULT 'title',
  `metrics` json NOT NULL,
  `evidence_ids` json NOT NULL,
  `input_summary` json NOT NULL,
  `feature_version` varchar(40) NOT NULL DEFAULT 'feature-v1',
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`), UNIQUE KEY `uq_feature_snapshots_period_cohort` (`period_key`,`granularity`,`cohort_key`),
  KEY `ix_feature_snapshots_period_key` (`period_key`), KEY `ix_feature_snapshots_cohort_key` (`cohort_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS `signals` (
  `id` varchar(64) NOT NULL,
  `signal_type` varchar(40) NOT NULL,
  `cohort_key` varchar(255) NOT NULL,
  `period_key` varchar(32) NOT NULL,
  `granularity` varchar(16) NOT NULL DEFAULT 'month',
  `severity` varchar(16) NOT NULL DEFAULT 'medium',
  `status` varchar(16) NOT NULL DEFAULT 'active',
  `metrics` json NOT NULL,
  `evidence_ids` json NOT NULL,
  `suppression_key` varchar(255) NOT NULL DEFAULT '',
  `signal_version` varchar(40) NOT NULL DEFAULT 'signal-v1',
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`), UNIQUE KEY `uq_signals_type_cohort_period` (`signal_type`,`cohort_key`,`period_key`,`granularity`),
  KEY `ix_signals_signal_type` (`signal_type`), KEY `ix_signals_cohort_key` (`cohort_key`), KEY `ix_signals_period_key` (`period_key`), KEY `ix_signals_status` (`status`), KEY `ix_signals_suppression_key` (`suppression_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
DROP TABLE IF EXISTS `review_actions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `review_actions` (
  `id` varchar(64) NOT NULL,
  `draft_id` varchar(64) NOT NULL,
  `action` varchar(24) NOT NULL,
  `note` text NOT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_review_actions_draft_id` (`draft_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `role_definition_drafts`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `role_definition_drafts` (
  `id` varchar(64) NOT NULL,
  `role_id` varchar(80) NOT NULL,
  `role_name` varchar(255) NOT NULL,
  `candidate_type` varchar(40) NOT NULL,
  `status` varchar(24) NOT NULL,
  `definition` json NOT NULL,
  `evidence` json NOT NULL,
  `origin` varchar(24) NOT NULL DEFAULT 'legacy',
  `batch_id` varchar(64) NOT NULL DEFAULT '',
  `evidence_grade` varchar(32) NOT NULL DEFAULT 'legacy',
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_role_definition_drafts_origin` (`origin`),
  KEY `ix_role_definition_drafts_batch_id` (`batch_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
CREATE TABLE IF NOT EXISTS `review_comments` (
  `id` varchar(64) NOT NULL,
  `draft_id` varchar(64) NOT NULL,
  `action` varchar(24) NOT NULL DEFAULT '',
  `comment` text NOT NULL,
  `author_id` varchar(64) NOT NULL DEFAULT '',
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_review_comments_draft_id` (`draft_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS `role_definition_versions` (
  `id` varchar(64) NOT NULL,
  `version_id` varchar(64) NOT NULL,
  `draft_id` varchar(64) NOT NULL,
  `role_id` varchar(80) NOT NULL DEFAULT '',
  `role_name` varchar(255) NOT NULL DEFAULT '',
  `candidate_type` varchar(40) NOT NULL DEFAULT 'new_role',
  `status` varchar(24) NOT NULL DEFAULT 'approved',
  `definition` json NOT NULL,
  `evidence` json NOT NULL,
  `origin` varchar(24) NOT NULL DEFAULT 'legacy',
  `batch_id` varchar(64) NOT NULL DEFAULT '',
  `evidence_grade` varchar(32) NOT NULL DEFAULT 'legacy',
  `publish_result` json NOT NULL,
  `published_at` datetime DEFAULT NULL,
  `withdrawn_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_role_definition_versions_version_id` (`version_id`),
  KEY `ix_role_definition_versions_draft_id` (`draft_id`),
  KEY `ix_role_definition_versions_role_id` (`role_id`),
  KEY `ix_role_definition_versions_status` (`status`),
  KEY `ix_role_definition_versions_origin` (`origin`),
  KEY `ix_role_definition_versions_batch_id` (`batch_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS `publish_tasks` (
  `id` varchar(64) NOT NULL,
  `idempotency_key` varchar(160) NOT NULL,
  `version_id` varchar(64) NOT NULL,
  `draft_id` varchar(64) NOT NULL DEFAULT '',
  `status` varchar(24) NOT NULL DEFAULT 'pending',
  `attempts` int NOT NULL DEFAULT 0,
  `error` text NOT NULL,
  `payload` json NOT NULL,
  `result` json NOT NULL,
  `next_retry_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_publish_tasks_idempotency_key` (`idempotency_key`),
  KEY `ix_publish_tasks_version_id` (`version_id`),
  KEY `ix_publish_tasks_draft_id` (`draft_id`),
  KEY `ix_publish_tasks_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS `agent_runs` (
  `id` varchar(64) NOT NULL,
  `batch_id` varchar(64) NOT NULL,
  `draft_id` varchar(64) NOT NULL DEFAULT '',
  `trigger` varchar(40) NOT NULL DEFAULT 'ingest',
  `scope` varchar(24) NOT NULL DEFAULT 'batch',
  `status` varchar(24) NOT NULL DEFAULT 'queued',
  `stages` json NOT NULL,
  `draft_count` int NOT NULL DEFAULT 0,
  `description_count` int NOT NULL DEFAULT 0,
  `llm_used` tinyint(1) NOT NULL DEFAULT 0,
  `error` text NOT NULL,
  `started_at` datetime NOT NULL,
  `finished_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_agent_runs_batch_id` (`batch_id`),
  KEY `ix_agent_runs_draft_id` (`draft_id`),
  KEY `ix_agent_runs_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE IF NOT EXISTS `agent_descriptions` (
  `id` varchar(64) NOT NULL,
  `draft_id` varchar(64) NOT NULL,
  `input_hash` varchar(64) NOT NULL,
  `provider` varchar(24) NOT NULL DEFAULT 'rules',
  `model` varchar(120) NOT NULL DEFAULT '',
  `prompt_version` varchar(80) NOT NULL,
  `status` varchar(24) NOT NULL DEFAULT 'rules',
  `llm_error` text NOT NULL,
  `sections` json NOT NULL,
  `markdown_path` text NOT NULL,
  `docx_path` text NOT NULL,
  `generated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_agent_descriptions_draft_id` (`draft_id`),
  KEY `ix_agent_descriptions_draft_id` (`draft_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;
