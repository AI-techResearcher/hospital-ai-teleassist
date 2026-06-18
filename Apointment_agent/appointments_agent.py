from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from dotenv import load_dotenv
import os
import sqlite3
from langgraph.checkpoint.memory import MemorySaver
from datetime import datetime, timedelta
from config import DB_CONFIG
from typing import Optional, Tuple, List, Dict, Any

# Natural language date parsing
try:
    from dateutil import parser as date_parser  # type: ignore
except Exception:  # pragma: no cover
    date_parser = None

# ------------------- MEMORY -------------------
memory = MemorySaver()

load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")

# ------------------- DB Connection -------------------
def get_connection():
    conn = sqlite3.connect(DB_CONFIG["database"])
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
    except Exception:
        pass
    return conn

# ------------------- TOOLS -------------------


from datetime import datetime
@tool
def get_system_time_date():
    """Returns the current system date and time.
    
    Returns:
        str: Current system date and time in ISO format.
    """
    """Get current system date and time."""
    current_time = datetime.now()
    return current_time.strftime("%Y-%m-%d %H:%M:%S")


@tool
def table_schema() -> dict:
    """Retrieves the complete database schema including all tables and their column definitions.
    
    Returns:
        dict: A dictionary where keys are table names and values are lists of column definitions.
        Each column definition includes the column name and its data type.
        
    Example:
        {
            'doctors': ['doctor_id (integer)', 'full_name (varchar)', ...],
            'appointments': ['appointment_id (integer)', 'patient_id (integer)', ...]
        }
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # Get all table names
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cur.fetchall()
        
        schema = {}
        for (table_name,) in tables:
            # Get column info for each table
            cur.execute(f"PRAGMA table_info({table_name});")
            columns = cur.fetchall()
            schema[table_name] = [f"{col[1]} ({col[2]})" for col in columns]
        
        return schema
    except Exception as e:
        return {"error": str(e)}
    finally:
        if conn:
            conn.close()


@tool
def search_doctors(specialty: str = None, language: str = None, designation: str = None, name: str = None) -> dict:
    """
    Search and filter doctors based on their specialty, spoken languages, designation, and/or name.
    
    Args:
        specialty (str, optional): Medical specialty to filter by (e.g., 'Cardiology', 'Pediatrics')
        language (str, optional): Language proficiency to filter by (e.g., 'English', 'Arabic')
        designation (str, optional): Professional designation to filter by (e.g., 'Consultant', 'Specialist')
        name (str, optional): Doctor's name to search for (e.g., 'Mohammad Kurdi', 'Ali')
    
    Returns:
        dict: A dictionary containing matched doctors with their basic information including:
            - doctor_id: Unique identifier for the doctor
            - full_name: Doctor's full name
            - specialty: Doctor's medical specialty
            - languages: Languages spoken by the doctor
            - designation: Professional designation
            - experience: Years of experience
            
    Note:
        - All filters are case-insensitive
        - Partial matches are supported
        - Multiple filters can be combined using AND logic
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        base = """
            SELECT d.doctor_id,
                   d.full_name,
                   d.designation,
                   COALESCE(d.experience_text, ''),
                   COALESCE(d.experience_years, 0),
                   COALESCE(GROUP_CONCAT(DISTINCT s.name), '') AS specialties,
                   COALESCE(GROUP_CONCAT(DISTINCT l.name), '') AS languages
            FROM doctors d
            LEFT JOIN doctor_specialties ds ON d.doctor_id = ds.doctor_id
            LEFT JOIN specialties s ON ds.specialty_id = s.specialty_id
            LEFT JOIN doctor_languages dl ON d.doctor_id = dl.doctor_id
            LEFT JOIN languages l ON dl.language_id = l.language_id
            WHERE 1=1
        """
        params: List[str] = []
        if specialty:
            base += " AND LOWER(s.name) LIKE ?"
            params.append(f"%{specialty.lower()}%")
        if language:
            base += " AND LOWER(l.name) LIKE ?"
            params.append(f"%{language.lower()}%")
        if designation:
            base += " AND LOWER(d.designation) LIKE ?"
            params.append(f"%{designation.lower()}%")
        if name:
            base += " AND LOWER(d.full_name) LIKE ?"
            params.append(f"%{name.lower()}%")
        base += " GROUP BY d.doctor_id, d.full_name, d.designation, d.experience_text, d.experience_years"
        cur.execute(base, tuple(params))
        rows = cur.fetchall()
        results = []
        for r in rows:
            results.append({
                "doctor_id": r[0],
                "name": r[1],
                "designation": r[2],
                "experience_text": r[3],
                "experience_years": r[4],
                "specialties": (r[5] or "").split(",") if r[5] else [],
                "languages": (r[6] or "").split(",") if r[6] else [],
            })
        return {"results": results}
    except Exception as e:
        return {"error": str(e)}
    finally:
        if conn:
            conn.close()


# ------------------- HELPERS -------------------
def _normalize_date(date_text: str) -> Optional[str]:
    """Parse various human date expressions into YYYY-MM-DD (local date).
    Returns None if parsing fails. Defaults to current year (2025).
    """
    if not date_text:
        return None
    
    current_year = datetime.now().year
    
    # Try explicit formats first
    for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%m-%d-%Y", "%m/%d/%Y", "%d-%m-%Y", "%d/%m/%Y", "%m-%d", "%m/%d", "%d-%m", "%d/%m"]:
        try:
            dt = datetime.strptime(date_text.replace("\n", " ").strip(), fmt)
            # If year absent, assume current year
            if fmt in ("%m-%d", "%m/%d", "%d-%m", "%d/%m"):
                dt = dt.replace(year=current_year)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            pass
    
    # Handle natural language like "06 september", "september 6th", etc.
    if date_parser is not None:
        try:
            dt = date_parser.parse(date_text, fuzzy=True, dayfirst=False)
            # If parsed year is not current year, assume user meant current year
            if dt.year != current_year and dt.year < current_year:
                dt = dt.replace(year=current_year)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return None
    return None


def _normalize_time(time_text: str) -> Optional[str]:
    """Parse various human time expressions into HH:MM:SS (24h).
    Returns None if parsing fails.
    """
    if not time_text:
        return None
    # common patterns
    candidates = [time_text.strip(), time_text.strip().lower().replace(" ", "")]  # e.g., "2 pm" -> "2pm"
    for cand in candidates:
        for fmt in ["%H:%M", "%H:%M:%S", "%I%p", "%I:%M%p", "%I %p", "%I:%M %p"]:
            try:
                t = datetime.strptime(cand, fmt)
                return t.strftime("%H:%M:%S")
            except Exception:
                pass
    # Try dateutil
    if date_parser is not None:
        try:
            dt = date_parser.parse(time_text, fuzzy=True)
            return dt.strftime("%H:%M:%S")
        except Exception:
            return None
    return None


def _parse_datetime(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Parse a combined text into (date_str, time_str). Both in normalized formats."""
    if not text:
        return None, None
    # Heuristic split
    lower = text.lower().replace(" on ", " ").replace(" at ", " ")
    parts = [p for p in lower.replace(",", " ").split() if p]
    date_str = None
    time_str = None
    # Try parse whole
    if date_parser is not None:
        try:
            dt = date_parser.parse(text, fuzzy=True)
            date_str = dt.strftime("%Y-%m-%d")
            time_str = dt.strftime("%H:%M:%S")
            return date_str, time_str
        except Exception:
            pass
    # Fallback: search tokens for time-like and date-like
    for i in range(len(parts)):
        if time_str is None:
            time_str = _normalize_time(parts[i])
        if date_str is None:
            date_str = _normalize_date(parts[i])
    return date_str, time_str


def _human_time(hhmmss: str) -> str:
    try:
        t = datetime.strptime(hhmmss, "%H:%M:%S")
        return t.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return hhmmss


def _human_date(date_str: str) -> str:
    """Convert YYYY-MM-DD date to human-friendly format like 'Mon, Sep 8'"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%a, %b %d")
    except Exception:
        return date_str


def _find_exact_or_nearest_slot(cur: sqlite3.Cursor, doctor_id: int, date: str, time_str: Optional[str]) -> Dict[str, Any]:
    """Find an exact matching slot for given date/time; otherwise propose nearest unbooked slots.
    Returns dict with keys: exact_match (slot or None), suggestions [slots].
    """
    cur.execute(
        """
        SELECT slot_id, start_time, end_time, is_booked
        FROM time_slots
        WHERE doctor_id = ? AND slot_date = ?
        ORDER BY start_time
        """,
        (doctor_id, date),
    )
    rows = cur.fetchall()
    slots = [dict(slot_id=r[0], start=str(r[1]), end=str(r[2]), is_booked=int(r[3])) for r in rows]
    unbooked = [s for s in slots if not s["is_booked"]]
    if time_str is None:
        return {"exact_match": None, "suggestions": unbooked[:3]}
    # exact match first
    exact = next((s for s in unbooked if s["start"][:5] == time_str[:5]), None)
    if exact:
        return {"exact_match": exact, "suggestions": []}
    # nearest by absolute time diff
    try:
        target = datetime.strptime(time_str, "%H:%M:%S")
        def diff(s):
            st = datetime.strptime(s["start"], "%H:%M:%S")
            return abs((st - target).total_seconds())
        suggestions = sorted(unbooked, key=diff)[:3]
        return {"exact_match": None, "suggestions": suggestions}
    except Exception:
        return {"exact_match": None, "suggestions": unbooked[:3]}


@tool
def get_doctor_profile(doctor_id: int) -> dict:
    """
    Retrieve comprehensive profile information for a specific doctor by their ID.
    
    Args:
        doctor_id (int): Unique identifier of the doctor
        
    Returns:
        dict: A dictionary containing the doctor's complete profile including:
            - full_name: Doctor's complete name
            - tagline: Professional tagline or brief introduction
            - designation: Professional title or position
            - specialty: Primary medical specialty
            - experience: Years of professional experience
            - languages: Languages spoken by the doctor
            - brief_profile: Short professional biography
            - core_competencies: List of key medical skills and expertise
            - qualifications: Academic and professional qualifications
            - specialties: List of all medical specialties and subspecialties
            
    Note:
        Returns error message if doctor_id is not found in the database
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT d.doctor_id, d.full_name, d.tagline, d.designation,
                   COALESCE(d.experience_text,''), COALESCE(d.experience_years,0),
                   d.brief_profile, d.core_competencies, d.qualifications,
                   COALESCE(GROUP_CONCAT(DISTINCT s.name),''),
                   COALESCE(GROUP_CONCAT(DISTINCT l.name),'')
            FROM doctors d
            LEFT JOIN doctor_specialties ds ON d.doctor_id = ds.doctor_id
            LEFT JOIN specialties s ON ds.specialty_id = s.specialty_id
            LEFT JOIN doctor_languages dl ON d.doctor_id = dl.doctor_id
            LEFT JOIN languages l ON dl.language_id = l.language_id
            WHERE d.doctor_id = ?
            GROUP BY d.doctor_id
            """,
            (doctor_id,),
        )
        row = cur.fetchone()
        if not row:
            return {"error": "Doctor not found"}
        return {
            "doctor_id": row[0],
            "full_name": row[1],
            "tagline": row[2],
            "designation": row[3],
            "experience_text": row[4],
            "experience_years": row[5],
            "brief_profile": row[6],
            "core_competencies": row[7],
            "qualifications": row[8],
            "specialties": (row[9] or "").split(",") if row[9] else [],
            "languages": (row[10] or "").split(",") if row[10] else [],
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        if conn:
            conn.close()
            
            

@tool
def find_doctor_by_name(name: str) -> dict:
    """Find doctor(s) by name (case-insensitive, partial supported). Returns a list of matches with doctor_id and specialty."""
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT d.doctor_id, d.full_name, d.designation, d.experience_years,
                   COALESCE(GROUP_CONCAT(DISTINCT s.name),'') AS specialties
            FROM doctors d
            LEFT JOIN doctor_specialties ds ON d.doctor_id = ds.doctor_id
            LEFT JOIN specialties s ON ds.specialty_id = s.specialty_id
            WHERE LOWER(d.full_name) LIKE ?
            GROUP BY d.doctor_id, d.full_name, d.designation, d.experience_years
            ORDER BY d.experience_years DESC, d.doctor_id
            """,
            (f"%{name.lower()}%",),
        )
        rows = cur.fetchall()
        return {
            "matches": [
                {
                    "doctor_id": r[0], 
                    "full_name": r[1], 
                    "designation": r[2],
                    "experience_years": r[3],
                    "specialties": (r[4] or "").split(",") if r[4] else []
                }
                for r in rows
            ]
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        if conn:
            conn.close()


@tool
def check_availability(doctor_id: int, date: str, timeslot: str) -> dict:
    """
    Check available appointment slots for a specific doctor on a given date and time.
    
    Args:
        doctor_id (int): Unique identifier of the doctor
        date (str): Appointment date in YYYY-MM-DD format
        timeslot (str): Preferred time for the appointment
        
    Returns:
        dict: A dictionary containing available time slots information:
            - slot_id: Unique identifier for the time slot
            - start_time: Start time of the available slot
            - end_time: End time of the available slot
            - doctor_info: Basic information about the doctor including
                full name, specialty, designation, and experience
            
    Note:
        - Only returns unbooked time slots
        - Validates the existence of the doctor and the format of date/time
        - Returns appropriate error messages for invalid inputs or no availability
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        date_norm = _normalize_date(date)
        if not date_norm:
            return {"status": "failed", "message": "Invalid date format"}
        time_norm = _normalize_time(timeslot) if timeslot else None
        params = [doctor_id, date_norm]
        q = "SELECT slot_id, start_time, end_time FROM time_slots WHERE doctor_id=? AND slot_date=? AND is_booked=0"
        if time_norm:
            q += " AND start_time = ?"
            params.append(time_norm)
        q += " ORDER BY start_time"
        cur.execute(q, tuple(params))
        slots = cur.fetchall()
        cur.execute(
            """
            SELECT d.full_name,
                   COALESCE(GROUP_CONCAT(DISTINCT s.name),''),
                   d.designation,
                   COALESCE(d.experience_text,'')
            FROM doctors d
            LEFT JOIN doctor_specialties ds ON d.doctor_id = ds.doctor_id
            LEFT JOIN specialties s ON ds.specialty_id = s.specialty_id
            WHERE d.doctor_id = ?
            GROUP BY d.doctor_id
            """,
            (doctor_id,),
        )
        info = cur.fetchone()
        doctor_info = None
        if info:
            doctor_info = {
                "full_name": info[0],
                "specialties": (info[1] or "").split(",") if info[1] else [],
                "designation": info[2],
                "experience_text": info[3],
            }
        return {
            "status": "ok",
            "doctor_id": doctor_id,
            "date": date_norm,
            "available_slots": [{"slot_id": s[0], "start": str(s[1]), "end": str(s[2]), "display": _human_time(str(s[1]))} for s in slots],
            "doctor_info": doctor_info,
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        if conn:
            conn.close()


@tool
def get_doctor_availability_range(doctor_id: int, start_date: str, days: int = 7) -> dict:
    """
    Get availability for a doctor across multiple days to help users find open slots.
    
    Args:
        doctor_id (int): Unique identifier of the doctor
        start_date (str): Starting date to check from (YYYY-MM-DD format)
        days (int): Number of days to check (default 7)
        
    Returns:
        dict: Dictionary with dates as keys and available slots as values
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        start_date_norm = _normalize_date(start_date)
        if not start_date_norm:
            return {"error": "Invalid start date format"}
        
        start_dt = datetime.strptime(start_date_norm, "%Y-%m-%d")
        availability = {}
        
        for day_offset in range(days):
            check_date = (start_dt + timedelta(days=day_offset)).strftime("%Y-%m-%d")
            cur.execute(
                """
                SELECT slot_id, start_time, end_time 
                FROM time_slots 
                WHERE doctor_id = ? AND slot_date = ? AND is_booked = 0
                ORDER BY start_time
                """,
                (doctor_id, check_date)
            )
            slots = cur.fetchall()
            if slots:
                availability[check_date] = [
                    {"slot_id": s[0], "start": str(s[1]), "end": str(s[2]), "display": _human_time(str(s[1]))}
                    for s in slots
                ]
        
        # Get doctor info
        cur.execute("SELECT full_name FROM doctors WHERE doctor_id = ?", (doctor_id,))
        doc_info = cur.fetchone()
        doctor_name = doc_info[0] if doc_info else f"Doctor ID {doctor_id}"
        
        return {
            "status": "ok",
            "doctor_id": doctor_id,
            "doctor_name": doctor_name,
            "date_range": f"{start_date_norm} to {(start_dt + timedelta(days=days-1)).strftime('%Y-%m-%d')}",
            "availability": availability
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        if conn:
            conn.close()


@tool
def find_next_available_slots(doctor_id: int, max_weeks: int = 3) -> dict:
    """
    Smart function to find the next available slots for a doctor, starting from today.
    Searches up to max_weeks in the future to find available appointments.
    
    Args:
        doctor_id (int): Unique identifier of the doctor
        max_weeks (int): Maximum weeks to search ahead (default 3)
        
    Returns:
        dict: Next available slots with dates and times
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # Start from today
        today = datetime.now()
        found_slots = []
        
        # Search week by week for available slots
        for week in range(max_weeks):
            start_date = (today + timedelta(weeks=week)).strftime("%Y-%m-%d")
            
            # Check 7 days from this start date
            for day_offset in range(7):
                check_date = (today + timedelta(weeks=week, days=day_offset)).strftime("%Y-%m-%d")
                
                cur.execute(
                    """
                    SELECT slot_id, start_time, end_time 
                    FROM time_slots 
                    WHERE doctor_id = ? AND slot_date = ? AND is_booked = 0
                    ORDER BY start_time LIMIT 5
                    """,
                    (doctor_id, check_date)
                )
                
                slots = cur.fetchall()
                if slots:
                    for slot in slots:
                        found_slots.append({
                            "date": check_date,
                            "slot_id": slot[0],
                            "start": str(slot[1]),
                            "end": str(slot[2]),
                            "display": f"{_human_date(check_date)} at {_human_time(str(slot[1]))}"
                        })
                
                # If we found some slots, return them (don't need to search all weeks)
                if len(found_slots) >= 10:  # Return first 10 available slots
                    break
            
            if len(found_slots) >= 10:
                break
        
        # Get doctor info
        cur.execute("SELECT full_name FROM doctors WHERE doctor_id = ?", (doctor_id,))
        doc_info = cur.fetchone()
        doctor_name = doc_info[0] if doc_info else f"Doctor ID {doctor_id}"
        
        return {
            "status": "ok",
            "doctor_id": doctor_id,
            "doctor_name": doctor_name,
            "next_available_slots": found_slots[:10],  # Return top 10
            "total_found": len(found_slots)
        }
        
    except Exception as e:
        return {"error": str(e)}
    finally:
        if conn:
            conn.close()


@tool
def check_availability_by_name(name: str, date: str, time: str = None) -> dict:
    """Check availability for a doctor by name on a given date, optionally targeting a time.
    Returns exact match if available, otherwise up to 3 nearest suggestions.
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        # Find doctor id(s) - prefer most experienced doctor if multiple matches
        cur.execute(
            """
            SELECT d.doctor_id, d.full_name, d.experience_years,
                   COALESCE(GROUP_CONCAT(DISTINCT s.name),'') AS specialties
            FROM doctors d
            LEFT JOIN doctor_specialties ds ON d.doctor_id = ds.doctor_id
            LEFT JOIN specialties s ON ds.specialty_id = s.specialty_id
            WHERE LOWER(d.full_name) LIKE ?
            GROUP BY d.doctor_id, d.full_name, d.experience_years
            ORDER BY d.experience_years DESC, d.doctor_id
            """,
            (f"%{name.lower()}%",),
        )
        docs = cur.fetchall()
        if not docs:
            return {"status": "failed", "message": "Doctor not found"}
        if len(docs) > 1:
            return {
                "status": "ambiguous",
                "message": "Multiple doctors match the name. Please specify by choosing a number:",
                "candidates": [
                    {
                        "choice": i+1,
                        "doctor_id": d[0], 
                        "full_name": d[1], 
                        "experience_years": d[2],
                        "specialties": (d[3] or '').split(',') if d[3] else []
                    }
                    for i, d in enumerate(docs)
                ],
            }
        doctor_id, full_name, experience_years, specialties = docs[0]
        time_norm = _normalize_time(time) if time else None
        date_norm = _normalize_date(date)
        if not date_norm:
            return {"status": "failed", "message": "Invalid date format"}
        result = _find_exact_or_nearest_slot(cur, doctor_id, date_norm, time_norm)
        return {
            "status": "ok",
            "doctor": {
                "doctor_id": doctor_id, 
                "full_name": full_name, 
                "experience_years": experience_years,
                "specialties": (specialties or '').split(',') if specialties else []
            },
            "date": date_norm,
            **result,
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        if conn:
            conn.close()
    """Check availability for a doctor by name on a given date, optionally targeting a time.
    Returns exact match if available, otherwise up to 3 nearest suggestions.
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        # Find doctor id(s)
        cur.execute(
            """
            SELECT d.doctor_id, d.full_name,
                   COALESCE(GROUP_CONCAT(DISTINCT s.name),'') AS specialties
            FROM doctors d
            LEFT JOIN doctor_specialties ds ON d.doctor_id = ds.doctor_id
            LEFT JOIN specialties s ON ds.specialty_id = s.specialty_id
            WHERE LOWER(d.full_name) LIKE ?
            GROUP BY d.doctor_id, d.full_name
            """,
            (f"%{name.lower()}%",),
        )
        docs = cur.fetchall()
        if not docs:
            return {"status": "failed", "message": "Doctor not found"}
        if len(docs) > 1:
            return {
                "status": "ambiguous",
                "message": "Multiple doctors match the name. Please specify.",
                "candidates": [
                    {"doctor_id": d[0], "full_name": d[1], "specialties": (d[2] or '').split(',') if d[2] else []}
                    for d in docs
                ],
            }
        doctor_id, full_name, specialties = docs[0]
        time_norm = _normalize_time(time) if time else None
        date_norm = _normalize_date(date)
        if not date_norm:
            return {"status": "failed", "message": "Invalid date format"}
        result = _find_exact_or_nearest_slot(cur, doctor_id, date_norm, time_norm)
        return {
            "status": "ok",
            "doctor": {"doctor_id": doctor_id, "full_name": full_name, "specialties": (specialties or '').split(',') if specialties else []},
            "date": date_norm,
            **result,
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        if conn:
            conn.close()


@tool  
def book_appointment_by_name_datetime(name: str, patient_id: int, date: str = None, time: str = None, datetime_text: str = None) -> dict:
    """Book an appointment using doctor name and natural date/time. Enhanced to handle duplicates better.
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        # Resolve doctor - prefer most experienced if duplicates
        cur.execute(
            """
            SELECT doctor_id, full_name, experience_years FROM doctors 
            WHERE LOWER(full_name) LIKE ? 
            ORDER BY experience_years DESC, doctor_id
            """, 
            (f"%{name.lower()}%",)
        )
        docs = cur.fetchall()
        if not docs:
            return {"status": "failed", "message": "Doctor not found"}
        if len(docs) > 1:
            return {
                "status": "ambiguous",
                "message": "Multiple doctors match the name. Please specify by number:",
                "candidates": [
                    {"choice": i+1, "doctor_id": d[0], "full_name": d[1], "experience_years": d[2]} 
                    for i, d in enumerate(docs)
                ],
            }
        
        # Use the single match or most experienced
        doctor_id, full_name, _ = docs[0]
        
        # Delegate to doctor_id version for consistency
        return book_appointment_by_doctor_id(doctor_id, patient_id, date, time, datetime_text)
        
    except Exception as e:
        return {"error": str(e)}
    finally:
        if conn:
            conn.close()


@tool
def book_appointment(doctor_id: int, patient_id: int, slot_id: int) -> dict:
    """
    Book a new appointment for a patient with a specific doctor using an available time slot.
    
    Args:
        doctor_id (int): Unique identifier of the doctor
        patient_id (int): Unique identifier of the patient
        slot_id (int): Unique identifier of the available time slot
        
    Returns:
        dict: A dictionary containing the booking result:
            - On success: {"status": "success", "appointment_id": <id>}
            - On failure: {"status": "failed", "message": <error_message>}
            
    Note:
        - Verifies patient exists in the database
        - Checks if the requested slot exists and is available
        - Automatically marks the slot as booked upon successful appointment creation
        - Returns appropriate error messages if any validation fails
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()

        # Check patient exists
        cur.execute("SELECT 1 FROM patients WHERE patient_id = ?", (patient_id,))
        if not cur.fetchone():
            return {"status": "failed", "message": "Patient not found"}

        # Validate slot belongs to doctor and is available
        cur.execute("SELECT doctor_id, is_booked FROM time_slots WHERE slot_id = ?", (slot_id,))
        row = cur.fetchone()
        if not row:
            return {"status": "failed", "message": "Slot not found"}
        slot_doctor_id, is_booked = row
        if slot_doctor_id != doctor_id:
            return {"status": "failed", "message": "Slot does not belong to the specified doctor"}
        if is_booked:
            return {"status": "failed", "message": "Slot already booked"}

        cur.execute(
            "INSERT INTO appointments (patient_id, doctor_id, slot_id, status) VALUES (?,?,?, 'scheduled')",
            (patient_id, doctor_id, slot_id),
        )
        appt_id = cur.lastrowid
        # Trigger will set is_booked=1
        conn.commit()
        return {"status": "success", "appointment_id": appt_id}
    except Exception as e:
        return {"error": str(e)}
    finally:
        if conn:
            conn.close()


@tool
def book_appointment_by_doctor_id(doctor_id: int, patient_id: int, date: str = None, time: str = None, datetime_text: str = None) -> dict:
    """Book an appointment using specific doctor_id to avoid ambiguity. Enhanced version.
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # Validate doctor exists
        cur.execute("SELECT full_name FROM doctors WHERE doctor_id = ?", (doctor_id,))
        doc_info = cur.fetchone()
        if not doc_info:
            return {"status": "failed", "message": "Doctor not found"}
        full_name = doc_info[0]

        # Parse date/time
        if datetime_text and (not date or not time):
            d_norm, t_norm = _parse_datetime(datetime_text)
        else:
            d_norm, t_norm = _normalize_date(date or ""), _normalize_time(time or "")
        
        if not d_norm:
            return {"status": "failed", "message": "Invalid or missing date"}
        
        # If time missing, provide available options for the date
        if not t_norm:
            cur.execute(
                "SELECT slot_id, start_time, end_time FROM time_slots WHERE doctor_id = ? AND slot_date = ? AND is_booked = 0 ORDER BY start_time",
                (doctor_id, d_norm),
            )
            slots = cur.fetchall()
            return {
                "status": "choose_time",
                "message": "Please pick a time from the available options.",
                "doctor": {"doctor_id": doctor_id, "full_name": full_name},
                "date": d_norm,
                "available": [
                    {"slot_id": s[0], "start": str(s[1]), "end": str(s[2]), "display": _human_time(str(s[1]))}
                    for s in slots
                ],
            }

        # Find exact or nearest slot
        match = _find_exact_or_nearest_slot(cur, doctor_id, d_norm, t_norm)
        if match["exact_match"]:
            slot = match["exact_match"]
            # Validate patient exists
            cur.execute("SELECT 1 FROM patients WHERE patient_id = ?", (patient_id,))
            if not cur.fetchone():
                return {"status": "failed", "message": "Patient not found"}
            # Create appointment using slot_id
            cur.execute(
                "INSERT INTO appointments (patient_id, doctor_id, slot_id, status) VALUES (?,?,?, 'scheduled')",
                (patient_id, doctor_id, slot["slot_id"]),
            )
            appt_id = cur.lastrowid
            conn.commit()
            return {
                "status": "success",
                "appointment_id": appt_id,
                "doctor": {"doctor_id": doctor_id, "full_name": full_name},
                "date": d_norm,
                "time": slot["start"],
            }
        else:
            # propose suggestions
            return {
                "status": "suggest",
                "message": "Requested time unavailable. Here are the nearest options.",
                "doctor": {"doctor_id": doctor_id, "full_name": full_name},
                "date": d_norm,
                "suggestions": [
                    {"slot_id": s["slot_id"], "start": s["start"], "display": _human_time(s["start"]) }
                    for s in match["suggestions"]
                ],
            }
    except Exception as e:
        return {"error": str(e)}
    finally:
        if conn:
            conn.close()
    """Book an appointment using doctor name and natural date/time. Avoids requiring slot IDs.
    If exact time isn't available, returns suggestions.
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        # Resolve doctor
        cur.execute("SELECT doctor_id, full_name FROM doctors WHERE LOWER(full_name) LIKE ?", (f"%{name.lower()}%",))
        docs = cur.fetchall()
        if not docs:
            return {"status": "failed", "message": "Doctor not found"}
        if len(docs) > 1:
            return {
                "status": "ambiguous",
                "message": "Multiple doctors match the name. Please specify.",
                "candidates": [{"doctor_id": d[0], "full_name": d[1]} for d in docs],
            }
        doctor_id, full_name = docs[0]

        # Parse date/time
        if datetime_text and (not date or not time):
            d_norm, t_norm = _parse_datetime(datetime_text)
        else:
            d_norm, t_norm = _normalize_date(date or ""), _normalize_time(time or "")
        if not d_norm:
            return {"status": "failed", "message": "Invalid or missing date"}
        # If time missing, just provide available options for the date
        if not t_norm:
            cur.execute(
                "SELECT slot_id, start_time, end_time FROM time_slots WHERE doctor_id = ? AND slot_date = ? AND is_booked = 0 ORDER BY start_time",
                (doctor_id, d_norm),
            )
            slots = cur.fetchall()
            return {
                "status": "choose_time",
                "message": "Please pick a time from the available options.",
                "doctor": {"doctor_id": doctor_id, "full_name": full_name},
                "date": d_norm,
                "available": [
                    {"slot_id": s[0], "start": str(s[1]), "end": str(s[2]), "display": _human_time(str(s[1]))}
                    for s in slots
                ],
            }

        # Find exact or nearest slot
        match = _find_exact_or_nearest_slot(cur, doctor_id, d_norm, t_norm)
        if match["exact_match"]:
            slot = match["exact_match"]
            # Validate patient exists
            cur.execute("SELECT 1 FROM patients WHERE patient_id = ?", (patient_id,))
            if not cur.fetchone():
                return {"status": "failed", "message": "Patient not found"}
            # Create appointment using slot_id
            cur.execute(
                "INSERT INTO appointments (patient_id, doctor_id, slot_id, status) VALUES (?,?,?, 'scheduled')",
                (patient_id, doctor_id, slot["slot_id"]),
            )
            appt_id = cur.lastrowid
            conn.commit()
            return {
                "status": "success",
                "appointment_id": appt_id,
                "doctor": {"doctor_id": doctor_id, "full_name": full_name},
                "date": d_norm,
                "time": slot["start"],
            }
        else:
            # propose suggestions
            return {
                "status": "suggest",
                "message": "Requested time unavailable. Here are the nearest options.",
                "doctor": {"doctor_id": doctor_id, "full_name": full_name},
                "date": d_norm,
                "suggestions": [
                    {"slot_id": s["slot_id"], "start": s["start"], "display": _human_time(s["start"]) }
                    for s in match["suggestions"]
                ],
            }
    except Exception as e:
        return {"error": str(e)}
    finally:
        if conn:
            conn.close()


@tool
def reschedule_appointment(appointment_id: int, new_slot_id: int) -> dict:
    """
    Reschedule an existing appointment to a different available time slot.
    
    Args:
        appointment_id (int): Unique identifier of the existing appointment
        new_slot_id (int): Unique identifier of the new time slot to reschedule to
        
    Returns:
        dict: A dictionary containing the rescheduling result:
            - On success: {"status": "success", "message": "Appointment rescheduled successfully"}
            - On failure: {"status": "failed", "message": <error_message>}
            
    Note:
        - Verifies the appointment exists
        - Checks if the new slot exists and is available
        - Updates both the appointment record and time slot availability status
        - Frees up the previously booked time slot
        - Returns appropriate error messages if any validation fails
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()

        # Fetch current appointment
        cur.execute("SELECT doctor_id, slot_id FROM appointments WHERE appointment_id = ?", (appointment_id,))
        row = cur.fetchone()
        if not row:
            return {"status": "failed", "message": "Appointment not found"}
        doctor_id, old_slot_id = row

        # Validate new slot belongs to same doctor and is free
        cur.execute("SELECT slot_date, start_time, end_time, doctor_id, is_booked FROM time_slots WHERE slot_id = ?", (new_slot_id,))
        slot = cur.fetchone()
        if not slot:
            return {"status": "failed", "message": "New slot not found"}
        slot_date, start_time, end_time, slot_doc_id, is_booked = slot
        if slot_doc_id != doctor_id:
            return {"status": "failed", "message": "New slot belongs to a different doctor"}
        if is_booked:
            return {"status": "failed", "message": "New slot is already booked"}

        # Perform reschedule: free old slot, assign new slot
        cur.execute("UPDATE time_slots SET is_booked = 0 WHERE slot_id = ?", (old_slot_id,))
        cur.execute("UPDATE time_slots SET is_booked = 1 WHERE slot_id = ?", (new_slot_id,))
        cur.execute(
            "UPDATE appointments SET slot_id = ?, status = 'rescheduled', updated_at = CURRENT_TIMESTAMP WHERE appointment_id = ?",
            (new_slot_id, appointment_id),
        )
        conn.commit()
        return {"status": "success", "message": f"Rescheduled to {slot_date} at {start_time}"}
    except Exception as e:
        return {"error": str(e)}
    finally:
        if conn:
            conn.close()


@tool
def cancel_appointment(appointment_id: int) -> dict:
    """
    Cancel an existing appointment and release the associated time slot for future bookings.
    
    Args:
        appointment_id (int): Unique identifier of the appointment to be canceled
        
    Returns:
        dict: A dictionary containing the cancellation result:
            - On success: {"status": "success", "message": "Appointment {id} canceled"}
            - On failure: {"status": "failed", "message": <error_message>}
            
    Note:
        - Verifies the appointment exists before attempting cancellation
        - Updates the appointment status to 'canceled' in the database
        - Releases the associated time slot by setting is_booked to FALSE
        - Returns appropriate error messages if the appointment cannot be found
    """
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("SELECT slot_id FROM appointments WHERE appointment_id = ?", (appointment_id,))
        row = cur.fetchone()
        if not row:
            return {"status": "failed", "message": "Appointment not found"}

        # Update status; trigger will free the slot
        cur.execute("UPDATE appointments SET status = 'canceled' WHERE appointment_id = ?", (appointment_id,))
        conn.commit()
        return {"status": "success", "message": f"Appointment {appointment_id} canceled"}
    except Exception as e:
        return {"error": str(e)}
    finally:
        if conn:
            conn.close()


# ------------------- AGENT -------------------

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1)

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
    book_appointment_by_doctor_id,
    book_appointment_by_name_datetime,
    reschedule_appointment,
    cancel_appointment
]


# For Conversational chat
appointment_agent = create_react_agent(
    llm,
    tools,
    checkpointer=memory,
    prompt="""
            You are ClinicBot, a professional healthcare appointment assistant.

            **Core Rules:**
            - Provide professional, clear, and helpful responses
            - Never expose technical details, database information, or system internals  
            - Use tools to gather information but present results in natural, user-friendly language
            - Always protect patient privacy and maintain confidentiality
            - Keep responses concise but complete (2-4 sentences typically)
            - Current year is 2025 - always assume dates refer to 2025 unless explicitly stated otherwise

            **Operational Guidelines:**
            - Use `get_system_time_date()` for current date/time when needed
            - Use `search_doctors()` to find doctors by specialty, language, or designation
            - Use `find_doctor_by_name()` to resolve a doctor's identity from a name
            - Use `get_doctor_profile()` for detailed doctor information
            - For multiple doctors with same name, use `get_doctor_availability_range()` to show week-long availability 
            - When users ask "which dates are available", use `get_doctor_availability_range()` starting from TODAY or next business day
            - Use `check_availability_by_name()` to check specific date/time combinations
            - Prefer `book_appointment_by_name_datetime()` for natural language booking
            - Use `book_appointment_by_doctor_id()` when you have resolved a specific doctor from ambiguous choices
            - Always assume patient_id=1 unless user provides different patient information
            - Present available slots in clean, numbered format with human-friendly times
            - For successful bookings, provide appointment confirmation with relevant details

            **CRITICAL AVAILABILITY CHECKING RULES:**
            - ALWAYS start availability checks from current date or the next 1-2 days (not weeks/months ahead)
            - When a doctor appears fully booked for a date range, try the NEXT consecutive week before giving up
            - If user asks for "Dr. [Name]" without specifying date, check availability starting from TODAY
            - For duplicate doctors with same name, check BOTH doctor IDs and show the one with better availability
            - Use `find_next_available_slots()` to quickly find the next available appointments for any doctor
            - Never assume a doctor is completely unavailable without checking at least 2-3 weeks from today

            **Smart Duplicate Handling:**
            - When multiple doctors have same name, automatically select the most experienced one
            - If user says "1" or "yes" to first choice, use the first doctor from the candidates list
            - Provide clear numbered choices when disambiguation is needed
            - Don't keep asking the same ambiguous question repeatedly

            **Response Style:**
            - Be warm, professional, and empathetic
            - Use proper medical terminology when appropriate
            - Format information clearly with bullet points or numbered lists
            - Never show raw data, JSON responses, or database queries
            - Focus on what matters to the patient: doctor names, times, dates, specialties
            - When no slots are available on requested date, proactively suggest alternative dates

            **Booking Process:**
            - Parse date expressions intelligently (assume 2025 for dates like "06 september")
            - If exact time is not available, propose the 2-3 closest times
            - Don't ask for internal slot IDs - handle that internally
            - Confirm all booking details before finalizing
            - When user asks for "available dates", show 7-day availability range starting from today
    """
)


# For another Agent call with structure output
# appointment_agent = create_react_agent(
#     llm,
#     tools,
#     checkpointer=memory,
#     prompt="""
                # You are ClinicBot, a backend appointment manager.
                # - Accept structured inputs only (JSON with intent + params).
                # - Call DB tools as needed.
                # - Always return JSON outputs (status, results, error).
                # - Do not generate natural language or explanations.
                # - Leave user-facing text to the Supervisor agent.
    #"""
# )

# ------------------- INTERFACE -------------------
# The following code is for testing the agent conversation
if __name__ == "__main__":
    while True:
        user_input = input("You: ")
        input_message = {"role": "user", "content": user_input}
        for step in appointment_agent.stream(
            {"messages": [input_message]},
            config={"configurable": {"thread_id": "user-session-1"}},  # session memory
            stream_mode="values"
        ):
            step["messages"][-1].pretty_print()
