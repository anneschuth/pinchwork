from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "data/pinchwork.db"
    host: str = "0.0.0.0"
    port: int = 8000
    initial_credits: int = 100
    task_expire_hours: int = 72
    max_wait_seconds: int = 300
    match_timeout_seconds: int = 120
    system_task_auto_approve_seconds: int = 60
    platform_agent_id: str = "ag-platform"
    match_credits: int = 3
    verify_credits: int = 5
    capability_extract_credits: int = 2
    platform_fee_percent: float = 10.0
    admin_key: str | None = None
    disable_auto_approve: bool = False
    max_abandons_before_cooldown: int = 5
    abandon_cooldown_minutes: int = 30
    rate_limit_register: str = "5/hour"
    rate_limit_create: str = "30/minute"
    rate_limit_pickup: str = "60/minute"
    rate_limit_deliver: str = "30/minute"
    rate_limit_read: str = "120/minute"
    rate_limit_admin: str = "30/minute"
    max_extracted_tags: int = 20
    rejection_grace_minutes: int = 5
    welcome_task_enabled: bool = True
    welcome_task_credits: int = 2
    default_review_timeout_minutes: int = 30
    default_claim_timeout_minutes: int = 10
    verification_timeout_seconds: int = 120
    max_rejections: int = 3
    task_preview_length: int = 80
    webhook_timeout_seconds: int = 10
    webhook_max_retries: int = 3
    seed_marketplace_drip: bool = False
    seed_drip_rate_business: float = 8.0
    seed_drip_rate_evening: float = 3.0
    seed_drip_rate_night: float = 0.5

    model_config = {"env_prefix": "PINCHWORK_"}


settings = Settings()
