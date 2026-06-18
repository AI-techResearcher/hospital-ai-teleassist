#!/usr/bin/env python3
"""
Production-Ready Hospital Twilio Voice Agent with Real-time Capabilities
Combines hospital system integration with OpenAI Realtime API for natural conversations
"""
import os
import json
import asyncio
import base64
import websockets
import logging
import time
import httpx
import uuid
from datetime import datetime
from typing import Dict, Optional, Any
from fastapi import FastAPI, WebSocket, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from twilio.twiml.voice_response import VoiceResponse, Connect, Gather
from twilio.rest import Client
from pydantic import BaseModel
from dotenv import load_dotenv
import uvicorn
from contextlib import asynccontextmanager

# Load environment variables
env_path = os.path.join(os.path.dirname(__file__), '.env')
print(f"Loading .env from: {env_path}")
load_dotenv(dotenv_path=env_path)

# Configuration
OPENAI_API_KEY = os.getenv("OPENAI_KEY")
PORT = int(os.getenv("PORT", 5050))
PUBLIC_URL = (os.getenv("PUBLIC_URL") or "").strip()

# Twilio Configuration
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")

# Hospital System Configuration
HOSPITAL_ORCHESTRATOR_URL = os.getenv("HOSPITAL_ORCHESTRATOR_URL", "http://localhost:8000")
VOICE_SCHEDULER_URL = os.getenv("VOICE_SCHEDULER_URL", "http://localhost:8001")
HOSPITAL_API_TIMEOUT = int(os.getenv("HOSPITAL_API_TIMEOUT", "300"))  # Extended timeout for complex operations

# Heuristic escalation configuration for encouraging hospital system routing when model misses tool call
HOSPITAL_AUTO_ESCALATION = True  # Toggle to enable/disable heuristic nudge after each user turn
APPOINTMENT_KEYWORDS = [
    "appointment", "book", "schedule", "availability", "available", "slot", "reschedule", "cancel", "doctor visit"
]
DOCTOR_INFO_KEYWORDS = [
    "doctor", "specialist", "cardiologist", "dermatologist", "pediatrician", "neurologist", "orthopedic", "urologist", "oncologist", "endocrinologist", "physician"
]
EMERGENCY_KEYWORDS = [
    "emergency", "chest pain", "not breathing", "unconscious", "stroke", "severe bleeding"
]
GENERAL_HEALTH_KEYWORDS = [
    "symptom", "pain", "fever", "medication", "prescription", "treatment"
]

TRANSCRIPT_COOLDOWN_SECONDS = 5.0

# Allowed categories for hospital routing
ALLOWED_CATEGORIES = {"appointment", "doctor_info", "medical_question", "general", "emergency"}


def infer_category_from_text(text: str) -> str:
    """Infer hospital routing category from transcript keywords."""
    lowered = text.lower()
    if any(keyword in lowered for keyword in EMERGENCY_KEYWORDS):
        return "emergency"
    if any(keyword in lowered for keyword in APPOINTMENT_KEYWORDS):
        return "appointment"
    if any(keyword in lowered for keyword in DOCTOR_INFO_KEYWORDS):
        return "doctor_info"
    if any(keyword in lowered for keyword in GENERAL_HEALTH_KEYWORDS):
        return "medical_question"
    return "general"


def should_auto_escalate(text: str) -> bool:
    """Determine whether a transcript warrants immediate hospital escalation."""
    lowered = text.lower()
    return any(keyword in lowered for keyword in (
        APPOINTMENT_KEYWORDS
        + DOCTOR_INFO_KEYWORDS
        + EMERGENCY_KEYWORDS
        + GENERAL_HEALTH_KEYWORDS
    ))


def normalize_category(category: Optional[str]) -> str:
    """Normalize free-form category into one of ALLOWED_CATEGORIES."""
    try:
        if not category:
            return "general"
        c = str(category).strip().lower()
        if c in ALLOWED_CATEGORIES:
            return c
        synonyms_map = {
            "appointments": "appointment",
            "book": "appointment",
            "booking": "appointment",
            "schedule": "appointment",
            "reschedule": "appointment",
            "cancel": "appointment",
            "doctor": "doctor_info",
            "physician": "doctor_info",
            "specialist": "doctor_info",
            "medical": "medical_question",
            "question": "medical_question",
            "health": "medical_question",
            "info": "general",
            "information": "general",
            "emergency": "emergency",
        }
        return synonyms_map.get(c, "general")
    except Exception:
        return "general"


async def inject_assistant_reply(openai_ws, response_text: str, instructions: str = "Speak the latest hospital response clearly and concisely for the caller.", ensure_ready_callback=None):
    """Inject a text response into the OpenAI Realtime session and request audio synthesis."""
    try:
        if not response_text:
            return

        content_type = "text"
        message_item = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": content_type, "text": response_text}]
            }
        }
        await openai_ws.send(json.dumps(message_item))

        # Small delay to ensure message is processed
        await asyncio.sleep(0.2)

        if ensure_ready_callback:
            is_ready = await ensure_ready_callback()
            if not is_ready:
                logger.warning("⚠️ Skipping response.create because a previous response is still active")
                return

        response_request = {
            "type": "response.create",
            "response": {
                "modalities": ["text", "audio"],
                "instructions": instructions
            }
        }
        await openai_ws.send(json.dumps(response_request))
    except Exception as e:
        logger.error(f"Error injecting assistant reply: {e}")


def build_escalation_instruction() -> str:
    """Instruction injected after VAD speech stop to push model to call route_to_hospital_system when appropriate."""
    return (
        "Analyze ONLY the caller's most recent utterance you just received. "
        "If it involves any of: appointments (booking, rescheduling, cancelling), specific doctors or specialties, detailed medical information lookup, or urgent symptoms, YOU MUST call the function 'route_to_hospital_system' first with an appropriate category ('appointment','doctor_info','medical_question','emergency','general'). "
        "Use the exact user phrasing in the 'query' field. After the function call output returns, provide a concise verbal response summarizing or clarifying next steps. "
        "If none of those domains apply, continue normally WITHOUT calling the function. Keep responses under 3 sentences."
    )

# Initialize Twilio client
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Validate PUBLIC_URL after logger is set up
if not PUBLIC_URL:
    logger.error("❌ PUBLIC_URL not set in environment variables!")
    PUBLIC_URL = f"https://localhost:{PORT}"  # Fallback
elif not PUBLIC_URL.startswith("https://"):
    logger.warning(f"⚠️ PUBLIC_URL should start with https://, got: {PUBLIC_URL}")
    
logger.info(f"🌐 PUBLIC_URL loaded: {PUBLIC_URL}")

# Hospital-optimized instructions for OpenAI
HOSPITAL_INSTRUCTIONS = (
    "You are Sarah, a professional and empathetic medical office assistant at a hospital. "
    "You work with a sophisticated hospital system that can handle appointments, doctor information, "
    "medical questions, and patient routing. Speak naturally and professionally. "

    "CRITICAL - VOICE ONLY INTERACTION: "
    "- This is a VOICE-ONLY phone call. You CANNOT see the caller. "
    "- NEVER reference visual elements, bandages, appearances, or anything you 'see'. "
    "- Base ALL responses ONLY on what the caller tells you verbally. "
    "- If you need information, ASK the caller directly. "

    "CONVERSATION GUIDELINES: "
    "- Greet warmly and use the caller's name when provided. "
    "- Keep responses concise (1-3 sentences) but comprehensive. "
    "- Ask one question at a time and wait for responses. "
    "- Use plain language; avoid complex medical jargon. "
    "- Confirm important details with brief recaps. "
    "- Listen carefully to what the caller says and respond accordingly. "

    "HOSPITAL CAPABILITIES: "
    "- Schedule, modify, and cancel appointments "
    "- Provide doctor information and specialties "
    "- Answer general medical questions (non-diagnostic) "
    "- Route to appropriate departments "
    "- Handle emergency situations with immediate escalation "
    "- Provide hospital services information "

    "TONE & PACING: "
    "- Professional, calm, and empathetic "
    "- Use natural contractions: 'I'll', 'we'll', 'that's' "
    "- Brief acknowledgments: 'Okay', 'I understand', 'Got it' "

    "APPOINTMENT HANDLING: "
    "- Collect: patient name, reason for visit, preferred times "
    "- Verify insurance if mentioned "
    "- Confirm all details before finalizing "
    "- Provide clear next steps "

    "EMERGENCY PROTOCOLS: "
    "- For emergencies, immediately offer to connect to medical staff "
    "- Never provide medical diagnoses or treatment advice "
    "- Escalate complex medical questions to appropriate specialists "

    "IMPORTANT: You work with an advanced hospital AI system that processes your conversations "
    "and routes them to specialized medical agents. Be helpful, accurate, and professional."
)

# Pydantic Models
class CallRequest(BaseModel):
    to: str
    appointment_date: Optional[str] = None
    appointment_time: Optional[str] = None
    patient_name: Optional[str] = None
    doctor_name: Optional[str] = None
    appointment_type: Optional[str] = None

class MessageRequest(BaseModel):
    message: str
    to_phone: str

class HospitalChatRequest(BaseModel):
    message: str
    conversation_id: str
    voice_call: bool = True
    context: Dict[str, Any] = {}
    call_sid: Optional[str] = None
    caller_phone: Optional[str] = None
    category: Optional[str] = None

class CallContext:
    """Enhanced call context for hospital integration and real-time processing"""
    def __init__(self, call_sid: str, stream_sid: str = None, caller_phone: str = None):
        self.call_sid = call_sid
        self.stream_sid = stream_sid
        self.caller_phone = caller_phone
        self.conversation_id = str(uuid.uuid4())
        self.start_time = datetime.utcnow()
        self.last_activity = datetime.utcnow()
        self.messages = []
        self.current_agent = None
        self.escalation_needed = False
        self.appointment_context = {}
        self.voice_context = {}
        self.hospital_routing_active = True
        self.realtime_mode = False
        self.is_voice_call = True
        self.total_interactions = 0
        self.session_data = {}
    
    def add_message(self, role: str, content: str, metadata: dict = None):
        """Add a message to the conversation history"""
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
        """Update context fields dynamically"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.last_activity = datetime.utcnow()
    
    def get_conversation_summary(self) -> dict:
        """Get a summary of the conversation for logging/monitoring"""
        return {
            "call_sid": self.call_sid,
            "stream_sid": self.stream_sid,
            "caller_phone": self.caller_phone,
            "conversation_id": self.conversation_id,
            "start_time": self.start_time.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "duration_seconds": (datetime.utcnow() - self.start_time).total_seconds(),
            "message_count": len(self.messages),
            "total_interactions": self.total_interactions,
            "current_agent": self.current_agent,
            "escalation_needed": self.escalation_needed,
            "realtime_mode": self.realtime_mode,
            "has_appointment_context": bool(self.appointment_context),
            "has_voice_context": bool(self.voice_context)
        }
    
    def should_escalate(self) -> bool:
        """Determine if conversation should be escalated based on context"""
        escalation_triggers = [
            self.escalation_needed,
            len(self.messages) > 20,  # Very long conversation
            (datetime.utcnow() - self.start_time).total_seconds() > 1800,  # Over 30 minutes
            "emergency" in self.voice_context.get("keywords", [])
        ]
        return any(escalation_triggers)
    
    def get_hospital_context(self, category: Optional[str] = None) -> dict:
        """Get formatted context for hospital system integration with dynamic category."""
        normalized = normalize_category(category or self.session_data.get("category_hint"))
        # Confidence heuristic
        has_hint = bool(category or self.session_data.get("category_hint"))
        intent_confidence = float(self.session_data.get("intent_confidence", 0.90 if has_hint else 0.70))
        return {
            "category": normalized,
            "channel": "voice" if self.is_voice_call else "chat",
            "intent_confidence": round(intent_confidence, 2)
        }

class HospitalOrchestrator:
    """Enhanced hospital orchestrator with real-time voice integration"""
    
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        # Configure granular timeouts with improved reliability
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0,  # Increased connect timeout
                read=float(HOSPITAL_API_TIMEOUT),
                write=15.0,  # Increased write timeout
                pool=10.0,  # Increased pool timeout
            ),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
        )
    
    async def health_check(self) -> bool:
        """Check if hospital orchestrator is available with retry logic"""
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                response = await self.client.get(f"{self.base_url}/health")
                if response.status_code == 200:
                    return True
                else:
                    logger.warning(f"Health check attempt {attempt + 1} failed with status {response.status_code}")
            except Exception as e:
                logger.error(f"Hospital orchestrator health check attempt {attempt + 1} failed: {e}")
            
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
        
        return False
    
    async def route_voice_query(self, message: str, call_context: CallContext, category: Optional[str] = None) -> Dict[str, Any]:
        """Route voice query to hospital orchestrator with enhanced context and normalized category"""
        try:
            # Add message to call context
            call_context.add_message("user", message)
            
            normalized_category = normalize_category(category or call_context.session_data.get("category_hint"))
            context_payload = call_context.get_hospital_context(normalized_category)
            call_context.session_data["category_hint"] = normalized_category

            request_data = HospitalChatRequest(
                message=message,
                conversation_id=call_context.conversation_id,
                voice_call=True,
                context=context_payload,
                call_sid=call_context.call_sid,
                caller_phone=call_context.caller_phone,
                category=normalized_category
            )
            
            logger.info(f"🔄 Sending request to {self.base_url}/voice-chat with timeout {HOSPITAL_API_TIMEOUT}s")
            logger.info(f"🧭 Category: input={category} normalized={normalized_category}")
            logger.info(f"🔍 Request payload: {request_data.dict()}")
            
            response = await self.client.post(
                f"{self.base_url}/voice-chat",
                json=request_data.dict(),
                timeout=HOSPITAL_API_TIMEOUT
            )
            
            logger.info(f"✅ Response received: status={response.status_code} with response: {response.json()}")
            
            if response.status_code == 200:
                result = response.json()
                
                # Update call context with orchestrator response
                response_text = result.get("response", "I'm sorry, I couldn't process your request.")
                call_context.add_message("assistant", response_text, {
                    "agent_used": result.get("agent_used"),
                    "should_escalate": result.get("should_escalate", False)
                })
                
                call_context.update_context(
                    current_agent=result.get("agent_used"),
                    escalation_needed=result.get("should_escalate", False)
                )

                if normalized_category:
                    call_context.session_data["category_hint"] = normalized_category
                
                # Update appointment context if provided
                if result.get("appointment_context"):
                    call_context.appointment_context.update(result.get("appointment_context", {}))
                
                # Update voice context if provided
                if result.get("voice_context"):
                    call_context.voice_context.update(result.get("voice_context", {}))
                
                logger.info(f"✅ Hospital response for {call_context.call_sid}: {result.get('agent_used')} - {response_text[:100]}...")
                
                return {
                    "response": response_text,
                    "agent_used": result.get("agent_used"),
                    "should_escalate": result.get("should_escalate", False),
                    "success": True,
                    "voice_optimized": True,
                    "hospital_context": result.get("hospital_context", {}),
                    "appointment_context": result.get("appointment_context", {}),
                    "conversation_summary": call_context.get_conversation_summary()
                }
            else:
                logger.error(f"Hospital orchestrator returned status {response.status_code}")
                return self._fallback_response(call_context)
                
        except httpx.TimeoutException:
            logger.error(f"Hospital orchestrator request timed out for call {call_context.call_sid}")
            return self._fallback_response(call_context, "Our systems are experiencing high volume. Please hold while I connect you.")
        except httpx.ConnectError:
            logger.error(f"Cannot connect to hospital orchestrator for call {call_context.call_sid}")
            return self._fallback_response(call_context, "I'm having trouble connecting to our system. Let me try again.")
        except httpx.ReadTimeout:
            logger.error(f"Hospital orchestrator read timeout for call {call_context.call_sid}")
            return self._fallback_response(call_context, "The system is taking longer than usual. Please hold on.")
        except Exception as e:
            logger.error(f"Hospital orchestrator communication failed for call {call_context.call_sid}: {e}")
            return self._fallback_response(call_context)
    
    def _fallback_response(self, call_context: CallContext = None, message: str = None) -> Dict[str, Any]:
        """Fallback response when hospital system is unavailable"""
        fallback_message = message or "I'm experiencing technical difficulties. Let me transfer you to our staff."
        
        if call_context:
            call_context.add_message("assistant", fallback_message, {"agent_used": "fallback", "fallback_reason": "hospital_system_unavailable"})
            call_context.update_context(current_agent="fallback", escalation_needed=True)
        
        return {
            "response": fallback_message,
            "agent_used": "fallback",
            "should_escalate": True,
            "success": False,
            "voice_optimized": True,
            "conversation_summary": call_context.get_conversation_summary() if call_context else {}
        }
    
    async def schedule_callback(self, phone: str, appointment_data: Dict[str, Any]) -> Dict[str, Any]:
        """Schedule a callback through voice scheduler"""
        try:
            response = await self.client.post(
                f"{VOICE_SCHEDULER_URL}/schedule-callback",
                json={
                    "phone": phone,
                    "appointment_data": appointment_data,
                    "callback_type": "appointment_reminder"
                }
            )
            return response.json() if response.status_code == 200 else {"success": False}
        except Exception as e:
            logger.error(f"Failed to schedule callback: {e}")
            return {"success": False, "error": str(e)}
    
    async def close(self):
        """Close HTTP client"""
        await self.client.aclose()

# Initialize hospital orchestrator
hospital_orchestrator = HospitalOrchestrator(HOSPITAL_ORCHESTRATOR_URL)

# Connection tracking for both traditional and real-time modes
active_calls: Dict[str, CallContext] = {}
active_connections: Dict[str, CallContext] = {}

# WebSocket Middleware for logging
class WebSocketLoggerMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        try:
            if scope.get("type") == "websocket":
                client = scope.get("client")
                path = scope.get("path")
                headers = {}
                for name, value in scope.get("headers", []):
                    try:
                        headers[name.decode()] = value.decode()
                    except Exception:
                        headers[str(name)] = str(value)
                logger.debug(f"Incoming WS handshake - path={path} client={client}")
        except Exception as e:
            logger.error(f"Error in WebSocketLoggerMiddleware: {e}")
        await self.app(scope, receive, send)

# Application lifecycle management
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🏥 Starting Hospital Twilio Voice Agent with Real-time Capabilities...")
    logger.info(f"🌐 PUBLIC_URL configured as: {PUBLIC_URL}")
    
    # Wait a bit for hospital orchestrator to be ready
    await asyncio.sleep(5)
    
    # Health check hospital orchestrator with retries
    if await hospital_orchestrator.health_check():
        logger.info("✅ Hospital orchestrator is available")
    else:
        logger.warning("⚠️ Hospital orchestrator is not available - using fallback mode")
        logger.info("🔄 Will continue attempting to connect during operation")
    
    yield
    
    # Shutdown
    logger.info("🏥 Shutting down Hospital Twilio Voice Agent...")
    await hospital_orchestrator.close()

app = FastAPI(
    title="Hospital Twilio Voice Agent",
    description="Production-ready hospital voice agent with real-time capabilities",
    version="3.0.0",
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

# Wrap with WebSocket middleware
asgi_app = WebSocketLoggerMiddleware(app)

@app.api_route("/", methods=["GET", "POST"])
async def index(request: Request):
    """Handle root endpoint - redirect to incoming call handler for POST requests"""
    if request.method == "POST":
        # This is likely a Twilio webhook, redirect to incoming call handler
        logger.info("📞 Twilio webhook received at root, redirecting to incoming-call handler")
        return await incoming_call(request)
    
    # GET request - return health status
    orchestrator_healthy = await hospital_orchestrator.health_check()
    return {
        "service": "Hospital Twilio Voice Agent",
        "status": "healthy",
        "version": "3.0.0",
        "capabilities": {
            "traditional_calls": True,
            "realtime_streaming": True,
            "hospital_integration": True,
            "emergency_routing": True
        },
        "active_calls": len(active_calls),
        "active_streams": len(active_connections),
        "hospital_orchestrator_status": "healthy" if orchestrator_healthy else "unavailable",
        "public_url": PUBLIC_URL
    }

@app.get("/health")
async def health():
    """Detailed health check"""
    orchestrator_healthy = await hospital_orchestrator.health_check()
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "active_calls": len(active_calls),
        "active_streams": len(active_connections),
        "components": {
            "twilio_client": bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN),
            "hospital_orchestrator": orchestrator_healthy,
            "openai_realtime": bool(OPENAI_API_KEY),
            "voice_scheduler": True  # Add actual check in production
        }
    }

@app.get("/test-openai")
async def test_openai():
    """Test OpenAI API key validity and Realtime API access"""
    api_key = OPENAI_API_KEY
    try:
        if not api_key:
            return {"success": False, "error": "No API key configured"}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.openai.com/v1/models",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "OpenAI-Beta": "realtime=v1"
                },
                timeout=10.0
            )
            
            if response.status_code == 200:
                models = response.json()
                realtime_models = [m for m in models.get("data", []) if "realtime" in m.get("id", "")]
                return {
                    "success": True,
                    "api_key_valid": True,
                    "status_code": response.status_code,
                    "realtime_models_available": len(realtime_models),
                    "has_realtime_access": len(realtime_models) > 0
                }
            elif response.status_code == 401:
                return {"success": False, "api_key_valid": False, "error": "Invalid API key"}
            elif response.status_code == 403:
                return {"success": False, "api_key_valid": True, "error": "No Realtime API access"}
            else:
                return {"success": False, "status_code": response.status_code}
                
    except Exception as e:
        return {"success": False, "error": str(e), "key_configured": bool(api_key)}

# ===== TRADITIONAL TWILIO WEBHOOKS (TwiML) =====

@app.api_route("/incoming-call", methods=["GET", "POST"])
async def incoming_call(request: Request):
    """Handle incoming calls - supports both traditional and real-time modes"""
    logger.info("📞 Incoming call received")
    
    # Extract call information
    form_data = await request.form()
    call_sid = form_data.get("CallSid", "unknown")
    caller_phone = form_data.get("From", "unknown")
    public_url = f"https://{request.url.hostname}"
    # Check if real-time mode is available
    PUBLIC_URL = public_url
    use_realtime = bool(OPENAI_API_KEY and PUBLIC_URL)
    
    if use_realtime:
        # Use real-time streaming mode
        call_context = CallContext(call_sid, caller_phone=caller_phone)
        call_context.realtime_mode = True
        active_calls[call_sid] = call_context
        
        logger.info(f"📞 Call {call_sid} from {caller_phone} - Using real-time mode")
        logger.info(f"🌐 WebSocket URL: {PUBLIC_URL.replace('https://', 'wss://')}/media-stream")
        
        response = VoiceResponse()
        response.say(
            "Hello, thank you for calling our hospital. Please hold while I connect you with our AI assistant.",
            voice="Polly.Amy", rate="medium"
        )
        response.pause(length=1)
        
        connect = Connect()
        stream_url = f"{PUBLIC_URL.replace('https://', 'wss://')}/media-stream"
        logger.info(f"🔗 Connecting to stream: {stream_url}")
        # Create bidirectional stream - Twilio defaults to both tracks when not specified
        # We control audio direction via the "track" field in individual media messages
        connect.stream(url=stream_url)
        response.append(connect)
        
        # Log the generated TwiML for debugging
        twiml_output = str(response)
        logger.info(f"📄 Generated TwiML: {twiml_output[:500]}")
        
        return HTMLResponse(content=twiml_output, media_type="application/xml")
    
    else:
        # Fall back to traditional TwiML mode
        call_context = CallContext(call_sid, caller_phone=caller_phone)
        call_context.realtime_mode = False
        active_calls[call_sid] = call_context
        
        logger.info(f"📞 Call {call_sid} from {caller_phone} - Using traditional mode")
        
        response = VoiceResponse()
        response.say(
            "Hello, thank you for calling our hospital. I'm Sarah, your AI assistant. How can I help you today?",
            voice="Polly.Amy", rate="medium"
        )
        
        gather = Gather(
            input='speech',
            action=f"{PUBLIC_URL}/process-speech",
            method='POST',
            speech_timeout=3,
            timeout=10,
            language='en-US'
        )
        
        gather.say(
            "Please tell me how I can assist you with appointments, doctor information, or medical questions.",
            voice="Polly.Amy", rate="medium"
        )
        
        response.append(gather)
        response.redirect(f"{PUBLIC_URL}/no-input")
        
        return HTMLResponse(content=str(response), media_type="application/xml")

@app.api_route("/process-speech", methods=["POST"])
async def process_speech(request: Request):
    """Process speech input and route to hospital system"""
    form_data = await request.form()
    call_sid = form_data.get("CallSid", "unknown")
    speech_result = form_data.get("SpeechResult", "")
    
    logger.info(f"🎤 Processing speech for call {call_sid}: {speech_result}")
    
    response = VoiceResponse()
    
    if call_sid not in active_calls:
        logger.warning(f"Call context not found for {call_sid}")
        response.say("I'm sorry, there was an error. Please try calling again.")
        response.hangup()
        return HTMLResponse(content=str(response), media_type="application/xml")
    
    call_context = active_calls[call_sid]
    
    if not speech_result.strip():
        response.say("I didn't catch that. Could you please repeat?")
        response.redirect(f"{PUBLIC_URL}/incoming-call")
        return HTMLResponse(content=str(response), media_type="application/xml")
    
    # Route to hospital orchestrator
    try:
        category_hint = infer_category_from_text(speech_result) if should_auto_escalate(speech_result) else None
        if category_hint:
            call_context.session_data["category_hint"] = category_hint
        hospital_response = await hospital_orchestrator.route_voice_query(speech_result, call_context, category_hint)
        
        # Respond with hospital system result
        response.say(
            hospital_response["response"],
            voice="Polly.Amy",
            rate="medium"
        )
        
        # Check if escalation is needed
        if hospital_response.get("should_escalate") or call_context.should_escalate():
            response.say("Let me transfer you to our staff for further assistance.")
            # In production, add actual transfer logic here
            response.hangup()
        else:
            # Continue conversation
            gather = Gather(
                input='speech',
                action=f"{PUBLIC_URL}/process-speech",
                method='POST',
                speech_timeout=3,
                timeout=10,
                language='en-US'
            )
            
            gather.say(
                "Is there anything else I can help you with today?",
                voice="Polly.Amy",
                rate="medium"
            )
            
            response.append(gather)
            response.redirect(f"{PUBLIC_URL}/end-call")
        
    except Exception as e:
        logger.error(f"Error processing speech for {call_sid}: {e}")
        call_context.add_message("system", f"Speech processing error: {str(e)}", {"error_type": "speech_processing"})
        response.say("I'm experiencing technical difficulties. Let me transfer you to our staff.")
        response.hangup()
    
    return HTMLResponse(content=str(response), media_type="application/xml")

@app.api_route("/no-input", methods=["GET", "POST"])
async def no_input(request: Request):
    """Handle no input scenarios"""
    form_data = await request.form()
    call_sid = form_data.get("CallSid", "unknown")
    
    logger.info(f"⏰ No input received for call {call_sid}")
    
    response = VoiceResponse()
    response.say("I didn't hear anything. Let me transfer you to our staff.")
    # In production, add transfer logic here
    response.hangup()
    
    return HTMLResponse(content=str(response), media_type="application/xml")

@app.api_route("/end-call", methods=["GET", "POST"])
async def end_call(request: Request):
    """Handle call ending"""
    form_data = await request.form()
    call_sid = form_data.get("CallSid", "unknown")
    
    logger.info(f"📞 Ending call {call_sid}")
    
    # Clean up call context and log summary
    if call_sid in active_calls:
        call_context = active_calls[call_sid]
        final_summary = call_context.get_conversation_summary()
        logger.info(f"📊 Call ended summary for {call_sid}: "
                   f"Duration: {final_summary['duration_seconds']}s, "
                   f"Messages: {final_summary['message_count']}, "
                   f"Agent: {final_summary['current_agent']}")
        del active_calls[call_sid]
    
    response = VoiceResponse()
    response.say("Thank you for calling our hospital. Have a great day!", voice="Polly.Amy")
    response.hangup()
    
    return HTMLResponse(content=str(response), media_type="application/xml")

@app.post("/make-call")
async def make_call(call_request: CallRequest, request: Request):
    """Make an outbound call for appointments or notifications (typed version)."""
    try:
        if not TWILIO_PHONE_NUMBER:
            raise HTTPException(status_code=500, detail="Twilio phone number not configured")
        
        public_url = PUBLIC_URL or f"https://{request.url.hostname}"
        
        call = twilio_client.calls.create(
            to=call_request.to,
            from_=TWILIO_PHONE_NUMBER,
            url=f"{public_url}/outgoing-call",
            timeout=300
        )
        
        logger.info(f"📞 Outbound call initiated to {call_request.to}, SID: {call.sid}")
        
        return {
            "success": True,
            "message": "Call initiated successfully",
            "call_sid": call.sid,
            "to": call_request.to
        }
        
    except Exception as e:
        logger.error(f"Failed to make call: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to make call: {str(e)}")

@app.api_route("/outgoing-call", methods=["GET", "POST"])
async def outgoing_call(request: Request):
    """Handle outgoing calls"""
    logger.info("📞 Outgoing call webhook triggered")
    
    response = VoiceResponse()
    response.say(
        "Hello, this is Sarah calling from your hospital. Please stay on the line.",
        voice="Polly.Amy",
        rate="medium"
    )
    
    # Route to main call processing
    response.redirect(f"{PUBLIC_URL}/incoming-call")
    
    return HTMLResponse(content=str(response), media_type="application/xml")

@app.get("/call-status/{call_sid}")
async def get_call_status(call_sid: str):
    """Get status of an active call"""
    if call_sid in active_calls:
        call_context = active_calls[call_sid]
        summary = call_context.get_conversation_summary()
        return {
            **summary,
            "status": "active",
            "should_escalate": call_context.should_escalate()
        }
    else:
        return {
            "call_sid": call_sid,
            "status": "not_found"
        }

@app.get("/metrics")
async def get_metrics():
    """Get service metrics for monitoring"""
    orchestrator_healthy = await hospital_orchestrator.health_check()
    
    # Calculate call statistics
    total_calls = len(active_calls)
    realtime_calls = sum(1 for call in active_calls.values() if call.realtime_mode)
    traditional_calls = total_calls - realtime_calls
    escalated_calls = sum(1 for call in active_calls.values() if call.should_escalate())
    
    # Calculate average call duration
    avg_duration = 0
    if total_calls > 0:
        total_duration = sum((datetime.utcnow() - call.start_time).total_seconds() 
                           for call in active_calls.values())
        avg_duration = total_duration / total_calls
    
    return {
        "active_calls": total_calls,
        "active_streams": len(active_connections),
        "realtime_calls": realtime_calls,
        "traditional_calls": traditional_calls,
        "escalated_calls": escalated_calls,
        "average_call_duration_seconds": round(avg_duration, 2),
        "hospital_orchestrator_healthy": orchestrator_healthy,
        "service_version": "3.0.0",
        "timestamp": datetime.utcnow().isoformat(),
        "uptime_seconds": time.time()  # In production, track actual uptime
    }

@app.get("/conversation/{conversation_id}")
async def get_conversation_history(conversation_id: str):
    """Get detailed conversation history for a specific conversation"""
    # Find call context by conversation ID
    call_context = None
    for call in active_calls.values():
        if call.conversation_id == conversation_id:
            call_context = call
            break
    
    if not call_context:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    return {
        "conversation_id": conversation_id,
        "summary": call_context.get_conversation_summary(),
        "messages": call_context.messages,
        "hospital_context": call_context.get_hospital_context(),
        "appointment_context": call_context.appointment_context,
        "voice_context": call_context.voice_context,
        "session_data": call_context.session_data
    }

@app.get("/active-conversations")
async def get_active_conversations():
    """Get summary of all active conversations"""
    conversations = []
    for call_sid, call_context in active_calls.items():
        conversations.append({
            "call_sid": call_sid,
            "conversation_id": call_context.conversation_id,
            "summary": call_context.get_conversation_summary()
        })
    
    return {
        "total_active": len(conversations),
        "conversations": conversations,
        "timestamp": datetime.utcnow().isoformat()
    }

# ===== HOSPITAL FALLBACK SYSTEM =====

async def handle_hospital_fallback_mode(websocket: WebSocket, call_context: CallContext, stream_sid: str):
    """
    Handle voice calls using hospital system when OpenAI is unavailable
    Uses a simplified approach with timeout and transfer to human agents
    """
    logger.info(f"🏥 Starting hospital fallback mode for {call_context.call_sid}")
    
    try:
        # Brief pause to let system settle
        await asyncio.sleep(1)
        
        # Listen for incoming data but process it efficiently
        start_time = asyncio.get_event_loop().time()
        timeout_duration = 10  # Reduce timeout to 10 seconds
        audio_received = False
        last_log_time = 0
        
        logger.info("🎤 Listening for user input in fallback mode...")
        
        while True:
            try:
                # Wait for messages with shorter timeout
                message = await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
                data = json.loads(message)
                
                if data.get("event") == "media" and data.get("media", {}).get("payload"):
                    if not audio_received:
                        logger.info("🎵 Audio detected - user is speaking")
                        audio_received = True
                        call_context.add_message("user", "[VOICE_AUDIO_DETECTED]")
                    
                    # Only log occasionally to avoid spam (every 5 seconds max)
                    current_time = asyncio.get_event_loop().time()
                    if current_time - last_log_time > 5:
                        logger.debug("🎤 Processing user audio...")  # Changed to debug to reduce logs
                        last_log_time = current_time
                    
                elif data.get("event") == "stop":
                    logger.info("📡 Media stream stopped by user")
                    break
                    
            except asyncio.TimeoutError:
                # No data received, check if we should timeout
                current_time = asyncio.get_event_loop().time()
                if current_time - start_time > timeout_duration:
                    logger.info("⏰ Fallback timeout reached - connecting to hospital system")
                    
                    # Route to hospital system with a general query
                    try:
                        user_message = "Hello, I need assistance with hospital services" if audio_received else "Caller connected but no clear speech detected"
                        
                        category_hint = "general"
                        call_context.session_data["category_hint"] = category_hint
                        
                        # Get hospital response (may take time - up to 60s based on logs)
                        # No keepalive needed here since this is fallback mode without OpenAI WebSocket
                        hospital_response = await hospital_orchestrator.route_voice_query(
                            user_message, 
                            call_context,
                            category_hint
                        )
                        
                        response_text = hospital_response.get('response', 'Let me transfer you to our staff for assistance.')
                        logger.info(f"🏥 Hospital response: {response_text[:100]}...")
                        
                        # Send the response back through Twilio (this would need TwiML redirect in practice)
                        logger.info("📞 Transferring call to hospital staff...")
                        
                    except Exception as e:
                        logger.error(f"❌ Hospital system error: {e}")
                        logger.info("📞 Transferring directly to staff...")
                    
                    break
                    
            except Exception as e:
                logger.error(f"❌ Error processing message in fallback: {e}")
                break
                
    except Exception as e:
        logger.error(f"❌ Error in fallback mode: {e}")
    finally:
        # Cleanup
        if call_context.call_sid in active_calls:
            del active_calls[call_context.call_sid]
        if stream_sid in active_connections:
            del active_connections[stream_sid]
        logger.info(f"✅ Fallback mode cleanup completed for {call_context.call_sid}")

# ===== REAL-TIME WEBSOCKET STREAMING =====

@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    """Enhanced WebSocket handler with hospital system integration"""
    client_host = websocket.client.host if websocket.client else "unknown"
    logger.info(f"🔗 WebSocket connection attempt from {client_host}")
    
    try:
        await websocket.accept()
        logger.info(f"✅ WebSocket connection accepted from {client_host}")
    except Exception as e:
        logger.error(f"❌ Failed to accept WebSocket connection from {client_host}: {e}")
        return

    openai_ws = None
    stream_sid = None
    call_context = None

    try:
        # Handle Twilio WebSocket flow
        logger.info("Waiting for Twilio WebSocket messages...")
        first_message = await websocket.receive_text()
        first_data = json.loads(first_message)
        
        if first_data.get("event") == "connected":
            logger.info("Received 'connected' event, waiting for 'start' event...")
            start_message = await websocket.receive_text()
            start_data = json.loads(start_message)
        elif first_data.get("event") == "start":
            start_data = first_data
        else:
            logger.error(f"Unexpected first event: {first_data.get('event')}")
            await websocket.close()
            return

        if start_data.get("event") != "start":
            logger.error(f"Expected 'start' event, got: {start_data.get('event')}")
            await websocket.close()
            return

        stream_sid = start_data["start"]["streamSid"]
        call_sid = start_data["start"].get("callSid", stream_sid)
        
        logger.info(f"✅ Stream started: {stream_sid} for call: {call_sid}")
        
        # Create or get call context
        if call_sid in active_calls:
            call_context = active_calls[call_sid]
            call_context.stream_sid = stream_sid
            call_context.update_context(realtime_mode=True)
            logger.info(f"🔄 Updated existing call context for {call_sid}")
        else:
            call_context = CallContext(call_sid, stream_sid)
            call_context.update_context(realtime_mode=True)
            active_calls[call_sid] = call_context
            logger.info(f"🆕 Created new call context for {call_sid}")
        
        active_connections[stream_sid] = call_context

        # Log initial context
        logger.info(f"📊 Call context summary: {call_context.get_conversation_summary()}")

        # Connect to OpenAI Realtime API
        logger.info("Connecting to OpenAI Realtime API...")
        
        if not OPENAI_API_KEY:
            logger.error("❌ OPENAI_API_KEY not found - falling back to hospital system")
            await handle_hospital_fallback_mode(websocket, call_context, stream_sid)
            return

        try:
            openai_ws = await websockets.connect(
                "wss://api.openai.com/v1/realtime?model=gpt-realtime-2025-08-28",
                additional_headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "OpenAI-Beta": "realtime=v1"
                },
                ping_interval=20,  # Send ping every 20s to keep connection alive
                ping_timeout=30,   # Increased timeout for slow responses
                close_timeout=20,
                max_size=2*1024*1024  # 2MB for larger responses
            )
            logger.info("✅ Connected to OpenAI Realtime API")
        except Exception as e:
            logger.error(f"❌ Failed to connect to OpenAI: {e}")
            logger.info("🔄 Falling back to hospital system mode...")
            await handle_hospital_fallback_mode(websocket, call_context, stream_sid)
            return

        # Configure OpenAI session with hospital context
        session_update = {
            "type": "session.update",
            "session": {
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.65,
                    "prefix_padding_ms": 500,
                    "silence_duration_ms": 1200
                },
                "input_audio_format": "g711_ulaw",
                "output_audio_format": "g711_ulaw",
                "voice": "marin",
                "instructions": HOSPITAL_INSTRUCTIONS,
                "modalities": ["text", "audio"],
                "temperature": 0.6,
                "max_response_output_tokens": 500,
                "tools": [
                    {
                        "type": "function",
                        "name": "route_to_hospital_system",
                        "description": "Route complex medical queries, appointments, or specialized requests to the hospital system",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string", "description": "The user's request to route to hospital system"},
                                "category": {"type": "string", "enum": ["appointment", "medical_question", "doctor_info", "emergency", "general"], "description": "Category of the request"}
                            },
                            "required": ["query", "category"]
                        }
                    },
                    {
                        "type": "function",
                        "name": "end_call",
                        "description": "End the phone call when conversation has naturally concluded",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "goodbye_message": {"type": "string", "description": "Final goodbye message"}
                            },
                            "required": ["goodbye_message"]
                        }
                    }
                ]
            }
        }
        
        await openai_ws.send(json.dumps(session_update))
        logger.info("✅ Session configuration sent to OpenAI")

        # Send initial greeting
        greeting_item = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "assistant",
                "content": [{
                    "type": "text", 
                    "text": "Hi! I'm Sarah, your hospital AI assistant. I can help you with appointments, doctor information, medical questions, and more. How can I assist you today?"
                }]
            }
        }
        await openai_ws.send(json.dumps(greeting_item))
        
        initial_response = {"type": "response.create", "response": {"modalities": ["text", "audio"]}}
        await openai_ws.send(json.dumps(initial_response))

        # Initialize conversation state
        latest_media_timestamp = 0
        active_response_id = None
        mark_queue = []
        last_response_end_time = 0.0
        pending_cancel_task = None
        speech_started_flag = False
        call_start_time = time.time()

        async def ensure_response_ready(wait_timeout: float = 4.0, cancel_timeout: float = 2.0) -> bool:
            """Ensure there is no active response before triggering a new one."""
            nonlocal active_response_id

            if not active_response_id:
                return True

            start = time.time()
            while active_response_id and (time.time() - start) < wait_timeout:
                await asyncio.sleep(0.05)

            if not active_response_id:
                return True

            cancel_payload = {
                "type": "response.cancel",
                "response_id": active_response_id
            }

            try:
                await openai_ws.send(json.dumps(cancel_payload))
                logger.warning("⚠️ Forcing cancel of lingering response before creating a new one")
            except Exception as cancel_error:
                logger.error(f"Unable to cancel active response: {cancel_error}")
                return False

            start = time.time()
            while active_response_id and (time.time() - start) < cancel_timeout:
                await asyncio.sleep(0.05)

            return not active_response_id

        async def check_call_duration():
            """Monitor call duration"""
            while True:
                await asyncio.sleep(60)
                call_duration = time.time() - call_start_time
                if call_duration > 1800:  # 30 minutes
                    logger.warning(f"Call {stream_sid}: Maximum duration reached, terminating")
                    await websocket.close(code=1000, reason="Maximum call duration reached")
                    break

        async def receive_from_twilio():
            """Handle incoming audio from Twilio"""
            nonlocal latest_media_timestamp, mark_queue
            try:
                async for message in websocket.iter_text():
                    if not message:
                        continue
                    
                    data = json.loads(message)
                    event_type = data.get("event")
                    
                    if event_type == "media":
                        latest_media_timestamp = int(data["media"]["timestamp"])
                        audio_append = {
                            "type": "input_audio_buffer.append", 
                            "audio": data["media"]["payload"]
                        }
                        await openai_ws.send(json.dumps(audio_append))
                        
                    elif event_type == "mark":
                        if mark_queue:
                            mark_queue.pop(0)
                            
                    elif event_type == "stop":
                        logger.info(f"Stream {stream_sid} stopped")
                        break
                        
            except websockets.exceptions.ConnectionClosed:
                logger.info(f"Twilio connection closed: {stream_sid}")
            except Exception as e:
                logger.error(f"Error receiving from Twilio: {e}")

        async def send_to_twilio():
            """Handle outgoing audio to Twilio and function calls"""
            nonlocal active_response_id, mark_queue, pending_cancel_task, speech_started_flag, last_response_end_time
            
            try:
                async for openai_message in openai_ws:
                    response_data = json.loads(openai_message)
                    response_type = response_data.get("type")
                    
                    if response_type == "response.audio.delta" and "delta" in response_data:
                        try:
                            audio_payload = base64.b64encode(base64.b64decode(response_data["delta"])).decode("utf-8")
                            audio_delta = {
                                "event": "media",
                                "streamSid": stream_sid,
                                "media": {"payload": audio_payload}
                            }
                            await websocket.send_json(audio_delta)
                            
                            resp_id = response_data.get("response_id")
                            if resp_id:
                                active_response_id = resp_id
                                
                        except Exception as e:
                            logger.error(f"Error processing audio delta: {e}")
                    
                    elif response_type == "response.audio.done":
                        logger.info(f"🔊 Audio response completed: {stream_sid}")
                        last_response_end_time = time.time()
                        
                        try:
                            await asyncio.sleep(0.25)
                            mark_event = {
                                "event": "mark",
                                "streamSid": stream_sid,
                                "mark": {"name": "audioComplete"}
                            }
                            await websocket.send_json(mark_event)
                            mark_queue.append("audioComplete")
                            active_response_id = None
                        except Exception as e:
                            logger.error(f"Error sending audio completion mark: {e}")

                    elif response_type == "response.input_text.delta":
                        delta = response_data.get("delta", "")
                        if delta:
                            current_buffer = call_context.session_data.get("transcript_buffer", "")
                            call_context.session_data["transcript_buffer"] = current_buffer + delta

                    elif response_type == "response.input_text.done":
                        text_value = response_data.get("text")
                        if not text_value:
                            text_value = call_context.session_data.get("transcript_buffer", "")
                        if text_value:
                            call_context.session_data["last_user_transcript"] = text_value.strip()
                        call_context.session_data.pop("transcript_buffer", None)

                    elif response_type == "conversation.item.created":
                        item = response_data.get("item", {})
                        if item.get("type") == "message" and item.get("role") == "user":
                            contents = item.get("content") or []
                            transcript_text = ""
                            for content in contents:
                                if isinstance(content, dict) and content.get("type") in {"input_text", "text"}:
                                    transcript_text += content.get("text", "")
                            if transcript_text.strip():
                                call_context.session_data["last_user_transcript"] = transcript_text.strip()
                    
                    elif response_type == "input_audio_buffer.speech_started":
                        logger.info(f"🎤 User started speaking: {stream_sid}")
                        speech_started_flag = True
                        snapshot_media_ts = latest_media_timestamp
                        
                        if pending_cancel_task and not pending_cancel_task.done():
                            pending_cancel_task.cancel()
                        
                        async def _debounced_cancel():
                            try:
                                await asyncio.sleep(0.25)
                                if speech_started_flag and latest_media_timestamp != snapshot_media_ts:
                                    if active_response_id:
                                        cancel_payload = {
                                            "type": "response.cancel",
                                            "response_id": active_response_id
                                        }
                                        await openai_ws.send(json.dumps(cancel_payload))
                                        logger.info("❌ Debounced cancel sent")
                                    else:
                                        logger.debug("Debounced cancel skipped; no active response")
                            except asyncio.CancelledError:
                                return
                            except Exception as e:
                                logger.error(f"Error sending debounced cancel: {e}")
                        
                        pending_cancel_task = asyncio.create_task(_debounced_cancel())
                    
                    elif response_type == "input_audio_buffer.speech_stopped":
                        logger.info(f"🛑 User stopped speaking: {stream_sid}")
                        speech_started_flag = False
                        
                        if pending_cancel_task and not pending_cancel_task.done():
                            pending_cancel_task.cancel()
                        auto_escalated = False
                        transcript = call_context.session_data.pop("last_user_transcript", None)

                        if transcript and transcript.strip():
                            # Prevent duplicate escalations for unchanged transcripts or rapid repeats
                            last_processed = call_context.session_data.get("last_processed_transcript")
                            last_tool_ts = call_context.session_data.get("last_tool_ts", 0)
                            cooldown_elapsed = (time.time() - last_tool_ts) > TRANSCRIPT_COOLDOWN_SECONDS

                            if transcript != last_processed or cooldown_elapsed:
                                if should_auto_escalate(transcript):
                                    category_hint = infer_category_from_text(transcript)
                                    logger.info(
                                        f"🧾 Transcript captured ({category_hint}): {transcript}"
                                    )
                                    call_context.session_data["category_hint"] = category_hint
                                    try:
                                        # Create keepalive task to prevent OpenAI timeout during long hospital API call
                                        async def keepalive_pinger():
                                            """Send periodic pings to keep OpenAI connection alive"""
                                            try:
                                                while True:
                                                    await asyncio.sleep(5)  # Ping every 5 seconds
                                                    await openai_ws.ping()
                                                    logger.debug("🏓 Sent keepalive ping to OpenAI during hospital call")
                                            except asyncio.CancelledError:
                                                pass  # Expected when we cancel the task
                                            except Exception as e:
                                                logger.warning(f"Keepalive ping failed: {e}")
                                        
                                        # Start keepalive task
                                        keepalive_task = asyncio.create_task(keepalive_pinger())
                                        
                                        try:
                                            # Get hospital response (may take time - up to 60s based on logs)
                                            hospital_response = await hospital_orchestrator.route_voice_query(
                                                transcript,
                                                call_context,
                                                category_hint,
                                            )
                                        finally:
                                            # Always cancel keepalive when done
                                            keepalive_task.cancel()
                                            try:
                                                await keepalive_task
                                            except asyncio.CancelledError:
                                                pass
                                        
                                        call_context.session_data["last_processed_transcript"] = transcript
                                        call_context.session_data["last_tool_ts"] = time.time()
                                        auto_escalated = True

                                        await inject_assistant_reply(
                                            openai_ws,
                                            hospital_response.get("response", ""),
                                            instructions="Deliver the hospital system response based on the caller's latest question.",
                                            ensure_ready_callback=ensure_response_ready
                                        )

                                        logger.info(
                                            f"📨 Direct hospital escalation succeeded: agent={hospital_response.get('agent_used')}"
                                        )
                                    except Exception as escalation_error:
                                        logger.error(f"Direct hospital escalation failed: {escalation_error}")
                                else:
                                    logger.debug("Transcript did not match escalation keywords; deferring to model.")
                            else:
                                logger.debug("Duplicate transcript detected; skipping immediate escalation.")

                        # Heuristic escalation nudge remains as fallback if no auto escalation occurred
                        if HOSPITAL_AUTO_ESCALATION and not auto_escalated:
                            try:
                                # Wait longer to ensure previous response is truly done
                                await asyncio.sleep(0.5)
                                
                                # Only proceed if no active response
                                if not active_response_id:
                                    escalation_item = {
                                        "type": "conversation.item.create",
                                        "item": {
                                            "type": "message",
                                            "role": "system",
                                            "content": [{
                                                "type": "input_text",
                                                "text": build_escalation_instruction()
                                            }]
                                        }
                                    }
                                    await openai_ws.send(json.dumps(escalation_item))
                                    
                                    # Wait and verify response is ready with longer timeout
                                    if await ensure_response_ready(wait_timeout=6.0):
                                        escalation_response_trigger = {
                                            "type": "response.create",
                                            "response": {"modalities": ["text", "audio"], "instructions": "Process the last caller utterance now."}
                                        }
                                        await openai_ws.send(json.dumps(escalation_response_trigger))
                                        logger.info("🧭 Escalation heuristic instruction injected to encourage hospital routing if needed")
                                    else:
                                        logger.debug("Skipped heuristic response prompt because previous response is still active")
                                else:
                                    logger.debug("Skipped heuristic escalation because active_response_id is set")
                            except Exception as e:
                                logger.error(f"Failed to inject escalation heuristic: {e}")
                    
                    elif response_type == "response.output_item.done":
                        item = response_data.get("item", {})
                        if item.get("type") == "function_call":
                            function_name = item.get("name")
                            arguments = json.loads(item.get("arguments", "{}"))
                            call_id = item.get("call_id")
                            
                            if function_name == "route_to_hospital_system":
                                # Route to hospital orchestrator
                                query = arguments.get("query", "")
                                category = arguments.get("category", "general")
                                call_context.session_data["category_hint"] = category
                                
                                logger.info(f"🏥 Routing to hospital system: {category} - {query}")
                                
                                try:
                                    # Create keepalive task to prevent OpenAI timeout during long hospital API call
                                    async def keepalive_pinger():
                                        """Send periodic pings to keep OpenAI connection alive"""
                                        try:
                                            while True:
                                                await asyncio.sleep(5)  # Ping every 5 seconds
                                                await openai_ws.ping()
                                                logger.debug("🏓 Sent keepalive ping to OpenAI during hospital call")
                                        except asyncio.CancelledError:
                                            pass  # Expected when we cancel the task
                                        except Exception as e:
                                            logger.warning(f"Keepalive ping failed: {e}")
                                    
                                    # Start keepalive task
                                    keepalive_task = asyncio.create_task(keepalive_pinger())
                                    
                                    try:
                                        # Get hospital response (may take time - up to 60s based on logs)
                                        hospital_response = await hospital_orchestrator.route_voice_query(query, call_context, category)
                                    finally:
                                        # Always cancel keepalive when done
                                        keepalive_task.cancel()
                                        try:
                                            await keepalive_task
                                        except asyncio.CancelledError:
                                            pass
                                    
                                    call_context.session_data["last_tool_ts"] = time.time()
                                    call_context.session_data["last_processed_transcript"] = query
                                    call_context.session_data.pop("last_user_transcript", None)
                                    
                                    response_text = hospital_response.get("response", "")
                                    
                                    # Send function output immediately to prevent timeout
                                    function_output = {
                                        "type": "conversation.item.create",
                                        "item": {
                                            "type": "function_call_output",
                                            "call_id": call_id,
                                            "output": json.dumps({
                                                "success": hospital_response.get("success", False),
                                                "response": response_text,
                                                "agent_used": hospital_response.get("agent_used"),
                                                "should_escalate": hospital_response.get("should_escalate", False),
                                                "conversation_summary": hospital_response.get("conversation_summary", {})
                                            })
                                        }
                                    }
                                    await openai_ws.send(json.dumps(function_output))
                                    
                                    # Log successful routing
                                    logger.info(
                                        f"✅ Hospital routing completed: agent={hospital_response.get('agent_used')} "
                                        f"escalate={hospital_response.get('should_escalate', False)}"
                                    )

                                    # Immediately trigger response to speak the result
                                    await asyncio.sleep(0.1)
                                    response_create = {
                                        "type": "response.create",
                                        "response": {
                                            "modalities": ["text", "audio"],
                                            "instructions": f"Say this to the caller verbatim: {response_text}"
                                        }
                                    }
                                    await openai_ws.send(json.dumps(response_create))
                                    logger.info("🎙️ Response synthesis triggered for hospital result")
                                    
                                except Exception as e:
                                    logger.error(f"Hospital routing error for {stream_sid}: {e}")
                                    call_context.add_message("system", f"Hospital routing failed: {str(e)}", {
                                        "error_type": "hospital_routing_failure",
                                        "query": query,
                                        "category": category
                                    })
                                    
                                    error_output = {
                                        "type": "conversation.item.create",
                                        "item": {
                                            "type": "function_call_output",
                                            "call_id": call_id,
                                            "output": json.dumps({
                                                "success": False,
                                                "error": "Hospital system temporarily unavailable. Connecting you to our staff."
                                            })
                                        }
                                    }
                                    await openai_ws.send(json.dumps(error_output))
                            
                            elif function_name == "end_call":
                                goodbye_message = arguments.get("goodbye_message", "Thank you for calling. Goodbye!")
                                logger.info("🔚 End call function triggered by AI")
                                
                                function_output = {
                                    "type": "conversation.item.create",
                                    "item": {
                                        "type": "function_call_output",
                                        "call_id": call_id,
                                        "output": "Call termination initiated"
                                    }
                                }
                                await openai_ws.send(json.dumps(function_output))
                                await terminate_twilio_call(stream_sid, goodbye_message)
                    
                    elif response_type == "response.text.done":
                        response_text = response_data.get("text", "")
                        logger.info(f"📝 AI Response: {response_text}")
                    
                    elif response_type == "response.canceled":
                        logger.info("🚫 OpenAI confirmed response cancellation")
                        active_response_id = None

                    elif response_type == "error":
                        error_code = response_data.get("error", {}).get("code", "")
                        if error_code == "conversation_already_has_active_response":
                            # This is expected during concurrent operations, just log as debug
                            logger.debug(f"OpenAI busy: {response_data.get('error', {}).get('message', 'Active response in progress')}")
                        else:
                            logger.error(f"OpenAI error: {response_data}")
                    
                    elif response_type in ["session.created", "session.updated"]:
                        logger.info(f"✅ OpenAI session confirmed: {response_type}")
                        
            except websockets.exceptions.ConnectionClosed:
                logger.info(f"OpenAI connection closed: {stream_sid}")
            except Exception as e:
                logger.error(f"Error sending to Twilio: {e}")

        # Start processing
        logger.info(f"✅ Starting real-time processing for {stream_sid}")
        await asyncio.gather(
            receive_from_twilio(),
            send_to_twilio(),
            check_call_duration(),
            return_exceptions=True
        )

    except Exception as e:
        logger.error(f"WebSocket error for {stream_sid}: {e}")
    finally:
        # Cleanup
        if openai_ws:
            try:
                await openai_ws.close()
            except Exception:
                pass
        
        if stream_sid and stream_sid in active_connections:
            del active_connections[stream_sid]
        
        if call_context and call_context.call_sid in active_calls:
            # Log final conversation summary before cleanup
            final_summary = call_context.get_conversation_summary()
            logger.info(f"📊 Final conversation summary for {call_context.call_sid}: "
                       f"Duration: {final_summary['duration_seconds']}s, "
                       f"Messages: {final_summary['message_count']}, "
                       f"Agent: {final_summary['current_agent']}, "
                       f"Escalated: {final_summary['escalation_needed']}")
            
            del active_calls[call_context.call_sid]
        
        logger.info(f"✅ Cleanup completed for {stream_sid}")

async def terminate_twilio_call(stream_sid: str, goodbye_message: str = "Thank you for calling. Goodbye!"):
    """Terminate the Twilio call by redirecting to hangup endpoint"""
    try:
        calls = twilio_client.calls.list(status='in-progress', limit=50)
        logger.info(f"🔍 Looking for active calls to terminate for stream {stream_sid}")
        
        if len(calls) > 0:
            for call in calls:
                logger.info(f"📋 Terminating call: SID={call.sid}")
                from urllib.parse import quote
                encoded_message = quote(goodbye_message)
                hangup_url = f"{PUBLIC_URL}/hangup?message={encoded_message}"
                twilio_client.calls(call.sid).update(url=hangup_url, method='POST')
                logger.info(f"✅ Redirected call {call.sid} to hangup endpoint")
                return True
                
        logger.warning("⚠️ No active calls found to terminate")
        return False
    except Exception as e:
        logger.error(f"❌ Error terminating Twilio call: {e}")
        return False

@app.api_route("/hangup", methods=["GET", "POST"])
async def hangup_call(request: Request):
    """TwiML endpoint to properly hang up calls"""
    try:
        goodbye_message = request.query_params.get("message", "Thank you for calling. Goodbye!")
        logger.info(f"🔚 Hangup endpoint called with message: {goodbye_message}")
        
        response = VoiceResponse()
        response.say(goodbye_message, voice='Polly.Amy')
        response.hangup()
        
        return Response(content=str(response), media_type="application/xml")
    except Exception as e:
        logger.error(f"❌ Error in hangup endpoint: {e}")
        response = VoiceResponse()
        response.hangup()
        return Response(content=str(response), media_type="application/xml")

# ===== OUTBOUND SMS =====

@app.post("/send-sms")
async def send_sms(request: dict):
    """Send SMS notification"""
    try:
        to_number = request.get("to_number")
        message = request.get("message")
        
        if not to_number or not message:
            raise HTTPException(status_code=400, detail="to_number and message are required")
        
        sms = twilio_client.messages.create(
            body=message,
            from_=TWILIO_PHONE_NUMBER,
            to=to_number
        )
        
        logger.info(f"📱 SMS sent: {sms.sid} to {to_number}")
        return {"success": True, "message_sid": sms.sid}
        
    except Exception as e:
        logger.error(f"Error sending SMS: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    logger.info(f"Starting Hospital Twilio Voice Agent on port {PORT}")
    uvicorn.run(
        "production_twilio_agent:app",
        host="0.0.0.0",
        port=PORT,
        log_level="info",
        reload=False
    )