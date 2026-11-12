from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ROOT = BACKEND_ROOT.parent
APP_DATA_ROOT = EXAMPLE_ROOT / "应用数据"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env.local", env_file_encoding="utf-8", extra="ignore"
    )

    app_host: str = "127.0.0.1"
    app_port: int = 8010
    frontend_origin: str = "http://127.0.0.1:5175"
    neo4j_url: str = "http://127.0.0.1:7474"
    neo4j_database: str = "neo4j"
    neo4j_user: str = "neo4j"
    neo4j_password: str
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_database: str = "career_insight"
    mysql_user: str = "career_insight_app"
    mysql_password: str
    agent_provider: str = "rules"
    entity_linker_enabled: bool = False
    agent_pipeline_enabled: bool = False
    agent_description_enabled: bool = True
    agent_description_max_drafts: int = 30
    agent_description_max_tokens: int = 4096
    agent_description_timeout_seconds: int = 90
    agent_description_prompt_version: str = "agent-description-v1"
    agent_run_stale_minutes: int = 60
    feature_min_sample: int = 5
    emerging_role_age_months: int = 3
    emerging_role_mom_growth: float = 0.5
    emerging_role_min_sources: int = 2
    emerging_role_min_observations: int = 5
    capability_shift_top5_delta: int = 2
    capability_shift_jaccard: float = 0.5
    skill_surge_share_pp: float = 0.2
    skill_surge_relative_growth: float = 0.5
    skill_surge_min_postings: int = 5
    skill_surge_min_sources: int = 2
    role_decline_mom_drop: float = -0.3
    role_decline_consecutive_months: int = 2
    role_decline_base_sample: int = 10
    skill_obsolescence_months: int = 3
    skill_obsolescence_cumulative_drop: float = 0.3
    skill_obsolescence_base_share: float = 0.1
    signal_suppression_days: int = 30
    agent_base_url: str = ""
    agent_chat_path: str = "/api/chat"
    agent_api_key: str = ""
    agent_user_id: str = "career-insight-local"
    agent_career_planning_bot_id: str = ""
    agent_ability_analysis_bot_id: str = ""
    agent_timeout_seconds: int = 60
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    interview_question_count: int = 6
    interview_asr_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    interview_asr_api_key: str = ""
    interview_asr_model: str = "paraformer-v2"
    interview_asr_timeout_seconds: int = 90
    auth_secret: str
    auth_token_hours: int = 12
    personal_username: str = "user"
    personal_password: str
    admin_username: str = "admin"
    admin_password: str
    enterprise_username: str = "enterprise"
    enterprise_password: str = "123456"

    @property
    def mysql_url(self) -> str:
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}?charset=utf8mb4"
        )

    @property
    def agent_configured(self) -> bool:
        provider = self.agent_provider.strip().lower()
        if provider == "coze":
            return bool(
                self.agent_base_url.strip()
                and self.agent_api_key.strip()
                and (self.agent_career_planning_bot_id.strip() or self.agent_ability_analysis_bot_id.strip())
            )
        return provider == "external" and bool(self.agent_base_url.strip())

    def agent_bot_id(self, mode: str = "career_planning") -> str:
        if mode == "ability_analysis":
            return self.agent_ability_analysis_bot_id.strip() or self.agent_career_planning_bot_id.strip()
        return self.agent_career_planning_bot_id.strip() or self.agent_ability_analysis_bot_id.strip()


settings = Settings()

for directory in ("uploads", "reports", "logs", "derived", "backups", "quality"):
    (APP_DATA_ROOT / directory).mkdir(parents=True, exist_ok=True)
