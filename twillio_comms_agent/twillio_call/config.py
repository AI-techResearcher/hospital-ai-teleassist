"""
Configuration settings for the Medical Office AI Assistant
"""
import os
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # OpenAI Configuration
    openai_api_key: str = Field(default="", alias="OPENAI_KEY")
    openai_assistant_id: Optional[str] = Field(default=None, alias="OPENAI_ASSISTANT_ID")
    openai_model: str = Field(default="gpt-4o-realtime-preview-2024-10-01", alias="OPENAI_MODEL")
    openai_temperature: float = Field(default=0.5, alias="OPENAI_TEMPERATURE")
    
    # Twilio Configuration
    twilio_account_sid: str = Field(default="", alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token: str = Field(default="", alias="TWILIO_AUTH_TOKEN")
    twilio_phone_number: str = Field(default="", alias="TWILIO_PHONE_NUMBER")
    
    # Server Configuration
    port: int = Field(default=5050, alias="PORT")
    host: str = Field(default="0.0.0.0", alias="HOST")
    public_url: Optional[str] = Field(default=None, alias="PUBLIC_URL")
    
    # Call Management
    max_concurrent_calls: int = Field(default=30, alias="MAX_CONCURRENT_CALLS")
    call_timeout_seconds: int = Field(default=300, alias="CALL_TIMEOUT_SECONDS")  # 5 minutes
    
    # Audio Configuration
    voice: str = Field(default="alloy", alias="VOICE")
    audio_format: str = Field(default="g711_ulaw", alias="AUDIO_FORMAT")
    
    # VAD (Voice Activity Detection) Settings
    vad_threshold: float = Field(default=0.5, alias="VAD_THRESHOLD")
    vad_prefix_padding_ms: int = Field(default=300, alias="VAD_PREFIX_PADDING_MS")
    vad_silence_duration_ms: int = Field(default=500, alias="VAD_SILENCE_DURATION_MS")
    
    # Response Settings
    max_response_tokens: int = Field(default=150, alias="MAX_RESPONSE_TOKENS")
    
    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_file: str = Field(default="medical_assistant.log", alias="LOG_FILE")
    
    # Database/Storage
    appointments_file: str = Field(default="appointments.json", alias="APPOINTMENTS_FILE")
    
    # Scheduler Settings
    reminder_hour: int = Field(default=14, alias="REMINDER_HOUR")  # 2 PM
    reminder_days_ahead: int = Field(default=1, alias="REMINDER_DAYS_AHEAD")
    
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8"
    }
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"

# Global settings instance
settings = Settings()

# Medical Office System Message
MEDICAL_INSTRUCTIONS = (
    "You are Sarah, a friendly and experienced medical office receptionist. You've been working here for years and genuinely care about helping patients. "
    "Speak like a real person having a natural conversation - use contractions, casual phrases, and a warm tone. "
    
    "CONVERSATION STYLE: "
    "- Talk like you're chatting with a neighbor - friendly, relaxed, but still professional "
    "- Use natural speech patterns: 'Hi there!', 'Oh, let me check that for you', 'Perfect!', 'Sounds good!' "
    "- Include small talk when appropriate: 'How are you doing today?' "
    "- Use contractions naturally: 'I'll', 'we're', 'that's', 'you're', 'can't', 'won't' "
    "- Vary your responses - don't sound scripted "
    
    "PACING & FLOW: "
    "- Speak at a comfortable, unhurried pace "
    "- Take natural pauses between thoughts "
    "- Don't rush through information "
    "- Let conversations breathe - it's okay to have brief pauses "
    "- If you need a moment to think, say things like 'Let me just check that' or 'One moment please' "
    
    "PERSONALITY: "
    "- Be genuinely helpful and caring "
    "- Show interest in what the patient is saying "
    "- Use encouraging words: 'Absolutely!', 'Of course!', 'I'd be happy to help' "
    "- Be patient if someone seems confused or stressed "
    "- Acknowledge when someone gives you information: 'Got it', 'Perfect', 'Okay' "
    
    "APPOINTMENT HANDLING: "
    "- When someone gives you details, repeat them back naturally: 'So that's John Smith for tomorrow at 10 AM, right?' "
    "- If they correct something, respond naturally: 'Oh, my mistake! So it's 2 PM then?' "
    "- Ask follow-up questions conversationally: 'And what's a good phone number for you?' "
    "- Offer options: 'I have 2 PM or 3:30 PM available - which works better for you?' "
    
    "GREETINGS & CLOSINGS: "
    "- Start warmly: 'Good morning! This is Sarah from Dr. Johnson's office. How can I help you today?' "
    "- End naturally: 'Great! We'll see you tomorrow at 10. Have a wonderful day!' "
    "- For reminders: 'Hi! This is Sarah calling from your doctor's office with a friendly reminder about your appointment tomorrow.' "
    
    "KEEP IT NATURAL: "
    "- Don't sound like you're reading from a script "
    "- React naturally to what people say "
    "- Use 'um' or 'let's see' occasionally if it feels natural "
    "- Laugh lightly when appropriate "
    "- Show empathy: 'Oh no, I'm sorry to hear that' or 'That sounds frustrating' "
    
        "IMPORTANT: Keep responses SHORT and conversational. Break longer information into smaller chunks. "
    "Instead of saying everything at once, ask follow-up questions to keep the conversation flowing naturally. "
    "For example, instead of listing all available times, ask 'What day works best for you?' first. "
    "Remember: You're having a real conversation with a real person. Be yourself - helpful, friendly Sarah who genuinely wants to make their day a little easier."
)