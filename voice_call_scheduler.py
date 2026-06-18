"""
Voice Call Scheduler for Hospital AI System
Handles scheduled appointment reminders and callback management
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import json
import sqlite3
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger
import httpx
from dotenv import load_dotenv
import os

load_dotenv()

# Configuration
VOICE_AGENT_URL = os.getenv("VOICE_AGENT_URL", "http://localhost:5050")
REMINDER_ADVANCE_HOURS = int(os.getenv("REMINDER_ADVANCE_HOURS", 24))  # 24 hours before

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class VoiceCallScheduler:
    """Manages scheduled voice calls for appointment reminders and callbacks"""
    
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.scheduled_calls = {}  # Track scheduled calls
        # Resolve appointments DB path robustly (absolute path) with env override
        base_dir = os.path.dirname(os.path.abspath(__file__))
        default_db = os.path.join(base_dir, "Apointment_agent", "appointments.db")
        self.appointment_db_path = os.getenv("APPOINTMENTS_DB_PATH", default_db)
        
    async def start(self):
        """Start the scheduler"""
        self.scheduler.start()
        logger.info("Voice call scheduler started")
        
        # Schedule daily check for upcoming appointments
        self.scheduler.add_job(
            self._check_daily_appointments,
            CronTrigger(hour=9, minute=0),  # Check at 9 AM daily
            id="daily_appointment_check"
        )
    
    async def stop(self):
        """Stop the scheduler"""
        self.scheduler.shutdown()
        logger.info("Voice call scheduler stopped")
    
    async def schedule_appointment_reminder(
        self, 
        appointment_id: int,
        phone: str,
        appointment_datetime: datetime,
        doctor_name: str,
        patient_name: str,
        appointment_type: str = "appointment"
    ):
        """Schedule a voice call reminder for an appointment"""
        try:
            # Calculate reminder time (24 hours before by default)
            reminder_time = appointment_datetime - timedelta(hours=REMINDER_ADVANCE_HOURS)
            
            # Don't schedule if reminder time is in the past
            if reminder_time <= datetime.now():
                logger.warning(f"Cannot schedule reminder for past time: {reminder_time}")
                return False
            
            job_id = f"reminder_{appointment_id}_{int(reminder_time.timestamp())}"
            
            appointment_details = {
                "appointment_id": appointment_id,
                "doctor": doctor_name,
                "patient_name": patient_name,
                "date": appointment_datetime.strftime("%A, %B %d, %Y"),
                "time": appointment_datetime.strftime("%I:%M %p"),
                "appointment_type": appointment_type,
                "phone": phone
            }
            
            # Schedule the reminder call
            self.scheduler.add_job(
                self._make_reminder_call,
                DateTrigger(run_date=reminder_time),
                args=[phone, appointment_details],
                id=job_id,
                replace_existing=True
            )
            
            # Track the scheduled call
            self.scheduled_calls[job_id] = {
                "appointment_id": appointment_id,
                "phone": phone,
                "reminder_time": reminder_time.isoformat(),
                "appointment_datetime": appointment_datetime.isoformat(),
                "type": "reminder"
            }
            
            logger.info(f"Scheduled reminder call for appointment {appointment_id} at {reminder_time}")
            return True
            
        except Exception as e:
            logger.error(f"Error scheduling appointment reminder: {e}")
            return False
    
    async def schedule_callback_call(
        self, 
        phone: str, 
        callback_time: datetime, 
        reason: str,
        patient_name: str = None
    ):
        """Schedule a callback call"""
        try:
            if callback_time <= datetime.now():
                logger.warning(f"Cannot schedule callback for past time: {callback_time}")
                return False
            
            job_id = f"callback_{phone.replace('+', '')}_{int(callback_time.timestamp())}"
            
            callback_details = {
                "phone": phone,
                "patient_name": patient_name,
                "reason": reason,
                "callback_time": callback_time.isoformat()
            }
            
            self.scheduler.add_job(
                self._make_callback_call,
                DateTrigger(run_date=callback_time),
                args=[phone, callback_details],
                id=job_id,
                replace_existing=True
            )
            
            self.scheduled_calls[job_id] = {
                "phone": phone,
                "callback_time": callback_time.isoformat(),
                "reason": reason,
                "type": "callback"
            }
            
            logger.info(f"Scheduled callback for {phone} at {callback_time}")
            return True
            
        except Exception as e:
            logger.error(f"Error scheduling callback: {e}")
            return False
    
    async def cancel_scheduled_call(self, job_id: str):
        """Cancel a scheduled call"""
        try:
            self.scheduler.remove_job(job_id)
            if job_id in self.scheduled_calls:
                del self.scheduled_calls[job_id]
            logger.info(f"Cancelled scheduled call: {job_id}")
            return True
        except Exception as e:
            logger.error(f"Error cancelling scheduled call {job_id}: {e}")
            return False
    
    async def _make_reminder_call(self, phone: str, appointment_details: Dict[str, Any]):
        """Make an appointment reminder call using the Twilio agent's /make-call endpoint"""
        try:
            # The current Twilio agent doesn't accept custom reminder text. We initiate a standard call.
            payload = {"to": phone}
            async with httpx.AsyncClient() as client:
                response = await client.post(f"{VOICE_AGENT_URL}/make-call", json=payload, timeout=30.0)

            if response.status_code == 200:
                result = response.json()
                logger.info(f"Reminder call initiated successfully: {result.get('call_sid')}")
            else:
                logger.error(f"Failed to make reminder call: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"Error making reminder call: {e}")
    
    async def _make_callback_call(self, phone: str, callback_details: Dict[str, Any]):
        """Make a callback call using the Twilio agent's /make-call endpoint"""
        try:
            payload = {"to": phone}
            async with httpx.AsyncClient() as client:
                response = await client.post(f"{VOICE_AGENT_URL}/make-call", json=payload, timeout=30.0)

            if response.status_code == 200:
                result = response.json()
                logger.info(f"Callback initiated successfully: {result.get('call_sid')}")
            else:
                logger.error(f"Failed to make callback: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"Error making callback: {e}")
    
    async def _check_daily_appointments(self):
        """Check for appointments that need reminder calls scheduled"""
        try:
            # Connect to appointments database
            conn = sqlite3.connect(self.appointment_db_path)
            cursor = conn.cursor()
            
            # Get appointments for the next 2 days that don't have reminders scheduled
            tomorrow = datetime.now() + timedelta(days=1)
            day_after = tomorrow + timedelta(days=1)
            
            cursor.execute("""
                SELECT id, patient_name, patient_phone, doctor_name, appointment_date, 
                       appointment_time, appointment_type
                FROM appointments 
                WHERE appointment_date BETWEEN ? AND ?
                AND status = 'confirmed'
            """, (tomorrow.date(), day_after.date()))
            
            appointments = cursor.fetchall()
            conn.close()
            
            for appointment in appointments:
                (apt_id, patient_name, phone, doctor_name, 
                 apt_date, apt_time, apt_type) = appointment
                
                # Create datetime object
                apt_datetime = datetime.combine(apt_date, apt_time)
                
                # Check if reminder is already scheduled
                reminder_job_id = f"reminder_{apt_id}_{int((apt_datetime - timedelta(hours=REMINDER_ADVANCE_HOURS)).timestamp())}"
                
                if reminder_job_id not in self.scheduled_calls:
                    await self.schedule_appointment_reminder(
                        apt_id, phone, apt_datetime, doctor_name, patient_name, apt_type
                    )
            
        except Exception as e:
            logger.error(f"Error checking daily appointments: {e}")
    
    def get_scheduled_calls(self) -> Dict[str, Any]:
        """Get information about all scheduled calls"""
        return {
            "scheduled_calls": self.scheduled_calls,
            "total_scheduled": len(self.scheduled_calls),
            "jobs": [job.id for job in self.scheduler.get_jobs()]
        }
    
    async def reschedule_appointment_reminder(
        self, 
        old_appointment_id: int,
        new_appointment_id: int,
        phone: str,
        new_appointment_datetime: datetime,
        doctor_name: str,
        patient_name: str
    ):
        """Reschedule an appointment reminder when appointment is changed"""
        try:
            # Cancel old reminder
            old_job_ids = [job_id for job_id in self.scheduled_calls.keys() 
                          if f"reminder_{old_appointment_id}_" in job_id]
            
            for job_id in old_job_ids:
                await self.cancel_scheduled_call(job_id)
            
            # Schedule new reminder
            await self.schedule_appointment_reminder(
                new_appointment_id, phone, new_appointment_datetime, 
                doctor_name, patient_name
            )
            
            logger.info(f"Rescheduled reminder from appointment {old_appointment_id} to {new_appointment_id}")
            
        except Exception as e:
            logger.error(f"Error rescheduling appointment reminder: {e}")

# Global scheduler instance
voice_scheduler = VoiceCallScheduler()

# Utility functions for integration with hospital chatbot orchestrator

async def schedule_reminder_for_appointment(appointment_data: Dict[str, Any]) -> bool:
    """Utility function to schedule reminder from appointment data"""
    try:
        return await voice_scheduler.schedule_appointment_reminder(
            appointment_id=appointment_data.get("id"),
            phone=appointment_data.get("patient_phone"),
            appointment_datetime=appointment_data.get("appointment_datetime"),
            doctor_name=appointment_data.get("doctor_name"),
            patient_name=appointment_data.get("patient_name"),
            appointment_type=appointment_data.get("appointment_type", "appointment")
        )
    except Exception as e:
        logger.error(f"Error in schedule_reminder_for_appointment: {e}")
        return False

async def schedule_patient_callback(phone: str, callback_datetime: datetime, reason: str) -> bool:
    """Utility function to schedule patient callback"""
    try:
        return await voice_scheduler.schedule_callback_call(phone, callback_datetime, reason)
    except Exception as e:
        logger.error(f"Error in schedule_patient_callback: {e}")
        return False

if __name__ == "__main__":
    # Test the scheduler
    async def test_scheduler():
        await voice_scheduler.start()
        
        # Test scheduling a reminder for tomorrow
        test_time = datetime.now() + timedelta(hours=1)
        await voice_scheduler.schedule_appointment_reminder(
            appointment_id=1,
            phone="+1234567890",
            appointment_datetime=test_time,
            doctor_name="Dr. Smith",
            patient_name="John Doe"
        )
        
        print("Scheduler test complete")
        print("Scheduled calls:", voice_scheduler.get_scheduled_calls())
        
        await asyncio.sleep(5)
        await voice_scheduler.stop()
    
    asyncio.run(test_scheduler())
