# Medical Office AI Assistant

A natural, conversational AI phone assistant for medical offices using OpenAI's Realtime API. Features a friendly receptionist named "Sarah" who handles appointment booking, confirmations, and reminders with human-like conversation flow.

## 🚀 Key Features

- **Natural Conversation**: Human-like speech patterns with contractions, empathy, and warmth
- **OpenAI Realtime API**: Advanced speech-to-speech with gpt-4o model
- **Professional Medical Assistant**: Specialized for appointment management
- **Auto-Greeting**: Sarah starts conversations automatically
- **Appointment Management**: Full CRUD operations with JSON storage
- **Twilio Integration**: Seamless phone system integration
- **WebSocket Audio Streaming**: Real-time audio processing

## 🏗️ How It Works

### Core Files Structure

```
📁 Project Root
├── 🤖 final_fixed_agent.py     # Main FastAPI server & WebSocket handler
├── 📅 appointment_manager.py   # Appointment CRUD operations
├── ⚙️ config.py               # Configuration & environment settings
├── 🧪 test_call_now.py        # Test script for making calls
├── 📊 create_dummy_appointments.py # Generate sample data
├── 📋 appointments.json       # JSON data storage
├── 🔐 .env                   # Environment variables
└── 📦 requirements.txt       # Python dependencies
```

### Call Flow Architecture

```
📞 Phone Call → Twilio → FastAPI Webhook → WebSocket Connection
                                                    ↓
🤖 OpenAI Realtime API ← Audio Stream ← Sarah's Greeting
                                                    ↓
💬 Natural Conversation ↔ Appointment Management ↔ JSON Storage
```

### Technical Components

1. **FastAPI Server** (`final_fixed_agent.py`)
   - HTTP endpoints for Twilio webhooks
   - WebSocket handler for real-time audio
   - Connection management and error handling

2. **OpenAI Integration**
   - Realtime API with gpt-4o model
   - Natural speech-to-speech processing
   - Sarah's conversational personality

3. **Appointment System** (`appointment_manager.py`)
   - Create, read, update, delete appointments
   - JSON file storage (`appointments.json`)
   - Phone number and date-based queries

4. **Audio Processing**
   - Twilio ↔ WebSocket ↔ OpenAI audio streaming
   - Base64 audio encoding/decoding
   - Turn detection disabled for natural flow

## 📋 Requirements

- Python 3.8+
- OpenAI API key with Realtime API access
- Twilio account with phone number
- Public URL (ngrok for development)

## 🛠️ Installation & Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Edit `.env` file with your credentials:

```env
# OpenAI Configuration
OPENAI_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4o-realtime-preview-2024-10-01
OPENAI_TEMPERATURE=0.8

# Twilio Configuration
TWILIO_ACCOUNT_SID=your_twilio_sid
TWILIO_AUTH_TOKEN=your_twilio_token
TWILIO_PHONE_NUMBER=your_twilio_number

# Server Configuration
PORT=5050
PUBLIC_URL=your_ngrok_url
```

### 3. Create Sample Data (Optional)
```bash
python create_dummy_appointments.py
```

### 4. Start the Server
```bash
python final_fixed_agent.py
```

### 5. Setup Ngrok (Development)
```bash
ngrok http 5050
# Update PUBLIC_URL in .env with ngrok URL
```

## 🚀 Quick Start

### Make a Test Call
```bash
# Edit phone number in test_call_now.py
python test_call_now.py
```

### Expected Call Flow
1. **Call connects** - Twilio plays initial message
2. **Sarah greets you** - "Good morning! This is Sarah from Dr. Johnson's office. How can I help you today?"
3. **Natural conversation** - Ask about appointments, booking, rescheduling
4. **Appointment management** - Sarah can access and modify appointment data

## 🔧 How the Code Works

### Main Application (`final_fixed_agent.py`)

**Key Components:**

1. **FastAPI Server Setup**
   ```python
   app = FastAPI(title="Final Fixed Medical Office Voice Agent")
   # CORS middleware for web requests
   # Connection tracking for active calls
   ```

2. **Twilio Webhook Endpoints**
   ```python
   @app.api_route("/incoming-call", methods=["GET", "POST"])
   @app.api_route("/outgoing-call", methods=["GET", "POST"])
   # Handle incoming/outgoing calls and connect to WebSocket
   ```

3. **WebSocket Audio Handler**
   ```python
   @app.websocket("/media-stream")
   async def media_stream(websocket: WebSocket):
   # Real-time audio streaming between Twilio and OpenAI
   ```

**Audio Processing Flow:**

1. **Connection Setup**
   - Accept WebSocket connection from Twilio
   - Connect to OpenAI Realtime API
   - Initialize session with Sarah's personality

2. **Audio Streaming**
   - Receive audio from Twilio → Send to OpenAI
   - Receive audio from OpenAI → Send to Twilio
   - Handle base64 encoding/decoding

3. **Conversation Management**
   - Auto-greeting when call starts
   - Natural turn-taking (turn detection disabled)
   - Error handling and connection cleanup

### Appointment Management (`appointment_manager.py`)

**Data Structure:**
```python
@dataclass
class Appointment:
    patient_name: str
    phone_number: str
    appointment_date: str
    appointment_time: str
    doctor_name: str
    appointment_type: str
    status: str = "scheduled"
```

**Key Operations:**
- `create_appointment()` - Add new appointments
- `get_appointments_by_phone()` - Find patient's appointments
- `reschedule_appointment()` - Change date/time
- `update_appointment_status()` - Confirm/cancel appointments

### Sarah's Personality

**Conversation Style:**
- Uses contractions: "I'll", "we're", "that's"
- Natural reactions: "Got it", "Perfect!", "Oh, my mistake!"
- Empathetic responses: Shows care for stressed callers
- Professional but warm tone

**Technical Settings:**
- Temperature: 0.8 (natural variation)
- Turn detection: Disabled (prevents cutting)
- Max tokens: 200 (allows complete thoughts)
- Voice: Alloy (professional tone)

## 📞 API Endpoints

### Core Endpoints
- `GET /` - System status and active connections
- `GET /health` - Health check with timestamp
- `POST /incoming-call` - Twilio webhook for incoming calls
- `POST /outgoing-call` - Twilio webhook for outgoing calls
- `WebSocket /media-stream` - Real-time audio streaming

## 🧪 Testing

### Test Scenarios
```python
# Create sample appointments
python create_dummy_appointments.py

# Make test call
python test_call_now.py
```

### Conversation Examples
- **"I'd like to confirm my appointment for tomorrow"**
  - Sarah will find your appointment and confirm details
- **"I need to reschedule my appointment with Dr. Johnson"**
  - Sarah will help you pick a new time
- **"What time is my appointment?"**
  - Sarah will check and tell you the details
- **"I want to book a new appointment"**
  - Sarah will guide you through scheduling

### Sample Appointment Data
The dummy data includes:
- Your phone number: 2 appointments (tomorrow and day after)
- Various doctors: Dr. Sarah Johnson, Dr. Michael Brown, Dr. Lisa Chen
- Different appointment types: Checkup, Follow-up, Consultation

## 🎯 Key Improvements

### 1. Enhanced Concurrency
- Connection pooling for 30+ simultaneous calls
- Optimized WebSocket handling
- Resource management and cleanup

### 2. Advanced Speech Processing
- OpenAI Realtime API integration
- Temperature set to 0.5 for consistent responses
- Enhanced VAD (Voice Activity Detection)
- Interruption handling

### 3. Medical Office Optimization
- Professional greeting system
- Appointment-focused conversation flow
- Automated reminder scheduling
- Patient information management

### 4. Production Ready
- Comprehensive logging
- Error handling and recovery
- Health monitoring
- Performance metrics

## 🔧 Configuration Options

### Audio Settings
```env
VOICE=alloy                    # OpenAI voice model
AUDIO_FORMAT=g711_ulaw        # Twilio-compatible format
VAD_THRESHOLD=0.5             # Voice detection sensitivity
```

### Call Management
```env
MAX_CONCURRENT_CALLS=30       # Maximum simultaneous calls
CALL_TIMEOUT_SECONDS=300      # Call timeout (5 minutes)
MAX_RESPONSE_TOKENS=150       # Keep responses concise
```

### Scheduler Settings
```env
REMINDER_HOUR=14              # Send reminders at 2 PM
REMINDER_DAYS_AHEAD=1         # Remind 1 day before
```

## 📊 Monitoring

### Real-time Stats
```bash
curl http://localhost:5050/stats
```

### Health Check
```bash
curl http://localhost:5050/health
```

### Logs
```bash
tail -f medical_assistant.log
```

## 🧪 Testing

The system includes comprehensive testing:

```bash
# Run all tests
python test_system.py

# Test specific functionality
python -c "
import asyncio
from test_system import SystemTester
tester = SystemTester()
asyncio.run(tester.test_concurrent_calls(10))
"
```

## 🔒 Security Features

- Environment variable configuration
- Request validation
- Connection limits
- Error sanitization
- Secure WebSocket connections

## 📈 Performance Optimization

- Async/await throughout
- Connection pooling
- Efficient audio streaming
- Memory management
- Resource cleanup

## 🚨 Troubleshooting

### Common Issues

1. **Sarah cuts off mid-sentence**
   - Turn detection is disabled in current version
   - Check OpenAI API connection stability

2. **Call doesn't connect**
   - Verify ngrok URL is updated in `.env`
   - Check Twilio webhook configuration
   - Ensure server is running on correct port

3. **No audio/Sarah doesn't respond**
   - Verify OpenAI API key has Realtime API access
   - Check WebSocket connection logs
   - Ensure proper audio format (g711_ulaw)

4. **Appointment data not found**
   - Run `create_dummy_appointments.py` to generate test data
   - Check `appointments.json` file exists and has data

### Debug Mode
```bash
# Check server logs
tail -f medical_assistant.log

# Test server health
curl http://localhost:5050/health

# Verify ngrok tunnel
curl https://your-ngrok-url.ngrok-free.app/
```

### File Structure Check
```bash
# Essential files that should exist:
final_fixed_agent.py     # Main server
appointment_manager.py   # Data management
config.py               # Settings
.env                    # Your credentials
appointments.json       # Data storage (created automatically)
requirements.txt        # Dependencies
```

## 📝 System Message

The AI assistant uses this optimized system message:

> "You are a friendly medical office phone assistant. Your main jobs are: (1) help patients confirm, book, or reschedule doctor appointments, and (2) politely deliver appointment reminders. Speak naturally like a real person: short, clear sentences, warm tone, calm pace. Always greet the patient politely, confirm their name, date, and time of appointment. If something is unclear, ask a short follow-up question. When delivering reminders, confirm the appointment details and offer a quick option to reschedule if needed. If the patient interrupts you, stop immediately and listen. Never lecture or sound robotic—keep responses conversational, about 1–2 sentences. Avoid filler phrases, avoid technical talk. End each call with a polite closing, like 'Thank you, we look forward to seeing you.' Language: English."

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License.

## 🆘 Support

For support and questions:
- Check the logs: `medical_assistant.log`
- Run system tests: `python test_system.py`
- Monitor health: `curl http://localhost:5050/health`

---

**Medical Office AI Assistant v2.0** - Professional, scalable, and reliable phone automation for healthcare.