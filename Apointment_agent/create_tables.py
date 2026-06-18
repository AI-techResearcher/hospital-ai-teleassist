import sqlite3
import json
import re
from pathlib import Path
from datetime import datetime, timedelta, time, date
import random
from config import DB_CONFIG


def dict_factory(cursor, row):
    # Not used; kept for reference
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def enable_foreign_keys(conn: sqlite3.Connection):
    conn.execute("PRAGMA foreign_keys = ON;")


def drop_all(cur: sqlite3.Cursor):
    cur.executescript(
        """
        DROP TRIGGER IF EXISTS trg_appointments_insert_book;
        DROP TRIGGER IF EXISTS trg_appointments_update_status;
        DROP TRIGGER IF EXISTS trg_appointments_delete_free;

        DROP TABLE IF EXISTS appointments;
        DROP TABLE IF EXISTS time_off;
        DROP TABLE IF EXISTS working_hours;
        DROP TABLE IF EXISTS time_slots;
        DROP TABLE IF EXISTS doctor_languages;
        DROP TABLE IF EXISTS languages;
        DROP TABLE IF EXISTS doctor_specialties;
        DROP TABLE IF EXISTS specialties;
        DROP TABLE IF EXISTS doctors;
        DROP TABLE IF EXISTS departments;
        DROP TABLE IF EXISTS locations;
        DROP TABLE IF EXISTS patient_insurances;
        DROP TABLE IF EXISTS insurance_providers;
        DROP TABLE IF EXISTS patients;
        """
    )


def create_schema(cur: sqlite3.Cursor):
    cur.executescript(
        """
        -- Reference tables
        CREATE TABLE locations (
            location_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            address TEXT,
            phone TEXT
        );

        CREATE TABLE departments (
            department_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        );

        CREATE TABLE specialties (
            specialty_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        );

        CREATE TABLE languages (
            language_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        );

        -- Core entities
        CREATE TABLE patients (
            patient_id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            date_of_birth DATE,
            gender TEXT CHECK (gender IN ('Male','Female','Other') OR gender IS NULL),
            phone_number TEXT,
            email TEXT UNIQUE,
            address TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE insurance_providers (
            insurance_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        );

        CREATE TABLE patient_insurances (
            patient_id INTEGER NOT NULL,
            insurance_id INTEGER NOT NULL,
            policy_number TEXT,
            PRIMARY KEY (patient_id, insurance_id),
            FOREIGN KEY (patient_id) REFERENCES patients(patient_id) ON DELETE CASCADE,
            FOREIGN KEY (insurance_id) REFERENCES insurance_providers(insurance_id) ON DELETE CASCADE
        );

        CREATE TABLE doctors (
            doctor_id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            tagline TEXT,
            designation TEXT,
            experience_text TEXT,
            experience_years INTEGER,
            brief_profile TEXT,
            core_competencies TEXT,
            qualifications TEXT,
            location_id INTEGER,
            department_id INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (location_id) REFERENCES locations(location_id),
            FOREIGN KEY (department_id) REFERENCES departments(department_id)
        );

        CREATE TABLE doctor_specialties (
            doctor_id INTEGER NOT NULL,
            specialty_id INTEGER NOT NULL,
            PRIMARY KEY (doctor_id, specialty_id),
            FOREIGN KEY (doctor_id) REFERENCES doctors(doctor_id) ON DELETE CASCADE,
            FOREIGN KEY (specialty_id) REFERENCES specialties(specialty_id) ON DELETE CASCADE
        );

        CREATE TABLE doctor_languages (
            doctor_id INTEGER NOT NULL,
            language_id INTEGER NOT NULL,
            PRIMARY KEY (doctor_id, language_id),
            FOREIGN KEY (doctor_id) REFERENCES doctors(doctor_id) ON DELETE CASCADE,
            FOREIGN KEY (language_id) REFERENCES languages(language_id) ON DELETE CASCADE
        );

        CREATE TABLE working_hours (
            working_hour_id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id INTEGER NOT NULL,
            weekday INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6), -- 0=Monday
            start_time TIME NOT NULL,
            end_time TIME NOT NULL,
            UNIQUE (doctor_id, weekday),
            FOREIGN KEY (doctor_id) REFERENCES doctors(doctor_id) ON DELETE CASCADE
        );

        CREATE TABLE time_off (
            time_off_id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id INTEGER NOT NULL,
            start_datetime DATETIME NOT NULL,
            end_datetime DATETIME NOT NULL,
            reason TEXT,
            FOREIGN KEY (doctor_id) REFERENCES doctors(doctor_id) ON DELETE CASCADE
        );

        CREATE TABLE time_slots (
            slot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_id INTEGER NOT NULL,
            slot_date DATE NOT NULL,
            start_time TIME NOT NULL,
            end_time TIME NOT NULL,
            is_booked INTEGER NOT NULL DEFAULT 0 CHECK (is_booked IN (0,1)),
            UNIQUE (doctor_id, slot_date, start_time),
            FOREIGN KEY (doctor_id) REFERENCES doctors(doctor_id) ON DELETE CASCADE
        );

        CREATE TABLE appointments (
            appointment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            doctor_id INTEGER NOT NULL,
            slot_id INTEGER NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('scheduled','completed','canceled','no_show','rescheduled')),
            reason TEXT,
            notes TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
            FOREIGN KEY (doctor_id) REFERENCES doctors(doctor_id),
            FOREIGN KEY (slot_id) REFERENCES time_slots(slot_id),
            UNIQUE (slot_id)
        );

        -- Indexes for performance
        CREATE INDEX idx_doctors_name ON doctors(full_name);
        CREATE INDEX idx_slots_doctor_date ON time_slots(doctor_id, slot_date);
        CREATE INDEX idx_appt_patient ON appointments(patient_id);
        CREATE INDEX idx_appt_doctor ON appointments(doctor_id);

        -- Triggers to maintain time_slots.is_booked
        CREATE TRIGGER trg_appointments_insert_book
        AFTER INSERT ON appointments
        BEGIN
            UPDATE time_slots SET is_booked = 1 WHERE slot_id = NEW.slot_id;
        END;

        CREATE TRIGGER trg_appointments_update_status
        AFTER UPDATE OF status ON appointments
        BEGIN
            -- Free slot when canceled
            UPDATE time_slots
            SET is_booked = CASE WHEN NEW.status = 'canceled' THEN 0 ELSE is_booked END
            WHERE slot_id = NEW.slot_id;
        END;

        CREATE TRIGGER trg_appointments_delete_free
        AFTER DELETE ON appointments
        BEGIN
            UPDATE time_slots SET is_booked = 0 WHERE slot_id = OLD.slot_id;
        END;
        """
    )


def seed_reference(cur: sqlite3.Cursor):
    # Locations
    locations = [
        ("Main Hospital", "123 Health St, City", "+1-555-0100"),
        ("Downtown Clinic", "456 Wellness Ave, City", "+1-555-0110"),
    ]
    cur.executemany("INSERT INTO locations(name, address, phone) VALUES (?,?,?)", locations)

    # Departments
    departments = [
        ("Cardiology",), ("Neurology",), ("Pediatrics",), ("Orthopedics",), ("General Medicine",)
    ]
    cur.executemany("INSERT INTO departments(name) VALUES (?)", departments)

    # Languages
    for lang in ["English", "Arabic", "Urdu", "Hindi", "French"]:
        cur.execute("INSERT OR IGNORE INTO languages(name) VALUES (?)", (lang,))

    # Insurance Providers
    for prov in ["AllCare", "HealthPlus", "MediShield"]:
        cur.execute("INSERT OR IGNORE INTO insurance_providers(name) VALUES (?)", (prov,))


def upsert_specialty(cur: sqlite3.Cursor, name: str) -> int:
    cur.execute("INSERT OR IGNORE INTO specialties(name) VALUES (?)", (name.strip(),))
    cur.execute("SELECT specialty_id FROM specialties WHERE name = ?", (name.strip(),))
    return cur.fetchone()[0]


def upsert_language(cur: sqlite3.Cursor, name: str) -> int:
    cur.execute("INSERT OR IGNORE INTO languages(name) VALUES (?)", (name.strip(),))
    cur.execute("SELECT language_id FROM languages WHERE name = ?", (name.strip(),))
    return cur.fetchone()[0]


def approximate_years(text: str | None) -> int | None:
    if not text:
        return None
    m = re.search(r"(\d+)", text)
    return int(m.group(1)) if m else None


def seed_patients(cur: sqlite3.Cursor, n: int = 20):
    random.seed(42)
    first_names = ["Ali", "Ayesha", "Omar", "Fatima", "Zain", "Hina", "Ahmed", "Sana", "Bilal", "Maryam",
                   "Imran", "Nida", "Usman", "Zara", "Khalid", "Noor", "Hamza", "Iqra", "Talha", "Hareem"]
    last_names = ["Khan", "Shah", "Ahmed", "Malik", "Hussain", "Iqbal", "Javed", "Rehman", "Raza", "Chaudhry"]
    for i in range(n):
        birth_date = (datetime(1980, 1, 1) + timedelta(days=random.randint(0, 15000))).date().isoformat()
        gender = random.choice(["Male", "Female"])  # keep simple
        phone = f"+92300{i:07d}"
        email = f"user{i}@example.com"
        address = f"Sector {random.randint(1, 10)}, City"
        cur.execute(
            """
            INSERT INTO patients (first_name, last_name, date_of_birth, gender, phone_number, email, address)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (first_names[i % len(first_names)], last_names[i % len(last_names)], birth_date, gender, phone, email, address),
        )
        # capture the new patient id explicitly for FK inserts
        new_patient_id = cur.lastrowid
        # random insurance mapping
        if random.random() < 0.6:
            cur.execute("SELECT insurance_id FROM insurance_providers ORDER BY RANDOM() LIMIT 1")
            row = cur.fetchone()
            if row:
                ins_id = row[0]
                try:
                    cur.execute(
                        "INSERT INTO patient_insurances(patient_id, insurance_id, policy_number) VALUES (?,?,?)",
                        (new_patient_id, ins_id, f"POL-{random.randint(100000,999999)}"),
                    )
                except sqlite3.IntegrityError:
                    # Skip if any unexpected FK issue
                    pass


def seed_doctors_and_mappings(cur: sqlite3.Cursor):
    data_path = Path(__file__).parent / "doctors_by_specialty.json"
    doctors_data = json.loads(data_path.read_text(encoding="utf-8"))

    # default department mapping heuristic
    dept_map = {
        "Cardiology": "Cardiology",
        "Neuro": "Neurology",
        "Pediatric": "Pediatrics",
        "Ortho": "Orthopedics",
    }

    # Pre-fetch a default location and department
    cur.execute("SELECT location_id FROM locations ORDER BY location_id LIMIT 1")
    default_location_id = cur.fetchone()[0]
    cur.execute("SELECT department_id, name FROM departments")
    dept_rows = {name: did for (did, name) in cur.fetchall()}

    for group, doctors in doctors_data.items():
        # Match department by group name if possible
        dept_name = next((dept_rows_key for dept_rows_key in dept_rows.keys() if dept_rows_key.lower() in group.lower()), "General Medicine")
        department_id = dept_rows.get(dept_name, dept_rows.get("General Medicine"))

        for doc in doctors:
            experience_text = doc.get("experience")
            experience_years = approximate_years(experience_text)
            core_comp = ", ".join(doc.get("core_competencies", []) or [])
            qual = ", ".join(doc.get("qualifications", []) or [])

            cur.execute(
                """
                INSERT INTO doctors(full_name, tagline, designation, experience_text, experience_years, brief_profile, core_competencies, qualifications, location_id, department_id)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    doc.get("full_name"),
                    doc.get("tagline"),
                    doc.get("designation"),
                    experience_text,
                    experience_years,
                    doc.get("brief_profile"),
                    core_comp,
                    qual,
                    default_location_id,
                    department_id,
                ),
            )
            cur.execute("SELECT last_insert_rowid()")
            (doctor_id,) = cur.fetchone()

            # Specialties (primary and list)
            specialties = []
            if doc.get("specialty"):
                specialties.append(doc.get("specialty"))
            if doc.get("specialties"):
                specialties.extend(doc.get("specialties"))
            for s in specialties:
                if not s:
                    continue
                sid = upsert_specialty(cur, s)
                cur.execute("INSERT OR IGNORE INTO doctor_specialties(doctor_id, specialty_id) VALUES (?,?)", (doctor_id, sid))

            # Languages
            langs = []
            if isinstance(doc.get("languages"), list):
                langs = doc.get("languages")
            elif isinstance(doc.get("languages"), str):
                langs = [x.strip() for x in doc.get("languages").replace("/", ",").split(",") if x.strip()]
            for ln in langs:
                lid = upsert_language(cur, ln)
                cur.execute("INSERT OR IGNORE INTO doctor_languages(doctor_id, language_id) VALUES (?,?)", (doctor_id, lid))


def seed_working_hours(cur: sqlite3.Cursor):
    # Mon-Fri 09:00-17:00 default for all doctors
    cur.execute("SELECT doctor_id FROM doctors")
    doctors = [r[0] for r in cur.fetchall()]
    for did in doctors:
        for weekday in range(0, 5):  # 0..4 Mon..Fri
            cur.execute(
                "INSERT OR REPLACE INTO working_hours(doctor_id, weekday, start_time, end_time) VALUES (?,?,?,?)",
                (did, weekday, "09:00:00", "17:00:00"),
            )


def within_time_off(cur: sqlite3.Cursor, doctor_id: int, slot_dt: datetime, end_dt: datetime) -> bool:
    cur.execute(
        """
        SELECT 1 FROM time_off
        WHERE doctor_id = ?
          AND NOT (end_datetime <= ? OR start_datetime >= ?)
        LIMIT 1
        """,
        (doctor_id, slot_dt.isoformat(sep=" "), end_dt.isoformat(sep=" ")),
    )
    return cur.fetchone() is not None


def generate_time_slots(cur: sqlite3.Cursor, days_ahead: int = 7, slot_minutes: int = 30):
    cur.execute("SELECT doctor_id FROM doctors")
    doctors = [r[0] for r in cur.fetchall()]
    today = datetime.now().date()

    for did in doctors:
        for d in range(days_ahead):
            current_date = today + timedelta(days=d)
            weekday = (current_date.weekday())  # Monday=0
            # fetch working hours
            cur.execute(
                "SELECT start_time, end_time FROM working_hours WHERE doctor_id=? AND weekday=?",
                (did, weekday),
            )
            wh = cur.fetchone()
            if not wh:
                continue
            wh_start = datetime.combine(current_date, datetime.strptime(wh[0], "%H:%M:%S").time())
            wh_end = datetime.combine(current_date, datetime.strptime(wh[1], "%H:%M:%S").time())

            t = wh_start
            while t < wh_end:
                end_t = t + timedelta(minutes=slot_minutes)
                if end_t > wh_end:
                    break
                # skip if overlaps time off
                if within_time_off(cur, did, t, end_t):
                    t = end_t
                    continue
                cur.execute(
                    "INSERT OR IGNORE INTO time_slots(doctor_id, slot_date, start_time, end_time, is_booked) VALUES (?,?,?,?,0)",
                    (did, current_date.isoformat(), t.strftime("%H:%M:%S"), end_t.strftime("%H:%M:%S")),
                )
                t = end_t


def seed_sample_appointments(cur: sqlite3.Cursor, count: int = 15):
    random.seed(7)
    # Choose random free slots and book them
    for _ in range(count):
        cur.execute("SELECT slot_id, doctor_id FROM time_slots WHERE is_booked=0 ORDER BY RANDOM() LIMIT 1")
        row = cur.fetchone()
        if not row:
            break
        slot_id, doctor_id = row
        cur.execute("SELECT patient_id FROM patients ORDER BY RANDOM() LIMIT 1")
        (patient_id,) = cur.fetchone()
        status = random.choice(["scheduled", "completed", "canceled"])  # some variety
        cur.execute(
            "INSERT INTO appointments(patient_id, doctor_id, slot_id, status, reason) VALUES (?,?,?,?,?)",
            (patient_id, doctor_id, slot_id, status, random.choice(["Consultation", "Follow-up", "Test results"]))
        )


def main():
    # Database connection
    conn = sqlite3.connect(DB_CONFIG["database"])
    enable_foreign_keys(conn)
    cur = conn.cursor()

    try:
        # Clean slate
        drop_all(cur)

        # Schema
        create_schema(cur)

        # Seed reference and core data
        seed_reference(cur)
        seed_patients(cur, n=25)
        seed_doctors_and_mappings(cur)
        seed_working_hours(cur)

        # Optional: add a few time off windows
        cur.execute("SELECT doctor_id FROM doctors ORDER BY RANDOM() LIMIT 3")
        for (did,) in cur.fetchall():
            start = datetime.now().replace(hour=11, minute=0, second=0, microsecond=0) + timedelta(days=1)
            end = start + timedelta(hours=2)
            cur.execute(
                "INSERT INTO time_off(doctor_id, start_datetime, end_datetime, reason) VALUES (?,?,?,?)",
                (did, start.isoformat(sep=" "), end.isoformat(sep=" "), "Surgery"),
            )

        # Generate slots for next 7 days
        generate_time_slots(cur, days_ahead=7, slot_minutes=30)

        # Seed some appointments that will mark slots as booked via triggers
        seed_sample_appointments(cur, count=20)

        conn.commit()
    finally:
        cur.close()
        conn.close()

    print("✅ Comprehensive tables created and seeded successfully!")


if __name__ == "__main__":
    main()
