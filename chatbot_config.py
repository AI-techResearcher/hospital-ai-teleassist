"""
Hospital Chatbot Configuration
Extends base config with orchestration-specific settings
"""

from config import AppConfig
from typing import Dict, Any, List
import os

class HospitalChatbotConfig(AppConfig):
    """Extended configuration for the orchestrated hospital chatbot"""
    
    # Agent Configuration
    default_agent_timeout: int = 30  # seconds
    max_conversation_turns: int = 50
    enable_agent_handoff: bool = True
    
    # Routing Configuration
    confidence_threshold: float = 0.7
    fallback_agent: str = "general_health_agent"
    
    # RAG Configuration (enhanced)
    rag_search_k: int = 5
    rag_score_threshold: float = 0.6
    enable_hybrid_search: bool = True
    
    # Appointment Agent Configuration
    appointment_db_path: str = "./Apointment_agent/appointments.db"
    max_booking_attempts: int = 3
    booking_confirmation_required: bool = True
    
    # Safety and Moderation
    emergency_keywords: List[str] = [
        "chest pain", "difficulty breathing", "severe bleeding",
        "heart attack", "stroke", "unconscious", "emergency",
        "can't breathe", "severe pain", "bleeding heavily",
        "suicide", "self harm", "kill myself"
    ]
    
    escalation_keywords: List[str] = [
        "complaint", "disappointed", "terrible service",
        "want to speak to manager", "file a complaint"
    ]
    
    # Response Generation
    max_response_length: int = 1000
    include_source_citations: bool = True
    personalization_enabled: bool = True
    
    # Logging and Monitoring
    log_conversations: bool = True
    log_sensitive_data: bool = False
    conversation_retention_days: int = 30
    
    # Integration Settings
    enable_appointment_integration: bool = True
    enable_rag_integration: bool = True
    enable_emergency_detection: bool = True
    
    # Performance Settings
    cache_responses: bool = True
    cache_ttl_seconds: int = 300  # 5 minutes
    
    # External Services
    notification_service_enabled: bool = False
    sms_notifications: bool = False
    email_notifications: bool = False
    
    class Config:
        env_prefix = "HOSPITAL_CHATBOT_"
        case_sensitive = False

def load_chatbot_config() -> HospitalChatbotConfig:
    """Load and validate chatbot configuration"""
    return HospitalChatbotConfig()

# Validation functions
def validate_agent_config(config: HospitalChatbotConfig) -> Dict[str, Any]:
    """Validate agent configuration and return status"""
    validation_results = {
        "valid": True,
        "warnings": [],
        "errors": []
    }
    
    # Check required API keys
    if not config.openai_api_key:
        validation_results["errors"].append("OpenAI API key is required")
        validation_results["valid"] = False
    
    # Check database paths
    if config.enable_appointment_integration:
        if not os.path.exists(config.appointment_db_path):
            validation_results["warnings"].append(f"Appointment database not found at {config.appointment_db_path}")
    
    # Check Weaviate connection for RAG
    if config.enable_rag_integration:
        try:
            import requests
            response = requests.get(config.weaviate_url, timeout=5)
            if response.status_code != 200:
                validation_results["warnings"].append("Weaviate service not accessible")
        except Exception:
            validation_results["warnings"].append("Cannot connect to Weaviate service")
    
    return validation_results

# Agent routing configuration
AGENT_ROUTING_PATTERNS = {
    "doctor_info_agent": [
        r"(?i)(doctor|physician|specialist|cardiologist|neurologist|pediatrician)",
        r"(?i)(find.*doctor|search.*doctor|doctor.*profile)",
        r"(?i)(specialty|specialization|medical.*expert)",
        r"(?i)(who.*treats|best.*doctor.*for)",
        r"(?i)(hospital.*services|medical.*services)"
    ],
    
    "appointment_agent": [
        r"(?i)(book|schedule|make).*appointment",
        r"(?i)(reschedule|change|modify).*appointment", 
        r"(?i)(cancel.*appointment|appointment.*cancel)",
        r"(?i)(available.*slot|appointment.*availability)",
        r"(?i)(my.*appointment|appointment.*status)",
        r"(?i)appointment.*(tomorrow|today|next|monday|tuesday|wednesday|thursday|friday|saturday|sunday)",
        r"(?i)(want|need|like|would like).*(appointment|booking)",
        r"(?i)(see|visit).*(doctor|specialist).*(tomorrow|next week|monday|tuesday|wednesday|thursday|friday)",
        r"(?i)(book|schedule).*(cardiologist|pediatrician|neurologist|dermatologist)",
        r"(?i)(\d{1,2}(am|pm|:)).*(appointment|booking)"
    ],
    
    "general_health_agent": [
        r"(?i)(symptom|feeling|health.*question)",
        r"(?i)(what.*should.*do|advice|guidance)",
        r"(?i)(condition|disease|illness|treatment)",
        r"(?i)(medicine|medication|drug)",
        r"(?i)(health.*tip|prevention|wellness)"
    ],
    
    "emergency_agent": [
        r"(?i)(emergency|urgent|help.*me)",
        r"(?i)(chest.*pain|heart.*attack|stroke)",
        r"(?i)(bleeding|blood|severe.*pain)",
        r"(?i)(can't.*breathe|difficulty.*breathing)",
        r"(?i)(unconscious|faint|collapse)"
    ]
}

# Response templates
RESPONSE_TEMPLATES = {
    "greeting": "Hello! I'm your Hospital AI Assistant. I can help you find doctors, book appointments, answer health questions, and provide medical information. How can I assist you today?",
    
    "clarification": "I'd be happy to help! Could you please provide more details about what you're looking for? For example, are you trying to:\n• Find a doctor or specialist\n• Book or manage an appointment\n• Get health information or advice\n• Handle an urgent medical concern",
    
    "error": "I apologize, but I'm experiencing technical difficulties. Please try again in a moment or contact our staff directly for immediate assistance.",
    
    "escalation": "I understand your concern requires additional attention. I'm connecting you with a human representative who can better assist you with this matter.",
    
    "emergency": "🚨 If this is a medical emergency, please call 911 immediately or go to the nearest emergency room. For urgent but non-emergency situations, you can visit our urgent care center or call our 24/7 nurse line.",
    
    "appointment_success": "✅ Your appointment has been successfully {action}. You should receive a confirmation shortly with all the details.",
    
    "doctor_info": "Here's the information about {doctor_name}:\n• Specialty: {specialty}\n• Experience: {experience}\n• Languages: {languages}\n• Available locations: {locations}"
}

# Default conversation starters
CONVERSATION_STARTERS = [
    "Find a doctor by specialty",
    "Book an appointment",
    "Check my appointment status",
    "Get health information",
    "Emergency assistance",
    "Hospital services and locations"
]

if __name__ == "__main__":
    # Test configuration loading
    config = load_chatbot_config()
    validation = validate_agent_config(config)
    
    print("Hospital Chatbot Configuration:")
    print(f"✅ Valid: {validation['valid']}")
    
    if validation['warnings']:
        print("\n⚠️ Warnings:")
        for warning in validation['warnings']:
            print(f"  - {warning}")
    
    if validation['errors']:
        print("\n❌ Errors:")
        for error in validation['errors']:
            print(f"  - {error}")
    
    print(f"\nAgent Integration Status:")
    print(f"📋 Appointment Agent: {'✅' if config.enable_appointment_integration else '❌'}")
    print(f"🔍 RAG Integration: {'✅' if config.enable_rag_integration else '❌'}")
    print(f"🚨 Emergency Detection: {'✅' if config.enable_emergency_detection else '❌'}")
