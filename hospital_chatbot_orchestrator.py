"""
Hospital AI Chatbot Orchestrator
Integrates appointment agent and RAG agent using LangGraph for comprehensive hospital services
"""

from typing import Dict, Any, List, Optional, TypedDict, Annotated
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from chatbot_config import load_chatbot_config, AGENT_ROUTING_PATTERNS
import json
import uuid
import operator
import sqlite3
import os
from datetime import datetime

APPOINTMENT_INTENT_KEYWORDS = {
    "appointment": [
        "appointment id",
        "cancel",
        "reschedule",
        "schedule",
        "book",
        "slot",
        "time",
        "doctor id",
        "appointment number",
        "follow up",
        "follow-up"
    ]
}

# Load environment variables
load_dotenv()

# State Management
class HospitalChatbotState(TypedDict):
    messages: Annotated[List[BaseMessage], operator.add]
    current_agent: Optional[str]
    agent_used: Optional[str]  # Track which agent handled the request
    user_context: Annotated[Dict[str, Any], operator.or_]
    appointment_context: Annotated[Dict[str, Any], operator.or_]
    rag_context: Annotated[Dict[str, Any], operator.or_]
    voice_context: Annotated[Dict[str, Any], operator.or_]  # Voice call context
    conversation_id: str
    trace_id: str
    escalation_needed: bool
    safety_flags: Annotated[List[str], operator.add]
    is_voice_call: bool  # Flag to indicate if this is a voice interaction
    category_hint: Optional[str]

# Initialize LLM
llm = ChatOpenAI(
    model="gpt-5",
    temperature=0.6,
    max_tokens=4096
)

# Prompts for different agents
SUPERVISOR_PROMPT = """You are a hospital chatbot supervisor that routes user requests to the appropriate specialized agent.

AVAILABLE AGENTS:
1. doctor_info_agent: For questions about doctors, specialties, medical information, hospital services
2. appointment_agent: For booking, rescheduling, canceling, or checking appointments
3. general_health_agent: For general health questions, symptom guidance, health advice
4. voice_communications_agent: For voice call related requests, scheduling calls, reminders
5. emergency_agent: For handling emergency situations and escalations

ROUTING RULES:
- Questions about specific doctors, specialties, or medical expertise → doctor_info_agent
- "book", "schedule", "appointment", "available slots", "see doctor" → appointment_agent  
- "reschedule", "cancel", "change appointment", "my appointment" → appointment_agent
- "call me back", "schedule a call", "voice reminder", "phone call", "callback" → voice_communications_agent
- General health questions, symptoms, medical advice → general_health_agent
- Emergency keywords (chest pain, difficulty breathing, severe bleeding, emergency) → emergency_agent
- Unclear requests → ask for clarification

VOICE CALL HANDLING:
- If this is a voice call interaction (indicated by [VOICE_CALL] prefix), adapt responses for speech
- Keep voice responses concise and conversational
- Avoid complex formatting or lengthy explanations
- Use natural speech patterns and confirmations
- For voice appointments: guide step-by-step, confirm each detail
- For voice emergencies: immediate escalation with clear instructions

SPECIAL VOICE ROUTING:
- Voice appointment requests: always route to appointment_agent (they handle voice context best)
- Voice doctor inquiries: route to doctor_info_agent but expect voice-optimized responses
- Voice callback/reminder requests: route to voice_communications_agent
- Voice emergencies: immediate emergency_agent routing with highest priority

Current conversation context: {context}
User message: {user_message}

Analyze the request and respond with ONLY the agent name: doctor_info_agent, appointment_agent, voice_communications_agent, general_health_agent, emergency_agent, or "clarification_needed"."""

DOCTOR_INFO_PROMPT = """You are a hospital information specialist with access to comprehensive doctor profiles and medical information.

Your role:
- Help users find the right doctor for their medical needs
- Provide detailed doctor profiles, specialties, and experience
- Answer questions about hospital services and medical procedures
- Recommend appropriate specialists based on symptoms or conditions

Guidelines:
- Always search the knowledge base first for doctor information
- Provide complete doctor profiles including experience, languages, and specialties
- Suggest 2-3 relevant doctors when possible
- Include availability hints if possible
- Be empathetic and professional
- Never provide specific medical diagnoses

User request: {user_message}
Context: {context}"""

APPOINTMENT_PROMPT = """You are an appointment scheduling specialist for the hospital.

Your capabilities:
- Search for doctors by specialty, name, or other criteria
- Check doctor availability and available time slots
- Book new appointments with patient details
- Reschedule existing appointments
- Cancel appointments when requested
- Provide appointment confirmations and details

Guidelines:
- Always confirm details before booking appointments
- Check doctor availability before suggesting slots
- Collect necessary patient information (name, contact, reason for visit)
- Explain cancellation policies when relevant
- Provide clear confirmation details
- Handle rescheduling requests professionally

User request: {user_message}
Context: {context}"""

GENERAL_HEALTH_PROMPT = """You are a health information specialist providing general medical guidance.

Your role:
- Answer general health questions and provide health education
- Offer guidance on symptoms and when to seek medical care
- Provide information about medical procedures and conditions
- Direct users to appropriate specialists when needed

Important guidelines:
- Never provide specific medical diagnoses
- Always recommend consulting healthcare professionals for serious concerns
- Provide educational information based on reliable medical sources
- Suggest when immediate medical attention may be needed
- Be supportive and empathetic

User request: {user_message}
Context: {context}"""

EMERGENCY_PROMPT = """You are an emergency response specialist for critical situations.

Handle:
- Medical emergencies (chest pain, difficulty breathing, severe bleeding)
- Urgent care situations requiring immediate attention
- Safety concerns and escalations
- Crisis situations requiring human intervention

Actions:
- Provide immediate emergency guidance
- Direct to emergency services when appropriate
- Escalate to human operators for critical situations
- Ensure patient safety is the top priority

User request: {user_message}
Context: {context}"""

class SupervisorAgent:
    """Routes user requests to appropriate specialized agents"""
    
    def __init__(self):
        self.llm = llm
        # Load configurable emergency keywords
        try:
            self.config = load_chatbot_config()
            self.emergency_keywords = [k.lower() for k in getattr(self.config, "emergency_keywords", [])]
        except Exception:
            # Safe fallback
            self.config = None
            self.emergency_keywords = [
                "chest pain", "difficulty breathing", "severe bleeding",
                "heart attack", "stroke", "unconscious", "emergency",
                "can't breathe", "severe pain", "bleeding heavily",
            ]
    
    def __call__(self, state: HospitalChatbotState) -> Dict[str, Any]:
        user_message = state["messages"][-1].content if state["messages"] else ""
        context = {
            "user_context": state.get("user_context", {}),
            "appointment_context": state.get("appointment_context", {}),
            "conversation_history": [msg.content for msg in state.get("messages", [])[-5:]]
        }

        category_hint = (state.get("category_hint") or "").strip().lower() if state.get("category_hint") else None
        if category_hint:
            hint_map = {
                "appointment": "appointment_agent",
                "doctor_info": "doctor_info_agent",
                "medical_question": "general_health_agent",
                "general": "general_health_agent",
                "emergency": "emergency_agent"
            }
            mapped_agent = hint_map.get(category_hint)
            if mapped_agent:
                return {"current_agent": mapped_agent, "messages": []}
        
        # Safety-first: pre-route emergency detection (but avoid false positives)
        try:
            lm = user_message.lower()
            
            # Check for emergency keywords but avoid false positives for follow-ups
            emergency_triggered = False
            for keyword in self.emergency_keywords:
                if keyword in lm:
                    # Check if it's likely a follow-up or non-acute mention
                    non_acute_indicators = [
                        "follow up", "follow-up", "history of", "previous", 
                        "ruled out", "past", "old", "chronic", "appointment for",
                        "check up", "routine", "schedule", "book"
                    ]
                    
                    # If it contains non-acute indicators, don't escalate to emergency
                    if not any(indicator in lm for indicator in non_acute_indicators):
                        emergency_triggered = True
                        break
            
            if emergency_triggered:
                return {"current_agent": "emergency_agent", "messages": []}
        except Exception:
            pass
        
        # Heuristic routing using regex patterns as a robust fallback
        try:
            import re
            lm = user_message or ""
            for agent, patterns in AGENT_ROUTING_PATTERNS.items():
                for pat in patterns:
                    if re.search(pat, lm):
                        return {"current_agent": agent, "messages": []}
        except Exception:
            pass

        prompt = SUPERVISOR_PROMPT.format(
            context=json.dumps(context, indent=2),
            user_message=user_message
        )
        
        response = self.llm.invoke([SystemMessage(content=prompt)])
        agent_choice = response.content.strip().lower()
        
        # Route to appropriate agent
        if "doctor_info" in agent_choice:
            next_agent = "doctor_info_agent"
        elif "appointment" in agent_choice:
            next_agent = "appointment_agent"
        elif "general_health" in agent_choice:
            next_agent = "general_health_agent"
        elif "emergency" in agent_choice:
            next_agent = "emergency_agent"
        elif "clarification" in agent_choice:
            next_agent = "clarification"
        else:
            next_agent = "general_health_agent"  # default
        
        return {
            "current_agent": next_agent,
            # Preserve conversation history; don't inject supervisor message
            "messages": []
        }

class DoctorInfoAgent:
    """Handles doctor search and medical information using RAG"""
    
    def __init__(self):
        self.llm = llm
        self._setup_rag()
    
    def _needs_appointment_handoff(self, message: str, state: HospitalChatbotState) -> bool:
        """Detect if the query should be handled by the appointment agent instead."""
        if not message:
            return False

        lower_message = message.lower()
        if state.get("agent_used") == "appointment_agent":
            for keyword in APPOINTMENT_INTENT_KEYWORDS["appointment"]:
                if keyword in lower_message:
                    return True
        appointment_context = state.get("appointment_context", {})
        if appointment_context.get("last_action") in {"appointment_request", "cancellation_pending"}:
            for keyword in APPOINTMENT_INTENT_KEYWORDS["appointment"]:
                if keyword in lower_message:
                    return True
        critical_terms = ["cancel", "reschedule", "appointment id", "appointment number"]
        return any(term in lower_message for term in critical_terms)

    def _setup_rag(self):
        """Initialize RAG components using FAISS"""
        try:
            from faiss_rag_integration import FAISSRAGIntegration
            
            self.faiss_rag = FAISSRAGIntegration()
            
            if self.faiss_rag.available:
                print("✅ FAISS RAG components initialized successfully")
            else:
                print("⚠️ FAISS RAG system not available - check if index exists")
                
        except Exception as e:
            print(f"⚠️ RAG initialization failed: {e}")
            self.faiss_rag = None
    
    def __call__(self, state: HospitalChatbotState) -> Dict[str, Any]:
        user_message = state["messages"][-1].content if state["messages"] else ""
        context = state.get("user_context", {})
        
        try:
            if self._needs_appointment_handoff(user_message, state):
                handoff_context = {
                    **state.get("appointment_context", {}),
                    "handoff_reason": "doctor_info_detected_appointment",
                    "last_action": "appointment_request"
                }
                return {
                    "messages": [],
                    "appointment_context": handoff_context,
                    "current_agent": "appointment_agent",
                    "agent_used": "doctor_info_agent"
                }
            
            # Search knowledge base for relevant information
            relevant_docs = []
            if self.faiss_rag and self.faiss_rag.available:
                docs = self.faiss_rag.search_knowledge(user_message, top_k=5)
                relevant_docs = docs  # FAISS integration returns formatted results
            
            # Prepare context with retrieved information
            knowledge_context = ""
            if relevant_docs:
                knowledge_context = "\n\nRelevant Information:\n"
                for i, doc in enumerate(relevant_docs, 1):
                    knowledge_context += f"{i}. {doc['content']}\n"
                    knowledge_context += f"   Source: {doc['source']}\n\n"
            
            prompt = f"""{DOCTOR_INFO_PROMPT.format(user_message=user_message, context=json.dumps(context, indent=2))}

{knowledge_context}

Based on the relevant information above, provide a helpful response about doctors, medical specialties, or hospital services. Always cite sources when using specific information."""
            
            response = self.llm.invoke([SystemMessage(content=prompt)])
            
            return {
                "messages": [AIMessage(content=response.content)],
                "rag_context": {"last_search": user_message, "docs_found": len(relevant_docs)},
                "current_agent": None,
                "agent_used": "doctor_info_agent"
            }
            
        except Exception as e:
            error_message = f"I apologize, but I'm having trouble accessing the doctor information system right now. Please try again or contact our staff directly for assistance. Error: {str(e)}"
            return {
                "messages": [AIMessage(content=error_message)],
                "current_agent": None
            }

class AppointmentAgent:
    """Handles all appointment-related operations using the actual appointment agent"""
    
    def __init__(self):
        self.llm = llm
        self._setup_appointment_agent()
    
    def _setup_appointment_agent(self):
        """Initialize the actual appointment agent with tools"""
        try:
            # Import the working appointment agent and its tools
            from Apointment_agent.appointments_agent import (
                search_doctors, get_doctor_profile, check_availability,
                check_availability_by_name, find_doctor_by_name,
                get_doctor_availability_range, find_next_available_slots,
                book_appointment, book_appointment_by_name_datetime,
                reschedule_appointment, cancel_appointment,
                get_system_time_date, table_schema
            )
            from langgraph.prebuilt import create_react_agent
            from langgraph.checkpoint.memory import MemorySaver
            
            # Create the tools list
            tools = [
                get_system_time_date,
                table_schema,
                search_doctors,
                get_doctor_profile,
                find_doctor_by_name,
                get_doctor_availability_range,
                find_next_available_slots,
                check_availability,
                check_availability_by_name,
                book_appointment,
                book_appointment_by_name_datetime,
                reschedule_appointment,
                cancel_appointment
            ]
            self.cancel_appointment_tool = cancel_appointment
            
            # Create the appointment agent with proper prompt
            appointment_prompt = """
            You are ClinicBot, a professional healthcare appointment assistant integrated into a larger hospital AI system.

            **Core Rules:**
            - Provide professional, clear, and helpful responses
            - Use tools to gather information and perform actions
            - Always protect patient privacy and maintain confidentiality
            - Keep responses concise but complete

            **Operational Guidelines:**
            - Use `get_system_time_date()` for current date/time when needed
            - Use `search_doctors()` to find doctors by specialty, language, or designation
            - Use `find_doctor_by_name()` to resolve the correct doctor record from a user-provided name
            - Use `get_doctor_profile()` for detailed doctor information
            - Prefer `check_availability_by_name()` to check appointment slots by doctor name and date (and optional time)
            - Prefer `book_appointment_by_name_datetime()` to book using doctor name + natural date/time (do NOT require slot IDs from the user)
            - Only fall back to `check_availability()` and `book_appointment()` with doctor_id/slot_id if strictly necessary or the user explicitly provides them
            - Use `reschedule_appointment()` to reschedule with appointment_id and new_slot_id
            - Use `cancel_appointment()` to cancel with appointment_id
            - Always confirm patient details before booking/rescheduling/canceling

            **Response Style:**
            - Be warm, professional, and empathetic
            - Format information clearly with bullet points or numbered lists
            - Focus on what matters to the patient: doctor names, times, dates, specialties
            - When showing available slots, present human-friendly times; do not expose internal slot IDs unless booking or the user asks

            **Important Notes:**
            - Patient details may be provided in the conversation context
            - Always check availability before attempting to book
            - Provide clear confirmation with appointment details after successful operations

            **Booking by Natural Language:**
            - If the user says "Book me with Dr. [Name] on [Date] at [Time]", first parse and check availability using `check_availability_by_name()`
            - If an exact slot exists, call `book_appointment_by_name_datetime()`
            - If no exact match, present the 2-3 nearest available times and ask which to confirm. If user picks one, proceed to book using the appropriate tool
            """

            # Create agent with memory for this conversation thread
            memory = MemorySaver()
            self.agent = create_react_agent(
                self.llm,
                tools,
                checkpointer=memory,
                prompt=appointment_prompt
            )
            
            print("✅ Appointment agent with tools initialized successfully")
            self.available = True
            
        except Exception as e:
            print(f"⚠️ Appointment agent initialization failed: {e}")
            self.agent = None
            self.available = False
            self.cancel_appointment_tool = None
    
    def __call__(self, state: HospitalChatbotState) -> Dict[str, Any]:
        if not self.available or not self.agent:
            error_message = "I apologize, but the appointment system is currently unavailable. Please try again or contact our appointment line directly."
            return {
                "messages": [AIMessage(content=error_message)],
                "current_agent": None
            }
        
        user_message = state["messages"][-1].content if state["messages"] else ""
        conversation_id = state.get("conversation_id", "default")
        lower_message = user_message.lower()
        
        # Get existing context to provide to the agent
        user_context = state.get("user_context", {})
        appointment_context = state.get("appointment_context", {})
        
        import re
        appointment_id = None
        doctor_id = None
        patient_id = None

        appointment_id_match = re.search(r"(?:appointment\s*(?:id|number|#)\s*(?:is|:)?\s*)(\d+)", user_message, re.IGNORECASE)
        if appointment_id_match:
            appointment_id = int(appointment_id_match.group(1))

        doctor_id_match = re.search(r"(?:doctor\s*id\s*(?:is|:)?\s*)(\d+)", user_message, re.IGNORECASE)
        if doctor_id_match:
            doctor_id = int(doctor_id_match.group(1))

        patient_id_match = re.search(r"(?:patient\s*id\s*(?:is|:)?\s*)(\d+)", user_message, re.IGNORECASE)
        if patient_id_match:
            patient_id = int(patient_id_match.group(1))

        cancel_requested = any(keyword in lower_message for keyword in ["cancel", "cancellation", "call off"])
        reschedule_requested = any(keyword in lower_message for keyword in ["reschedule", "move", "change time", "change date"])

        # Create a context-aware message that includes any previously captured details
        context_info = ""
        if user_context.get("name"):
            context_info += f"Patient name: {user_context['name']}\n"
        if user_context.get("phone"):
            context_info += f"Patient phone: {user_context['phone']}\n"
        if appointment_context.get("specialty"):
            context_info += f"Requested specialty: {appointment_context['specialty']}\n"
        if appointment_context.get("preferred_date_text"):
            context_info += f"Preferred date: {appointment_context['preferred_date_text']}\n"
        if appointment_context.get("preferred_time_text"):
            context_info += f"Preferred time: {appointment_context['preferred_time_text']}\n"
        if appointment_context.get("reason"):
            context_info += f"Reason for visit: {appointment_context['reason']}\n"
        if appointment_context.get("appointment_id"):
            context_info += f"Known appointment ID: {appointment_context['appointment_id']}\n"
        if appointment_id:
            context_info += f"Newly provided appointment ID: {appointment_id}\n"
        if doctor_id:
            context_info += f"Doctor ID referenced: {doctor_id}\n"
        
        # Combine user message with context
        enhanced_message = f"{user_message}"
        if context_info.strip():
            enhanced_message += f"\n\nContext from previous conversation:\n{context_info.strip()}"

        system_notes = []
        if cancel_requested:
            system_notes.append("Detected user intent: cancel appointment")
        if reschedule_requested:
            system_notes.append("Detected user intent: reschedule appointment")
        if appointment_id:
            system_notes.append(f"Parsed appointment_id={appointment_id}")
        if doctor_id:
            system_notes.append(f"Parsed doctor_id={doctor_id}")
        if patient_id:
            system_notes.append(f"Parsed patient_id={patient_id}")
        if system_notes:
            enhanced_message += "\n\nSystem notes:\n" + "\n".join(f"- {note}" for note in system_notes)

        updated_user_ctx = dict(user_context)
        updated_appt_ctx = {
            **appointment_context,
            "last_action": "appointment_request",
            "timestamp": datetime.now().isoformat()
        }

        if appointment_id:
            updated_appt_ctx["appointment_id"] = appointment_id
        if doctor_id:
            updated_appt_ctx["doctor_id"] = doctor_id
        if patient_id:
            updated_user_ctx["patient_id"] = patient_id

        if cancel_requested and appointment_id and self.cancel_appointment_tool is not None:
            try:
                cancel_result = self.cancel_appointment_tool.invoke({"appointment_id": appointment_id})
            except Exception as e:
                cancel_result = {"status": "failed", "message": str(e)}
            if cancel_result.get("status") == "success":
                response_content = (
                    f"Your appointment #{appointment_id} has been canceled successfully. "
                    "If you need to schedule another visit, just let me know."
                )
                updated_appt_ctx["last_action"] = "cancellation_completed"
                updated_appt_ctx["cancellation_result"] = cancel_result
                return {
                    "messages": [AIMessage(content=response_content)],
                    "appointment_context": updated_appt_ctx,
                    "user_context": updated_user_ctx,
                    "current_agent": None,
                    "agent_used": "appointment_agent"
                }
            else:
                failure_message = cancel_result.get("message", "I'm unable to cancel that appointment at the moment.")
                enhanced_message += (
                    f"\n\nSystem notes:\n- Direct cancellation attempt failed: {failure_message}."
                    "\n- Please assist the user in canceling appointment_id as soon as possible."
                )
                updated_appt_ctx["last_action"] = "cancellation_pending"
                updated_appt_ctx["cancellation_result"] = cancel_result

        if cancel_requested and not appointment_id:
            updated_appt_ctx["last_action"] = "cancellation_pending"

        if reschedule_requested:
            updated_appt_ctx["last_action"] = "reschedule_requested"
        
        try:
            # Use the appointment agent to process the request
            agent_input = {"messages": [{"role": "user", "content": enhanced_message}]}
            
            config = {"configurable": {"thread_id": conversation_id}}
            
            # Run the agent and collect the response
            response_content = ""
            for step in self.agent.stream(agent_input, config=config, stream_mode="values"):
                if "messages" in step and step["messages"]:
                    last_message = step["messages"][-1]
                    if hasattr(last_message, 'content'):
                        response_content = last_message.content
            
            # Simple regex extraction for future context
            phone_match = re.search(r"(\+?\d[\d\s\-]{7,}\d)", user_message)
            if phone_match:
                updated_user_ctx["phone"] = phone_match.group(1).strip()
            
            name_match = re.search(r"(?:my name is|i am|i'm)\s+([a-zA-Z][a-zA-Z\s']{1,60})", user_message, re.IGNORECASE)
            if name_match:
                updated_user_ctx["name"] = name_match.group(1).strip().title()
            
            updated_appt_ctx["timestamp"] = datetime.now().isoformat()
            return {
                "messages": [AIMessage(content=response_content)],
                "appointment_context": updated_appt_ctx,
                "user_context": updated_user_ctx,
                "current_agent": None,
                "agent_used": "appointment_agent"
            }
            
        except Exception as e:
            print(f"Error in appointment agent: {e}")
            error_message = f"I apologize, but I'm having trouble with the appointment system right now. Please try again or call our appointment line directly."
            return {
                "messages": [AIMessage(content=error_message)],
                "current_agent": None
            }

class GeneralHealthAgent:
    """Handles general health questions and guidance"""
    
    def __init__(self):
        self.llm = llm
    
    def __call__(self, state: HospitalChatbotState) -> Dict[str, Any]:
        user_message = state["messages"][-1].content if state["messages"] else ""
        context = state.get("user_context", {})
        
        prompt = GENERAL_HEALTH_PROMPT.format(
            user_message=user_message,
            context=json.dumps(context, indent=2)
        )
        
        response = self.llm.invoke([SystemMessage(content=prompt)])
        
        return {
            "messages": [AIMessage(content=response.content)],
            "current_agent": None,
            "agent_used": "general_health_agent"
        }

class VoiceCommunicationsAgent:
    """Handles voice call scheduling, reminders, and communication requests"""
    
    def __init__(self):
        self.llm = llm
        self._setup_voice_tools()
    
    def _setup_voice_tools(self):
        """Setup voice communication tools"""
        try:
            from voice_tools import VOICE_TOOLS
            self.voice_tools = VOICE_TOOLS
            
        except Exception as e:
            print(f"Error setting up voice communications agent: {e}")
            self.voice_tools = []
    
    def __call__(self, state: HospitalChatbotState) -> Dict[str, Any]:
        user_message = state["messages"][-1].content if state["messages"] else ""
        
        # Check if this is a voice call interaction
        is_voice_call = "[VOICE_CALL]" in user_message or state.get("is_voice_call", False)
        clean_message = user_message.replace("[VOICE_CALL]", "").strip()
        
        try:
            # Check for voice-specific requests
            voice_keywords = [
                "call me back", "callback", "voice call", "phone call",
                "call reminder", "voice reminder", "schedule a call",
                "make a call", "ring me", "telephone"
            ]
            
            is_voice_request = any(keyword in clean_message.lower() for keyword in voice_keywords)
            
            if is_voice_request and self.voice_tools:
                # Handle voice-specific requests using tools
                response_parts = []
                
                if "call me back" in clean_message.lower() or "callback" in clean_message.lower():
                    response_parts.append("I understand you'd like a callback. To schedule this, I'll need:")
                    response_parts.append("• Your phone number")
                    response_parts.append("• Preferred callback time")
                    response_parts.append("• Reason for the callback")
                    response_parts.append("Once you provide these details, I can schedule the callback for you.")
                
                elif "reminder" in clean_message.lower():
                    response_parts.append("I can set up a voice reminder for your appointment. I'll need:")
                    response_parts.append("• Your appointment details (date, time, doctor)")
                    response_parts.append("• Your phone number")
                    response_parts.append("• When you'd like to be reminded (usually 24 hours before)")
                
                elif "call" in clean_message.lower():
                    response_parts.append("I can help with voice call services. What specific type of call do you need?")
                    response_parts.append("• Appointment reminder calls")
                    response_parts.append("• Callback scheduling")
                    response_parts.append("• General information calls")
                
                response_content = "\n".join(response_parts)
            
            else:
                # Standard voice communications response
                voice_prompt = f"""You are a voice communications specialist for the hospital. 
                
                Handle this voice request: {clean_message}
                
                Voice Context: {state.get("voice_context", {})}
                User Context: {state.get("user_context", {})}
                
                Provide helpful information about voice services, but explain that some features may require the voice system to be fully activated.
                Keep responses conversational and appropriate for voice delivery if this is a voice call."""
                
                response = self.llm.invoke([SystemMessage(content=voice_prompt)])
                response_content = response.content
            
            # Optimize response for voice if needed
            if is_voice_call:
                response_content = self._optimize_for_voice(response_content)
            
            return {
                "messages": [AIMessage(content=response_content)],
                "voice_context": {
                    **state.get("voice_context", {}),
                    "last_action": "voice_communication",
                    "is_voice_call": is_voice_call,
                    "timestamp": datetime.now().isoformat()
                },
                "current_agent": None,
                "agent_used": "voice_communications_agent"
            }
        
        except Exception as e:
            print(f"Error in voice communications agent: {e}")
            error_message = "I'm having trouble with voice services right now. How else can I help you?"
            
            return {
                "messages": [AIMessage(content=error_message)],
                "current_agent": None,
                "agent_used": "voice_communications_agent"
            }
    
    def _optimize_for_voice(self, text_response: str) -> str:
        """Optimize response for voice delivery"""
        # Remove markdown and formatting
        voice_response = text_response.replace("**", "").replace("*", "")
        voice_response = voice_response.replace("#", "").replace("`", "")
        
        # Replace technical terms with voice-friendly versions
        replacements = {
            "ID": "I D",
            "AM": "A M", 
            "PM": "P M",
            "Dr.": "Doctor",
            "&": "and",
            "%": "percent",
            "@": "at"
        }
        
        for old, new in replacements.items():
            voice_response = voice_response.replace(old, new)
        
        # Limit length for voice
        if len(voice_response) > 250:
            sentences = voice_response.split('. ')
            voice_response = '. '.join(sentences[:2])
            if not voice_response.endswith('.'):
                voice_response += '.'
            voice_response += " Is there anything else you'd like to know?"
        
        return voice_response

class EmergencyAgent:
    """Handles emergency situations and escalations"""
    
    def __init__(self):
        self.llm = llm
    
    def __call__(self, state: HospitalChatbotState) -> Dict[str, Any]:
        user_message = state["messages"][-1].content if state["messages"] else ""
        
        # Check for emergency keywords
        emergency_keywords = [
            "chest pain", "difficulty breathing", "severe bleeding", 
            "heart attack", "stroke", "unconscious", "emergency",
            "can't breathe", "severe pain", "bleeding heavily"
        ]
        
        is_emergency = any(keyword in user_message.lower() for keyword in emergency_keywords)
        
        if is_emergency:
            emergency_response = """🚨 MEDICAL EMERGENCY DETECTED 🚨

If this is a life-threatening emergency:
• Call emergency services immediately: 911 (US) or your local emergency number
• Go to the nearest emergency room
• Don't wait - seek immediate medical attention

For urgent but non-life-threatening issues:
• Visit our urgent care center
• Call our 24/7 nurse hotline: [Hospital Phone Number]

I'm also notifying our medical staff about your situation. Stay calm and seek immediate help if needed."""
            
            return {
                "messages": [AIMessage(content=emergency_response)],
                "escalation_needed": True,
                "safety_flags": ["MEDICAL_EMERGENCY"],
                "current_agent": None,
                "agent_used": "emergency_agent"
            }
        
        prompt = EMERGENCY_PROMPT.format(
            user_message=user_message,
            context={}
        )
        
        response = self.llm.invoke([SystemMessage(content=prompt)])
        
        return {
            "messages": [AIMessage(content=response.content)],
            "escalation_needed": True,
            "current_agent": None,
            "agent_used": "emergency_agent"
        }

# Condition Functions
def should_continue(state: HospitalChatbotState) -> str:
    """Determine next step based on current state"""
    if state.get("escalation_needed"):
        return "escalate"
    elif state.get("current_agent"):
        return state["current_agent"]
    else:
        return END

def route_agent(state: HospitalChatbotState) -> str:
    """Route to specific agent based on supervisor decision"""
    agent = state.get("current_agent")
    if agent == "clarification":
        return "supervisor"  # Ask for clarification
    return agent or "supervisor"

def create_hospital_chatbot():
    """Create and configure the hospital chatbot graph"""
    
    # Initialize agents
    supervisor = SupervisorAgent()
    doctor_info = DoctorInfoAgent()
    appointment = AppointmentAgent()
    general_health = GeneralHealthAgent()
    voice_communications = VoiceCommunicationsAgent()
    emergency = EmergencyAgent()
    
    # Create the graph
    workflow = StateGraph(HospitalChatbotState)
    
    # Add nodes
    workflow.add_node("supervisor", supervisor)
    workflow.add_node("doctor_info_agent", doctor_info)
    workflow.add_node("appointment_agent", appointment)
    workflow.add_node("general_health_agent", general_health)
    workflow.add_node("voice_communications_agent", voice_communications)
    workflow.add_node("emergency_agent", emergency)
    
    # Add edges
    workflow.add_edge(START, "supervisor")
    
    # Conditional edges from supervisor
    workflow.add_conditional_edges(
        "supervisor",
        route_agent,
        {
            "doctor_info_agent": "doctor_info_agent",
            "appointment_agent": "appointment_agent", 
            "general_health_agent": "general_health_agent",
            "voice_communications_agent": "voice_communications_agent",
            "emergency_agent": "emergency_agent",
            "supervisor": "supervisor"  # For clarification loops
        }
    )
    
    # All agents route back to end or escalation
    workflow.add_conditional_edges(
        "doctor_info_agent",
        should_continue,
        {
            "escalate": "emergency_agent",
            "appointment_agent": "appointment_agent",
            END: END
        }
    )
    
    workflow.add_conditional_edges(
        "appointment_agent", 
        should_continue,
        {"escalate": "emergency_agent", END: END}
    )
    
    workflow.add_conditional_edges(
        "general_health_agent",
        should_continue, 
        {"escalate": "emergency_agent", END: END}
    )
    
    workflow.add_conditional_edges(
        "voice_communications_agent",
        should_continue, 
        {"escalate": "emergency_agent", END: END}
    )
    
    workflow.add_edge("emergency_agent", END)
    
    # Compile with memory
    memory = MemorySaver()
    app = workflow.compile(checkpointer=memory)
    
    return app

class HospitalChatbot:
    """Main chatbot interface"""
    
    def __init__(self):
        self.app = create_hospital_chatbot()
        self._session_store: Dict[str, Dict[str, Any]] = {}
        print("✅ Hospital chatbot initialized successfully")
    
    def chat(
        self,
        message: str,
        conversation_id: str = None,
        voice_context: Dict[str, Any] = None,
        category_hint: Optional[str] = None
    ) -> Dict[str, Any]:
        """Process a user message and return response"""
        if not conversation_id:
            conversation_id = str(uuid.uuid4())
        session = self._session_store.get(conversation_id)
        if not session:
            session = {
                "user_context": {},
                "appointment_context": {},
                "voice_context": {},
                "agent_used": None,
                "trace_id": str(uuid.uuid4()),
                "last_updated": datetime.now().isoformat()
            }
            self._session_store[conversation_id] = session

        stored_user_ctx = dict(session.get("user_context", {}))
        stored_appt_ctx = dict(session.get("appointment_context", {}))
        stored_voice_ctx = dict(session.get("voice_context", {}))
        
        # Check if this is a voice call
        voice_context = voice_context or {}
        stored_voice_ctx.update({k: v for k, v in voice_context.items() if v is not None})
        is_voice_call = "[VOICE_CALL]" in message or stored_voice_ctx.get("is_voice_call", False)
        if is_voice_call:
            stored_voice_ctx["is_voice_call"] = True
        
        call_sid = stored_voice_ctx.get("call_sid")
        caller_phone = stored_voice_ctx.get("caller_phone")
        stream_sid = stored_voice_ctx.get("stream_sid")
        trace_id = session.get("trace_id") or str(uuid.uuid4())
        session["trace_id"] = trace_id
        previous_agent = session.get("agent_used")
        
        # IMPORTANT: Only pass the new message; do not reset contexts each turn
        initial_state = {
            "messages": [HumanMessage(content=message)],
            # Reset transient flags each turn; agents can raise them again if needed
            "escalation_needed": False,
            "safety_flags": [],
            "current_agent": None,
            "agent_used": previous_agent,
            "is_voice_call": is_voice_call,  # Flag for voice interactions
            "voice_context": stored_voice_ctx,
            "user_context": stored_user_ctx,
            "appointment_context": stored_appt_ctx,
            "call_sid": call_sid,
            "caller_phone": caller_phone,
            "stream_sid": stream_sid,
            "conversation_id": conversation_id,
            "trace_id": trace_id,
            "category_hint": category_hint
        }
        
        config = {"configurable": {"thread_id": conversation_id}}
        
        try:
            result = self.app.invoke(initial_state, config=config)
            
            # Extract the final response
            response_message = ""
            for msg in result["messages"]:
                if isinstance(msg, AIMessage):
                    response_message = msg.content
            
            updated_user_ctx = dict(result.get("user_context", stored_user_ctx))
            updated_appt_ctx = dict(result.get("appointment_context", stored_appt_ctx))
            updated_voice_ctx = dict(result.get("voice_context", stored_voice_ctx))
            current_agent = result.get("agent_used") or previous_agent

            session.update(
                {
                    "user_context": updated_user_ctx,
                    "appointment_context": updated_appt_ctx,
                    "voice_context": updated_voice_ctx,
                    "agent_used": current_agent,
                    "last_updated": datetime.now().isoformat()
                }
            )

            # Remove transient routing hints so future turns can reroute naturally
            session.get("voice_context", {}).pop("category_hint", None)

            return {
                "response": response_message,
                "conversation_id": conversation_id,
                "escalation_needed": result.get("escalation_needed", False),
                "safety_flags": result.get("safety_flags", []),
                "agent_used": current_agent,
                "is_voice_call": is_voice_call,
                "voice_context": updated_voice_ctx,
                "appointment_context": updated_appt_ctx,
                "user_context": updated_user_ctx,
                "category_hint": category_hint,
                "messages": result.get("messages", []),  # Include full message history
                "success": True,
                "trace_id": trace_id
            }
            
        except Exception as e:
            print(f"Error in chatbot processing: {e}")
            error_response = "I apologize, but I'm experiencing technical difficulties. Please try again or contact our staff directly for assistance."
            
            # Shorter error message for voice calls
            if is_voice_call:
                error_response = "I'm sorry, I'm having technical trouble right now. Please call back later."
            
            return {
                "response": error_response,
                "conversation_id": conversation_id,
                "escalation_needed": True,
                "safety_flags": ["TECHNICAL_ERROR"],
                "agent_used": previous_agent,
                "is_voice_call": is_voice_call,
                "voice_context": stored_voice_ctx,
                "appointment_context": stored_appt_ctx,
                "user_context": stored_user_ctx,
                "category_hint": category_hint,
                "success": False,
                "trace_id": trace_id
            }
    
    def voice_chat(
        self,
        message: str,
        conversation_id: str = None,
        phone_number: str = None,
        call_sid: str = None,
        category: Optional[str] = None
    ) -> Dict[str, Any]:
        """Specialized method for voice call processing with enhanced context"""
        voice_context = {
            "is_voice_call": True,
            "caller_phone": phone_number,
            "call_sid": call_sid,
            "realtime_mode": True
        }
        
        # Add voice call marker to message
        voice_message = f"[VOICE_CALL] {message}"
        
        return self.chat(voice_message, conversation_id, voice_context, category)

def main():
    """Interactive chat interface for testing"""
    chatbot = HospitalChatbot()
    conversation_id = str(uuid.uuid4())
    
    print("\n🏥 Welcome to Hospital AI Assistant!")
    print("Type 'quit' to exit, 'help' for assistance\n")
    
    while True:
        try:
            user_input = input("You: ").strip()
            
            if user_input.lower() in ['quit', 'exit', 'bye']:
                print("👋 Thank you for using Hospital AI Assistant. Take care!")
                break
            
            if user_input.lower() == 'help':
                print("""
I can help you with:
• Finding doctors and specialists
• Booking, rescheduling, or canceling appointments
• General health information and guidance
• Emergency situations (though please call 911 for emergencies)

Just tell me what you need!
                """)
                continue
            
            if not user_input:
                print("Please enter your question or request.")
                continue
            
            # Process the message
            result = chatbot.chat(user_input, conversation_id)
            
            # Display response
            print(f"\n🤖 Assistant: {result['response']}\n")
            
            # Show any flags or escalations
            if result.get('escalation_needed'):
                print("⚠️ This conversation has been flagged for human review.")
            
            if result.get('safety_flags'):
                print(f"🚨 Safety flags: {', '.join(result['safety_flags'])}")
        
        except KeyboardInterrupt:
            print("\n👋 Goodbye!")
            break
        except Exception as e:
            print(f"❌ An error occurred: {e}")

if __name__ == "__main__":
    main()
