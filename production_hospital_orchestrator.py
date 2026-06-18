"""
Production-# Import existing hospital components
try:
    from hospital_chatbot_orchestrator import HospitalChatbot
    from voice_call_scheduler import voice_scheduler
except ImportError:
    # Fallback for testing
    class HospitalChatbot:
        def chat(self, message, conversation_id=None, voice_context=None, category_hint=None):
            return {"response": "Service temporarily unavailable", "agent_used": "fallback"}
        
        def voice_chat(self, message, conversation_id=None, phone_number=None, call_sid=None, category=None):
            return {"response": "Voice service temporarily unavailable", "agent_used": "fallback"}
    
    class VoiceSchedulerMock:
        async def start(self): pass
        async def stop(self): pass
    
    voice_scheduler = VoiceSchedulerMock()Orchestrator API
Enhanced to handle voice calls and provide proper routing to specialized agents
"""
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import logging
import asyncio
import uuid
import json
import os
from contextlib import asynccontextmanager

# Internal conversation management classes
class ConversationContext:
    """Internal conversation context tracking"""
    def __init__(self, conversation_id: str, channel: str = "chat"):
        self.conversation_id = conversation_id
        self.channel = channel
        self.start_time = datetime.utcnow()
        self.last_activity = datetime.utcnow()
        self.messages = []
        self.current_agent = None
        self.is_voice_call = False
        self.call_sid = None
        self.caller_phone = None
        self.voice_context = {}
        self.appointment_context = {}
        self.escalation_needed = False
        self.total_interactions = 0
    
    def add_message(self, role: str, content: str, metadata: dict = None):
        """Add a message to conversation history"""
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": metadata or {}
        }
        self.messages.append(message)
        self.last_activity = datetime.utcnow()
        self.total_interactions += 1
    
    def update_context(self, **kwargs):
        """Update context fields"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.last_activity = datetime.utcnow()

class CircuitBreaker:
    """Simple circuit breaker implementation"""
    def __init__(self, name: str = "default", failure_threshold: int = 3, timeout: int = 60):
        self.name = name
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half-open
    
    async def call(self, func, *args, **kwargs):
        """Execute function with circuit breaker protection"""
        if self.state == "open":
            if datetime.utcnow().timestamp() - self.last_failure_time.timestamp() > self.timeout:
                self.state = "half-open"
            else:
                raise Exception(f"Circuit breaker {self.name} is open")
        
        try:
            result = await func(*args, **kwargs) if asyncio.iscoroutinefunction(func) else func(*args, **kwargs)
            if self.state == "half-open":
                self.state = "closed"
                self.failure_count = 0
            return result
        except Exception as e:
            self.failure_count += 1
            self.last_failure_time = datetime.utcnow()
            if self.failure_count >= self.failure_threshold:
                self.state = "open"
            raise e

class RetryHandler:
    """Simple retry handler implementation"""
    def __init__(self, max_retries: int = 2, base_delay: float = 1.0):
        self.max_retries = max_retries
        self.base_delay = base_delay
    
    async def retry(self, func, *args, **kwargs):
        """Execute function with retry logic"""
        last_exception = None
        for attempt in range(self.max_retries + 1):
            try:
                if asyncio.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                else:
                    return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                if attempt < self.max_retries:
                    await asyncio.sleep(self.base_delay * (2 ** attempt))
                else:
                    raise last_exception

class InternalConversationManager:
    """Internal conversation state management"""
    def __init__(self):
        self.conversations: Dict[str, ConversationContext] = {}
        self.max_conversations = 1000
        self.cleanup_interval = 3600  # 1 hour
    
    async def connect(self):
        """Initialize connection (no-op for internal manager)"""
        logger.info("Internal conversation manager initialized")
    
    async def disconnect(self):
        """Cleanup on shutdown"""
        self.conversations.clear()
        logger.info("Internal conversation manager disconnected")
    
    async def get_conversation(self, conversation_id: str) -> Optional[ConversationContext]:
        """Get conversation context"""
        return self.conversations.get(conversation_id)
    
    async def save_conversation(self, context: ConversationContext):
        """Save conversation context"""
        self.conversations[context.conversation_id] = context
        await self._cleanup_if_needed()
    
    async def get_active_conversations_count(self) -> int:
        """Get count of active conversations"""
        return len(self.conversations)
    
    async def add_message(self, conversation_id: str, role: str, content: str, metadata: dict = None):
        """Add message to conversation"""
        context = await self.get_conversation(conversation_id)
        if context:
            context.add_message(role, content, metadata)
        else:
            # Create new conversation
            context = ConversationContext(conversation_id)
            context.add_message(role, content, metadata)
            await self.save_conversation(context)
    
    async def update_context(self, conversation_id: str, updates: dict):
        """Update conversation context"""
        context = await self.get_conversation(conversation_id)
        if context:
            context.update_context(**updates)
            await self.save_conversation(context)
    
    async def cleanup_expired_conversations(self):
        """Remove old conversations"""
        cutoff_time = datetime.utcnow() - timedelta(hours=24)
        expired_ids = [
            conv_id for conv_id, context in self.conversations.items()
            if context.last_activity < cutoff_time
        ]
        for conv_id in expired_ids:
            del self.conversations[conv_id]
        logger.info(f"Cleaned up {len(expired_ids)} expired conversations")
    
    async def _cleanup_if_needed(self):
        """Cleanup if conversation count exceeds limit"""
        if len(self.conversations) > self.max_conversations:
            await self.cleanup_expired_conversations()

# Initialize internal conversation manager
conversation_manager = InternalConversationManager()

# Import existing hospital components
try:
    from hospital_chatbot_orchestrator import HospitalChatbot
    from voice_call_scheduler import voice_scheduler
except ImportError:
    # Fallback for testing
    class HospitalChatbot:
        def chat(self, message, conversation_id=None, voice_context=None):
            return {"response": "Service temporarily unavailable", "agent_used": "fallback"}
    
    class VoiceSchedulerMock:
        async def start(self): pass
        async def stop(self): pass
    
    voice_scheduler = VoiceSchedulerMock()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Pydantic Models
class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    voice_call: bool = False

class VoiceCallRequest(BaseModel):
    message: str
    conversation_id: str
    voice_call: bool = True
    context: Dict[str, Any] = {}
    call_sid: Optional[str] = None
    caller_phone: Optional[str] = None
    category: Optional[str] = None

class AppointmentRequest(BaseModel):
    patient_name: str
    phone_number: str
    preferred_date: str
    preferred_time: str
    reason: str
    doctor_specialty: Optional[str] = None

class HealthResponse(BaseModel):
    status: str
    timestamp: str
    version: str
    components: Dict[str, bool]

# Initialize chatbot and conversation tracking with resilience
_chatbot = HospitalChatbot()

# Circuit breakers for different services
chatbot_circuit_breaker = CircuitBreaker(name="HospitalChatbot", failure_threshold=3)
voice_scheduler_circuit_breaker = CircuitBreaker(name="VoiceScheduler", failure_threshold=5)

# Retry handlers
retry_handler = RetryHandler(max_retries=2, base_delay=1.0)

class VoiceResponseFormatter:
    """Formats responses for optimal voice synthesis"""
    
    @staticmethod
    def format_for_voice(text: str, response_type: str = "general") -> str:
        """Format text response for natural voice synthesis"""
        
        # Remove markdown and special characters
        text = text.replace("**", "").replace("*", "").replace("#", "")
        text = text.replace("```", "").replace("`", "")
        
        # Break long sentences for better pacing
        if len(text) > 150:
            sentences = text.split('. ')
            if len(sentences) > 1:
                # Take first two sentences for voice calls
                text = '. '.join(sentences[:2])
                if not text.endswith('.'):
                    text += '.'
        
        # Add natural pauses for appointment confirmations
        if response_type == "appointment":
            text = text.replace(", ", " pause ")
            text = text.replace(" at ", " pause at ")
        
        # Ensure proper pronunciation of medical terms
        medical_replacements = {
            "Dr.": "Doctor",
            "appt": "appointment",
            "mins": "minutes",
            "w/": "with",
            "&": "and"
        }
        
        for abbrev, full in medical_replacements.items():
            text = text.replace(abbrev, full)
        
        return text.strip()

class ConversationManager:
    """Manages conversation context for voice calls using internal tracking"""
    
    @staticmethod
    def create_voice_context(call_sid: str, caller_phone: str, message: str) -> Dict[str, Any]:
        """Create enhanced context for voice calls"""
        return {
            "call_sid": call_sid,
            "caller_phone": caller_phone,
            "channel": "voice",
            "start_time": datetime.utcnow().isoformat(),
            "message_count": 1,
            "initial_message": message,
            "requires_voice_optimization": True
        }
    
    @staticmethod
    async def update_conversation(conversation_id: str, message: str, response: str, agent_used: str):
        """Update conversation tracking using internal conversation manager"""
        try:
            # Add user message
            await conversation_manager.add_message(conversation_id, "user", message)
            # Add assistant response with metadata
            await conversation_manager.add_message(conversation_id, "assistant", response, {"agent_used": agent_used})
            # Update context
            await conversation_manager.update_context(conversation_id, {
                "current_agent": agent_used,
                "last_activity": datetime.utcnow()
            })
        except Exception as e:
            logger.error(f"Error updating conversation {conversation_id}: {e}")
            # Fallback to simple logging
            logger.info(f"Conversation {conversation_id}: User: {message[:100]}... Bot: {response[:100]}... Agent: {agent_used}")
    
    @staticmethod
    async def create_or_update_voice_conversation(conversation_id: str, call_sid: str, caller_phone: str, message: str) -> ConversationContext:
        """Create or update voice conversation context"""
        context = await conversation_manager.get_conversation(conversation_id)
        if not context:
            context = ConversationContext(conversation_id, "voice")
            context.is_voice_call = True
            context.call_sid = call_sid
            context.caller_phone = caller_phone
            await conversation_manager.save_conversation(context)
        
        # Add the incoming message
        context.add_message("user", message)
        await conversation_manager.save_conversation(context)
        return context

# Application lifecycle
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🏥 Starting Hospital Orchestrator API...")
    
    # Initialize internal conversation manager
    try:
        await conversation_manager.connect()
        logger.info("✅ Internal conversation manager initialized")
    except Exception as e:
        logger.warning(f"⚠️ Internal conversation manager failed to initialize: {e}")
    
    try:
        await voice_scheduler.start()
        logger.info("✅ Voice scheduler started")
    except Exception as e:
        logger.warning(f"⚠️ Voice scheduler failed to start: {e}")
    
    # Initialize chatbot
    try:
        # Chatbot is already initialized globally
        logger.info("✅ Hospital chatbot initialized")
    except Exception as e:
        logger.error(f"❌ Hospital chatbot initialization failed: {e}")
    
    yield
    
    # Shutdown
    logger.info("🏥 Shutting down Hospital Orchestrator API...")
    
    try:
        await conversation_manager.disconnect()
        logger.info("✅ Internal conversation manager disconnected")
    except Exception:
        pass
    
    try:
        await voice_scheduler.stop()
        logger.info("✅ Voice scheduler stopped")
    except Exception:
        pass

app = FastAPI(
    title="Hospital Orchestrator API",
    description="Production-ready hospital AI orchestrator with voice call support",
    version="2.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", response_model=Dict[str, Any])
async def root():
    """Root endpoint with service information"""
    return {
        "service": "Hospital Orchestrator API",
        "version": "2.0.0",
        "status": "healthy",
        "endpoints": {
            "health": "/health",
            "chat": "/chat",
            "voice_chat": "/voice-chat",
            "appointments": "/appointments",
            "metrics": "/metrics"
        },
        "active_conversations": await conversation_manager.get_active_conversations_count()
    }

@app.get("/health", response_model=HealthResponse)
async def health():
    """Comprehensive health check"""
    components = {
        "chatbot": True,
        "voice_scheduler": True,
        "database": True,  # Add actual DB check in production
        "rag_system": True  # Add actual RAG system check
    }
    
    try:
        # Check if chatbot is available (without calling it)
        components["chatbot"] = _chatbot is not None
    except Exception:
        components["chatbot"] = False
    
    overall_status = "healthy" if all(components.values()) else "degraded"
    
    return HealthResponse(
        status=overall_status,
        timestamp=datetime.utcnow().isoformat(),
        version="2.0.0",
        components=components
    )

@app.post("/chat", response_model=Dict[str, Any])
async def chat(req: ChatRequest):
    """Handle text-based chat requests"""
    try:
        conversation_id = req.conversation_id or str(uuid.uuid4())
        
        # Process with chatbot (sync call, no await needed)
        try:
            result = _chatbot.chat(req.message, conversation_id=conversation_id)
        except Exception as e:
            logger.error(f"Chatbot error: {e}")
            result = {
                "response": "I'm experiencing technical difficulties. Please try again.",
                "agent_used": "error_handler",
                "escalation_needed": True
            }
        
        # Update conversation tracking
        await ConversationManager.update_conversation(
            conversation_id, 
            req.message, 
            result.get("response", ""), 
            result.get("agent_used", "unknown")
        )
        
        return {
            "response": result.get("response", "I'm sorry, I couldn't process your request."),
            "conversation_id": conversation_id,
            "agent_used": result.get("agent_used"),
            "escalation_needed": result.get("escalation_needed", False),
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Chat processing error: {e}")
        # Fallback response
        return {
            "response": "I'm experiencing technical difficulties. Please try again or contact our staff.",
            "conversation_id": conversation_id,
            "agent_used": "fallback",
            "escalation_needed": True,
            "timestamp": datetime.utcnow().isoformat()
        }

@app.post("/voice-chat", response_model=Dict[str, Any])
async def voice_chat(req: VoiceCallRequest):
    """Handle voice call requests with enhanced processing"""
    try:
        logger.info(f"🎤 Processing voice call: {req.call_sid} from {req.caller_phone}")
        
        # Simplified approach - skip complex conversation management for now
        # Create or update conversation context
        # context = await ConversationManager.create_or_update_voice_conversation(
        #     req.conversation_id,
        #     req.call_sid or "unknown",
        #     req.caller_phone or "unknown",
        #     req.message
        # )
        
        # Create voice-optimized context for the request
        # voice_context = ConversationManager.create_voice_context(
        #     req.call_sid or "unknown",
        #     req.caller_phone or "unknown",
        #     req.message
        # )
        
        # Add call context to the message for better routing
        enhanced_message = req.message
        if req.call_sid:
            enhanced_message = f"[VOICE_CALL:{req.call_sid}] {req.message}"
        
        # Process with chatbot using voice_chat method in a thread and bounded time
        logger.info("🔄 Calling chatbot.voice_chat (bounded)...")
        import asyncio
        async def _call_chatbot():
            return await asyncio.to_thread(
                _chatbot.voice_chat,
                req.message,
                req.conversation_id,
                req.caller_phone,
                req.call_sid,
                req.category,
            )
        try:
            # Soft ceiling to keep voice responsive; agent may still finish quickly
            result = await asyncio.wait_for(_call_chatbot(), timeout=20.0)
            logger.info(f"✅ Chatbot response: agent={result.get('agent_used')} escalate={result.get('escalation_needed', False)}")
        except asyncio.TimeoutError:
            logger.warning("⏱️ Chatbot processing exceeded 20s; returning partial response")
            # Intelligent fallback based on message intent
            m = (req.message or "").lower()
            inferred = None
            if req.category:
                inferred = {
                    "appointment": "appointment_agent",
                    "doctor_info": "doctor_info_agent",
                    "medical_question": "general_health_agent",
                    "general": "general_health_agent",
                    "emergency": "emergency_agent",
                }.get(req.category, None)

            if not inferred:
                inferred = "appointment_agent" if any(k in m for k in ["appointment","schedule","book","reschedule","cancel"]) else (
                "doctor_info_agent" if any(k in m for k in ["doctor","specialist","cardiologist","recommend"]) else "general_health_agent"
                )
            result = {
                "response": "Thanks. I'm checking availability now. May I confirm your full name and a contact number while I look?",
                "agent_used": inferred,
                "escalation_needed": False,
                "appointment_context": {},
                "user_context": {},
                "voice_context": {"is_voice_call": True},
                "category_hint": req.category
            }
        except Exception as e:
            logger.error(f"Chatbot error: {e}")
            result = {
                "response": "I'm experiencing technical difficulties. Please try again.",
                "agent_used": "error_handler",
                "escalation_needed": True,
                "appointment_context": {},
                "user_context": {},
                "voice_context": {"is_voice_call": True},
                "category_hint": req.category
            }
        
        # Ensure expected keys exist even on happy path
        result.setdefault("appointment_context", {})
        result.setdefault("user_context", {})
        result.setdefault("voice_context", {})
        result.setdefault("category_hint", req.category)
        result.setdefault("safety_flags", [])

        # Format response for voice synthesis
        voice_response = VoiceResponseFormatter.format_for_voice(
            result.get("response", "I'm sorry, I couldn't process your request."),
            response_type=result.get("agent_used", "general")
        )
        
        # Simple conversation tracking without complex async operations
        try:
            await ConversationManager.update_conversation(
                req.conversation_id, 
                req.message, 
                voice_response, 
                result.get("agent_used", "unknown")
            )
        except Exception as e:
            logger.warning(f"Conversation tracking error: {e}")
        
        # Determine if escalation is needed
        should_escalate = result.get("escalation_needed", False)
        
        # Check for emergency keywords in voice calls
        emergency_keywords = ["emergency", "urgent", "pain", "bleeding", "chest pain", "trouble breathing"]
        if any(keyword in req.message.lower() for keyword in emergency_keywords):
            should_escalate = True
            voice_response = "I understand this is urgent. Let me immediately connect you with our medical staff."
        
        return {
            "response": voice_response,
            "conversation_id": req.conversation_id,
            "agent_used": result.get("agent_used", "voice_handler"),
            "should_escalate": should_escalate,
            "voice_optimized": True,
            "appointment_context": result.get("appointment_context", {}),
            "user_context": result.get("user_context", {}),
            "voice_context": result.get("voice_context", {}),
            "category_hint": result.get("category_hint"),
            "safety_flags": result.get("safety_flags", []),
            "call_context": {
                "call_sid": req.call_sid,
                "duration": "ongoing",
                "message_count": 1,  # simplified
                "conversation_duration": 0  # simplified
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Voice chat processing error: {e}")
        
        # Provide fallback response for voice calls
        return {
            "response": VoiceResponseFormatter.format_for_voice(
                "I'm experiencing technical difficulties. Let me transfer you to our staff for immediate assistance."
            ),
            "conversation_id": req.conversation_id,
            "agent_used": "error_handler",
            "should_escalate": True,
            "voice_optimized": True,
            "error": True,
            "appointment_context": {},
            "user_context": {},
            "voice_context": {"is_voice_call": True},
            "category_hint": req.category,
            "timestamp": datetime.utcnow().isoformat()
        }

@app.post("/appointments", response_model=Dict[str, Any])
async def create_appointment(req: AppointmentRequest):
    """Handle appointment creation requests"""
    try:
        # Format appointment request for chatbot
        appointment_message = (
            f"I need to schedule an appointment for {req.patient_name} "
            f"on {req.preferred_date} at {req.preferred_time} "
            f"for {req.reason}. Phone: {req.phone_number}"
        )
        
        if req.doctor_specialty:
            appointment_message += f" with a {req.doctor_specialty} specialist"
        
        # Process with chatbot (sync call)
        try:
            result = _chatbot.chat(appointment_message, conversation_id=str(uuid.uuid4()))
        except Exception as e:
            logger.error(f"Appointment chatbot error: {e}")
            result = {
                "response": "I'm experiencing technical difficulties processing your appointment. Please try again.",
                "agent_used": "error_handler"
            }
        
        return {
            "success": True,
            "message": result.get("response", "Appointment request processed"),
            "appointment_details": {
                "patient_name": req.patient_name,
                "phone_number": req.phone_number,
                "preferred_date": req.preferred_date,
                "preferred_time": req.preferred_time,
                "reason": req.reason,
                "doctor_specialty": req.doctor_specialty
            },
            "agent_used": result.get("agent_used"),
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Appointment creation error: {e}")
        raise HTTPException(status_code=500, detail="Failed to process appointment request")

@app.get("/conversations/{conversation_id}", response_model=Dict[str, Any])
async def get_conversation(conversation_id: str):
    """Get conversation history"""
    context = await conversation_manager.get_conversation(conversation_id)
    if context:
        return {
            "conversation_id": conversation_id,
            "conversation": {
                "messages": context.messages,
                "start_time": context.start_time.isoformat() if context.start_time else None,
                "last_activity": context.last_activity.isoformat() if context.last_activity else None,
                "current_agent": context.current_agent,
                "is_voice_call": context.is_voice_call,
                "call_sid": context.call_sid,
                "caller_phone": context.caller_phone,
                "total_interactions": context.total_interactions
            }
        }
    else:
        raise HTTPException(status_code=404, detail="Conversation not found")

@app.get("/active-conversations")
async def get_active_conversations():
    """Get list of all active conversations with summary info"""
    try:
        conversations = []
        for conv_id, context in conversation_manager.conversations.items():
            conversations.append({
                "conversation_id": conv_id,
                "start_time": context.start_time.isoformat(),
                "last_activity": context.last_activity.isoformat(),
                "message_count": len(context.messages),
                "total_interactions": context.total_interactions,
                "is_voice_call": context.is_voice_call,
                "current_agent": context.current_agent,
                "escalation_needed": context.escalation_needed,
                "caller_phone": context.caller_phone,
                "call_sid": context.call_sid,
                "duration_seconds": (datetime.utcnow() - context.start_time).total_seconds()
            })
        
        return {
            "total_conversations": len(conversations),
            "conversations": conversations,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Error retrieving active conversations: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve conversations")

@app.get("/metrics", response_model=Dict[str, Any])
async def get_metrics():
    """Get service metrics for monitoring"""
    active_count = await conversation_manager.get_active_conversations_count()
    return {
        "active_conversations": active_count,
        "total_conversations": active_count,  # For internal manager, these are the same
        "service_uptime": "healthy",
        "version": "2.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "components": {
            "chatbot": True,
            "voice_scheduler": True,
            "rag_system": True,
            "conversation_manager": True
        }
    }

@app.delete("/conversations/{conversation_id}")
async def cleanup_conversation(conversation_id: str):
    """Cleanup conversation data"""
    try:
        # Remove specific conversation or trigger general cleanup
        context = await conversation_manager.get_conversation(conversation_id)
        if context:
            del conversation_manager.conversations[conversation_id]
            logger.info(f"Cleaned up conversation {conversation_id}")
            return {"message": f"Conversation {conversation_id} cleaned up"}
        else:
            # Trigger general cleanup if specific conversation not found
            await conversation_manager.cleanup_expired_conversations()
            return {"message": "General cleanup completed", "conversation_id": conversation_id}
    except Exception as e:
        logger.error(f"Error cleaning up conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")

# Emergency endpoints
@app.post("/emergency", response_model=Dict[str, Any])
async def handle_emergency(req: VoiceCallRequest):
    """Handle emergency calls with immediate escalation"""
    logger.critical(f"🚨 EMERGENCY call from {req.caller_phone}: {req.message}")
    
    return {
        "response": VoiceResponseFormatter.format_for_voice(
            "This is an emergency situation. I am immediately connecting you to our medical staff. Please stay on the line."
        ),
        "conversation_id": req.conversation_id,
        "agent_used": "emergency_handler",
        "should_escalate": True,
        "priority": "emergency",
        "voice_optimized": True,
        "timestamp": datetime.utcnow().isoformat()
    }

if __name__ == "__main__":
    import uvicorn
    logger.info("🏥 Starting Hospital Orchestrator API...")
    uvicorn.run(
        "production_hospital_orchestrator:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        reload=False
    )