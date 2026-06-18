from pydantic_settings import BaseSettings
from typing import Optional, List
import os

class AppConfig(BaseSettings):
    # Existing RAG Configuration (maintain compatibility)
    weaviate_url: str = "http://localhost:8080"
    weaviate_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    weaviate_class: str = "healthdata"  # override to 'DoctorProfile' for doctor ingestion
    text_key: str = "text"             # override to 'content' if using a separate class schema
    metadata_attributes: List[str] = ["source", "category"]
    semantic_k: int = 10
    bm25_k: int = 5
    alpha: float = 0.5
    
    # Hospital AI Specific Configuration
    # API Keys
    anthropic_api_key: Optional[str] = None
    langsmith_api_key: Optional[str] = None
    
    # Database Configuration
    database_url: str = "sqlite:///./hospital_ai.db"
    redis_url: str = "redis://localhost:6379"
    
    # FHIR Configuration
    use_native_fhir: bool = False
    fhir_base_url: Optional[str] = None
    
    # Twilio Configuration (for SMS/Voice)
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_phone_number: Optional[str] = None
    
    # Security
    secret_key: str = "your-secret-key-change-in-production"
    
    # Application Settings
    debug: bool = True
    log_level: str = "INFO"
    
    # Hospital Specific Settings
    hospital_name: str = "Main Hospital"
    hospital_timezone: str = "UTC"
    appointment_duration_minutes: int = 30
    reminder_hours_before: List[int] = [24, 2]  # Send reminders 24h and 2h before
    
    # Safety Settings
    enable_phi_redaction: bool = True
    enable_emergency_detection: bool = True
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

# Database Configuration for appointment agent compatibility
DB_CONFIG = {
    "database": os.path.join(os.path.dirname(__file__), "Apointment_agent", "appointments.db"),
    "type": "sqlite"
}

def load_config() -> AppConfig:
    """
    Loads configuration from environment variables or .env file.
    """
    return AppConfig()