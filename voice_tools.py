"""
Voice Communication Tools for Hospital Chatbot Orchestrator
Provides voice call capabilities integrated with the existing agent system
"""

from langchain_core.tools import tool
from typing import Dict, Any, Optional
import httpx
import logging
from datetime import datetime, timedelta
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

# Configuration
# Use the Twilio voice agent base URL. Default to local agent port 5050 (matches twillio_comms_agent).
VOICE_AGENT_URL = os.getenv("VOICE_AGENT_URL", "http://localhost:5050")

# Setup logging
logger = logging.getLogger(__name__)

@tool
def schedule_voice_reminder(
    phone: str,
    appointment_datetime: str,
    doctor_name: str,
    patient_name: str,
    appointment_id: int = None,
    appointment_type: str = "appointment"
) -> Dict[str, Any]:
    """
    Schedule a voice call reminder for an appointment.
    
    Args:
        phone: Patient's phone number (e.g., +1234567890)
        appointment_datetime: Appointment date and time (ISO format)
        doctor_name: Name of the doctor
        patient_name: Name of the patient
        appointment_id: Unique appointment ID (optional)
        appointment_type: Type of appointment (default: "appointment")
    
    Returns:
        Dict with success status and details
    """
    try:
        # Import here to avoid circular imports
        from voice_call_scheduler import voice_scheduler
        
        # Parse datetime
        apt_datetime = datetime.fromisoformat(appointment_datetime.replace('Z', '+00:00'))
        
        # Schedule the reminder asynchronously
        async def schedule_async():
            return await voice_scheduler.schedule_appointment_reminder(
                appointment_id=appointment_id or 0,
                phone=phone,
                appointment_datetime=apt_datetime,
                doctor_name=doctor_name,
                patient_name=patient_name,
                appointment_type=appointment_type
            )
        
        # Run async function
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        success = loop.run_until_complete(schedule_async())
        loop.close()
        
        if success:
            return {
                "success": True,
                "message": f"Voice reminder scheduled for {patient_name}'s appointment with {doctor_name}",
                "reminder_time": (apt_datetime - timedelta(hours=24)).isoformat()
            }
        else:
            return {
                "success": False,
                "message": "Failed to schedule voice reminder"
            }
            
    except Exception as e:
        logger.error(f"Error scheduling voice reminder: {e}")
        return {
            "success": False,
            "message": f"Error scheduling voice reminder: {str(e)}"
        }

@tool
def make_outbound_call(
    phone: str,
    message: str,
    call_type: str = "outbound"
) -> Dict[str, Any]:
    """
    Make an immediate outbound voice call to a patient.
    
    Args:
        phone: Patient's phone number
    message: Informational only. Current voice agent starts a standard assistant greeting.
    call_type: Informational only for logging (outbound, callback, etc.)
    
    Returns:
        Dict with call status and call SID
    """
    try:
        # Make synchronous HTTP request to voice agent
        import requests
        
        # The current Twilio agent exposes /make-call which triggers an outbound call
        # and returns a call_sid. It does not accept a free-form message.
        payload = {"to": phone}
        response = requests.post(f"{VOICE_AGENT_URL}/make-call", json=payload, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            return {
                "success": True,
                "call_sid": result.get("call_sid"),
                "message": f"Call initiated to {phone}",
                "call_type": call_type
            }
        else:
            return {
                "success": False,
                "message": f"Failed to initiate call: {response.status_code}"
            }
            
    except Exception as e:
        logger.error(f"Error making outbound call: {e}")
        return {
            "success": False,
            "message": f"Error making outbound call: {str(e)}"
        }

@tool
def schedule_callback(
    phone: str,
    callback_datetime: str,
    reason: str,
    patient_name: str = None
) -> Dict[str, Any]:
    """
    Schedule a callback to a patient at a specific time.
    
    Args:
        phone: Patient's phone number
        callback_datetime: When to call back (ISO format)
        reason: Reason for the callback
        patient_name: Name of the patient (optional)
    
    Returns:
        Dict with success status and details
    """
    try:
        from voice_call_scheduler import voice_scheduler
        
        callback_time = datetime.fromisoformat(callback_datetime.replace('Z', '+00:00'))
        
        async def schedule_async():
            return await voice_scheduler.schedule_callback_call(
                phone=phone,
                callback_time=callback_time,
                reason=reason,
                patient_name=patient_name
            )
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        success = loop.run_until_complete(schedule_async())
        loop.close()
        
        if success:
            return {
                "success": True,
                "message": f"Callback scheduled for {callback_time.strftime('%Y-%m-%d %H:%M')}",
                "callback_time": callback_datetime,
                "reason": reason
            }
        else:
            return {
                "success": False,
                "message": "Failed to schedule callback"
            }
            
    except Exception as e:
        logger.error(f"Error scheduling callback: {e}")
        return {
            "success": False,
            "message": f"Error scheduling callback: {str(e)}"
        }

@tool
def get_voice_session_status() -> Dict[str, Any]:
    """
    Get health and active connection status of the voice agent.
    
    Returns:
        Dict with information about active voice sessions
    """
    try:
        import requests

        # The Twilio agent provides /health with basic info including active_connections.
        response = requests.get(f"{VOICE_AGENT_URL}/health", timeout=10)

        if response.status_code == 200:
            data = response.json()
            return {
                "status": data.get("status", "unknown"),
                "timestamp": data.get("timestamp"),
                "active_connections": data.get("active_connections", 0)
            }
        else:
            return {
                "status": "unreachable",
                "active_connections": 0,
                "error": f"Failed to get health: {response.status_code}"
            }
            
    except Exception as e:
        logger.error(f"Error getting voice session status: {e}")
        return {
            "active_sessions": {},
            "total_sessions": 0,
            "error": str(e)
        }

@tool
def cancel_scheduled_voice_call(job_id: str) -> Dict[str, Any]:
    """
    Cancel a previously scheduled voice call.
    
    Args:
        job_id: ID of the scheduled call job
    
    Returns:
        Dict with cancellation status
    """
    try:
        from voice_call_scheduler import voice_scheduler
        
        async def cancel_async():
            return await voice_scheduler.cancel_scheduled_call(job_id)
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        success = loop.run_until_complete(cancel_async())
        loop.close()
        
        if success:
            return {
                "success": True,
                "message": f"Scheduled call {job_id} cancelled successfully"
            }
        else:
            return {
                "success": False,
                "message": f"Failed to cancel scheduled call {job_id}"
            }
            
    except Exception as e:
        logger.error(f"Error cancelling scheduled call: {e}")
        return {
            "success": False,
            "message": f"Error cancelling scheduled call: {str(e)}"
        }

# Voice tool collection for easy integration
VOICE_TOOLS = [
    schedule_voice_reminder,
    make_outbound_call,
    schedule_callback,
    get_voice_session_status,
    cancel_scheduled_voice_call
]
