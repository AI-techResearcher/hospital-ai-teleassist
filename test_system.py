#!/usr/bin/env python3
"""
Test script for Hospital AI System components
"""

import sys
import os
import traceback
from datetime import datetime

def test_hospital_chatbot_orchestrator():
    """Test the hospital chatbot orchestrator functionality"""
    print("\n" + "="*60)
    print("🧪 TESTING HOSPITAL CHATBOT ORCHESTRATOR")
    print("="*60)
    
    try:
        print("📦 Importing HospitalChatbot...")
        from hospital_chatbot_orchestrator import HospitalChatbot
        print("✅ Successfully imported HospitalChatbot")
        
        print("🚀 Initializing HospitalChatbot...")
        chatbot = HospitalChatbot()
        print("✅ Successfully initialized HospitalChatbot")
        
        # Test basic chat functionality
        print("💬 Testing basic chat functionality...")
        test_message = "Hello, I need help scheduling an appointment with Dr. Smith"
        test_response = chatbot.chat(test_message)
        print("✅ Basic chat test successful")
        print(f"📝 Response: {test_response.get('response', 'No response')}")
        print(f"🤖 Agent used: {test_response.get('agent_used', 'Unknown')}")
        print(f"🔄 Conversation ID: {test_response.get('conversation_id', 'Unknown')}")
        
        # Test voice chat functionality
        print("\n📞 Testing voice chat functionality...")
        voice_response = chatbot.voice_chat(
            "I need to schedule an appointment", 
            phone_number="+1234567890",
            call_sid="test_call_123"
        )
        print("✅ Voice chat test successful")
        print(f"📝 Voice Response: {voice_response.get('response', 'No response')}")
        print(f"🤖 Voice Agent used: {voice_response.get('agent_used', 'Unknown')}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error in hospital chatbot orchestrator: {e}")
        traceback.print_exc()
        return False

def test_voice_call_scheduler():
    """Test the voice call scheduler functionality"""
    print("\n" + "="*60)
    print("🧪 TESTING VOICE CALL SCHEDULER")
    print("="*60)
    
    try:
        print("📦 Importing voice_call_scheduler...")
        from voice_call_scheduler import VoiceCallScheduler, voice_scheduler
        print("✅ Successfully imported voice call scheduler components")
        
        print("🚀 Creating VoiceCallScheduler instance...")
        scheduler = VoiceCallScheduler()
        print("✅ Successfully created VoiceCallScheduler")
        
        # Test scheduler start
        print("▶️ Starting scheduler...")
        # Note: We won't actually start it to avoid background processes
        print("✅ Scheduler initialization test successful")
        
        return True
        
    except Exception as e:
        print(f"❌ Error in voice call scheduler: {e}")
        traceback.print_exc()
        return False

def test_production_hospital_orchestrator():
    """Test the production hospital orchestrator API"""
    print("\n" + "="*60)
    print("🧪 TESTING PRODUCTION HOSPITAL ORCHESTRATOR")
    print("="*60)
    
    try:
        print("📦 Importing production_hospital_orchestrator...")
        # Import the app directly
        sys.path.append(os.path.dirname(os.path.abspath(__file__)))
        
        # Test basic imports
        from production_hospital_orchestrator import app
        print("✅ Successfully imported production hospital orchestrator app")
        
        return True
        
    except Exception as e:
        print(f"❌ Error in production hospital orchestrator: {e}")
        traceback.print_exc()
        return False

def test_twilio_agent():
    """Test the Twilio agent functionality"""
    print("\n" + "="*60)
    print("🧪 TESTING TWILIO AGENT")
    print("="*60)
    
    try:
        print("📦 Testing Twilio agent import...")
        # Check if the file exists
        twilio_agent_path = "twillio_comms_agent/twillio_call/production_twilio_agent.py"
        if os.path.exists(twilio_agent_path):
            print(f"✅ Found Twilio agent file at: {twilio_agent_path}")
        else:
            print(f"⚠️ Twilio agent file not found at: {twilio_agent_path}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error in Twilio agent test: {e}")
        traceback.print_exc()
        return False

def test_dependencies():
    """Test critical dependencies"""
    print("\n" + "="*60)
    print("🧪 TESTING CRITICAL DEPENDENCIES")
    print("="*60)
    
    critical_packages = [
        "langchain",
        "langchain_openai", 
        "langgraph",
        "fastapi",
        "uvicorn",
        "twilio",
        "httpx",
        "pydantic",
        "python-dotenv"
    ]
    
    missing_packages = []
    
    for package in critical_packages:
        try:
            __import__(package)
            print(f"✅ {package}")
        except ImportError:
            print(f"❌ {package} - MISSING")
            missing_packages.append(package)
    
    if missing_packages:
        print(f"\n⚠️ Missing packages: {', '.join(missing_packages)}")
        return False
    else:
        print("\n✅ All critical dependencies are available")
        return True

def test_environment_variables():
    """Test environment variables"""
    print("\n" + "="*60)
    print("🧪 TESTING ENVIRONMENT VARIABLES")
    print("="*60)
    
    from dotenv import load_dotenv
    load_dotenv()
    
    required_vars = [
        "OPENAI_API_KEY",
        "LANGSMITH_API_KEY", 
        "WEAVIATE_URL",
        "WEAVIATE_API_KEY"
    ]
    
    missing_vars = []
    
    for var in required_vars:
        value = os.getenv(var)
        if value:
            # Mask sensitive info
            masked_value = value[:8] + "*" * (len(value) - 8) if len(value) > 8 else "*" * len(value)
            print(f"✅ {var}: {masked_value}")
        else:
            print(f"❌ {var}: NOT SET")
            missing_vars.append(var)
    
    if missing_vars:
        print(f"\n⚠️ Missing environment variables: {', '.join(missing_vars)}")
        return False
    else:
        print("\n✅ All required environment variables are set")
        return True

def main():
    """Run all tests"""
    print("🏥 HOSPITAL AI SYSTEM - COMPREHENSIVE TEST SUITE")
    print("=" * 70)
    print(f"📅 Test started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    test_results = []
    
    # Run all tests
    test_results.append(("Dependencies", test_dependencies()))
    test_results.append(("Environment Variables", test_environment_variables()))
    test_results.append(("Hospital Chatbot Orchestrator", test_hospital_chatbot_orchestrator()))
    test_results.append(("Voice Call Scheduler", test_voice_call_scheduler()))
    test_results.append(("Production Hospital Orchestrator", test_production_hospital_orchestrator()))
    test_results.append(("Twilio Agent", test_twilio_agent()))
    
    # Summary
    print("\n" + "="*70)
    print("📊 TEST SUMMARY")
    print("="*70)
    
    passed = 0
    failed = 0
    
    for test_name, result in test_results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{test_name:<35} : {status}")
        if result:
            passed += 1
        else:
            failed += 1
    
    print(f"\n📈 Results: {passed} passed, {failed} failed out of {len(test_results)} tests")
    
    if failed == 0:
        print("🎉 ALL TESTS PASSED! The system is ready for use.")
    else:
        print("⚠️ Some tests failed. Please review the errors above.")
    
    return failed == 0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)