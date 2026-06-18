# Hospital Appointment Agent

A sophisticated AI-powered appointment booking system built with LangGraph and SQLite.

## Features

- 🔍 **Doctor Search**: Find doctors by specialty, language, or designation
- 👨‍⚕️ **Doctor Profiles**: Get detailed information about doctors
- 📅 **Availability Check**: Check available time slots for appointments
- 📝 **Appointment Booking**: Book new appointments
- ♻️ **Appointment Management**: Reschedule and cancel existing appointments
- 🤖 **Conversational AI**: Natural language interaction using OpenAI GPT-4

## Setup

1. **Install Requirements**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Environment**:
   - Set your `OPENAI_API_KEY` in the main project's `.env` file
   - The agent uses SQLite database for easy setup

3. **Initialize Database**:
   ```bash
   python create_tables.py
   ```

4. **Create Test Data** (optional):
   ```bash
   python create_test_slots.py
   ```

## Usage

### Interactive Chat Interface
```bash
python appointments_agent.py
```

### Testing
```bash
# Test basic functionality
python test_appointment_agent.py

# Test conversations
python test_conversations.py

# Test booking functionality
python test_booking.py

# Run comprehensive tests
python test_final.py
```

## Database Schema

- **patients**: Patient information
- **doctors**: Doctor profiles and specialties
- **appointments**: Scheduled appointments
- **time_slots**: Available appointment slots

## API Tools

The agent provides the following tools:

- `get_system_time_date()`: Get current system time
- `table_schema()`: View database schema
- `search_doctors(specialty, language, designation)`: Find doctors
- `get_doctor_profile(doctor_id)`: Get doctor details
- `check_availability(doctor_id, date, timeslot)`: Check available slots
- `book_appointment(doctor_id, patient_id, slot_id)`: Book appointment
- `reschedule_appointment(appointment_id, new_slot_id)`: Reschedule
- `cancel_appointment(appointment_id)`: Cancel appointment

## Configuration

The system is configured to use:
- SQLite database (`appointments.db`)
- OpenAI GPT-4o-mini model
- LangGraph for conversation management
- Memory-based conversation checkpointing

## Files

- `appointments_agent.py`: Main agent implementation
- `config.py`: Database configuration
- `create_tables.py`: Database initialization
- `doctors_by_specialty.json`: Doctor data
- `requirements.txt`: Python dependencies
- `test_*.py`: Various test scripts

## Integration

This appointment agent is designed to integrate with the larger Hospital AI System and can be called by other agents or services for appointment management functionality.
