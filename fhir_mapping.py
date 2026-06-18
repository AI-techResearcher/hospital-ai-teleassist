"""
FHIR R4 Resource Mapping for Hospital Chatbot
Supports both native FHIR server and FHIR-shaped JSON local mode
"""

from typing import Dict, Any, List, Optional, Union
from datetime import datetime, timezone
from pydantic import BaseModel, Field
import uuid
import json
# Configuration flag for FHIR mode
USE_NATIVE_FHIR = False  # Set to True for production FHIR server

# FHIR Resource Models (Pydantic for validation)

class FHIRIdentifier(BaseModel):
    use: Optional[str] = None
    type: Optional[Dict[str, Any]] = None
    system: Optional[str] = None
    value: str

class FHIRCodeableConcept(BaseModel):
    coding: Optional[List[Dict[str, Any]]] = None
    text: Optional[str] = None

class FHIRReference(BaseModel):
    reference: Optional[str] = None
    display: Optional[str] = None

class FHIRPeriod(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None

# Doctor Profile to FHIR Practitioner Mapping
class FHIRPractitioner(BaseModel):
    resourceType: str = "Practitioner"
    id: str
    identifier: List[FHIRIdentifier] = []
    active: bool = True
    name: List[Dict[str, Any]] = []
    telecom: List[Dict[str, Any]] = []
    address: List[Dict[str, Any]] = []
    gender: Optional[str] = None
    birthDate: Optional[str] = None
    photo: List[Dict[str, Any]] = []
    qualification: List[Dict[str, Any]] = []
    communication: List[FHIRCodeableConcept] = []

class FHIRPractitionerRole(BaseModel):
    resourceType: str = "PractitionerRole"
    id: str
    identifier: List[FHIRIdentifier] = []
    active: bool = True
    period: Optional[FHIRPeriod] = None
    practitioner: Optional[FHIRReference] = None
    organization: Optional[FHIRReference] = None
    code: List[FHIRCodeableConcept] = []
    specialty: List[FHIRCodeableConcept] = []
    location: List[FHIRReference] = []
    healthcareService: List[FHIRReference] = []
    telecom: List[Dict[str, Any]] = []
    availableTime: List[Dict[str, Any]] = []
    notAvailable: List[Dict[str, Any]] = []
    availabilityExceptions: Optional[str] = None

# Appointment Resources
class FHIRAppointment(BaseModel):
    resourceType: str = "Appointment"
    id: str
    identifier: List[FHIRIdentifier] = []
    status: str  # proposed | pending | booked | arrived | fulfilled | cancelled | noshow | entered-in-error | checked-in | waitlist
    cancellationReason: Optional[FHIRCodeableConcept] = None
    serviceCategory: List[FHIRCodeableConcept] = []
    serviceType: List[FHIRCodeableConcept] = []
    specialty: List[FHIRCodeableConcept] = []
    appointmentType: Optional[FHIRCodeableConcept] = None
    reasonCode: List[FHIRCodeableConcept] = []
    reasonReference: List[FHIRReference] = []
    priority: Optional[int] = None
    description: Optional[str] = None
    supportingInformation: List[FHIRReference] = []
    start: Optional[str] = None
    end: Optional[str] = None
    minutesDuration: Optional[int] = None
    slot: List[FHIRReference] = []
    created: Optional[str] = None
    comment: Optional[str] = None
    patientInstruction: Optional[str] = None
    basedOn: List[FHIRReference] = []
    participant: List[Dict[str, Any]] = []
    requestedPeriod: List[FHIRPeriod] = []

class FHIRSlot(BaseModel):
    resourceType: str = "Slot"
    id: str
    identifier: List[FHIRIdentifier] = []
    serviceCategory: List[FHIRCodeableConcept] = []
    serviceType: List[FHIRCodeableConcept] = []
    specialty: List[FHIRCodeableConcept] = []
    appointmentType: Optional[FHIRCodeableConcept] = None
    schedule: FHIRReference
    status: str  # busy | free | busy-unavailable | busy-tentative | entered-in-error
    start: str
    end: str
    overbooked: Optional[bool] = None
    comment: Optional[str] = None

class FHIRSchedule(BaseModel):
    resourceType: str = "Schedule"
    id: str
    identifier: List[FHIRIdentifier] = []
    active: Optional[bool] = None
    serviceCategory: List[FHIRCodeableConcept] = []
    serviceType: List[FHIRCodeableConcept] = []
    specialty: List[FHIRCodeableConcept] = []
    actor: List[FHIRReference] = []
    planningHorizon: Optional[FHIRPeriod] = None
    comment: Optional[str] = None

# Transformation Functions

def doctor_json_to_fhir_practitioner(doctor_data: Dict[str, Any]) -> FHIRPractitioner:
    """Transform doctor JSON to FHIR Practitioner resource"""
    
    practitioner_id = doctor_data.get("practitioner_id") or f"pract_{uuid.uuid4().hex[:8]}"
    
    # Parse name
    full_name = doctor_data.get("full_name", "")
    name_parts = full_name.replace("Dr. ", "").split()
    given_names = name_parts[:-1] if len(name_parts) > 1 else []
    family_name = name_parts[-1] if name_parts else ""
    
    # Parse languages
    languages_str = doctor_data.get("LANGUAGES", "")
    languages = [lang.strip() for lang in languages_str.split(",") if lang.strip()]
    
    # Create qualifications
    qualifications = []
    for qual in doctor_data.get("qualifications", []):
        qualifications.append({
            "identifier": [{"value": f"qual_{uuid.uuid4().hex[:8]}"}],
            "code": {
                "coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0360", "code": "MD"}],
                "text": qual
            },
            "period": {"start": "1995-01-01"},  # Would extract from qualification text
            "issuer": {"display": "University"}  # Would extract from qualification text
        })
    
    # Create communication
    communication = []
    for lang in languages:
        communication.append(FHIRCodeableConcept(
            coding=[{
                "system": "urn:ietf:bcp:47",
                "code": lang.lower()[:2],  # ISO 639-1 language code
                "display": lang
            }],
            text=lang
        ))
    
    return FHIRPractitioner(
        id=practitioner_id,
        identifier=[
            FHIRIdentifier(
                use="usual",
                system="http://hospital.example.com/practitioner-id",
                value=practitioner_id
            )
        ],
        name=[{
            "use": "official",
            "family": family_name,
            "given": given_names,
            "prefix": ["Dr."]
        }],
        qualification=qualifications,
        communication=communication
    )

def doctor_json_to_fhir_practitioner_role(doctor_data: Dict[str, Any], practitioner_id: str) -> FHIRPractitionerRole:
    """Transform doctor JSON to FHIR PractitionerRole resource"""
    
    role_id = f"role_{uuid.uuid4().hex[:8]}"
    specialty = doctor_data.get("SPECIALTY", "General Medicine")
    
    # Map specialty to SNOMED CT codes (simplified mapping)
    specialty_mapping = {
        "General Surgery": {"code": "394609007", "display": "General surgery"},
        "Cardiology": {"code": "394579002", "display": "Cardiology"},
        "Orthopedics": {"code": "394801008", "display": "Trauma and orthopedics"},
        "Dermatology": {"code": "394582007", "display": "Dermatology"},
        "Neurology": {"code": "394591006", "display": "Neurology"}
    }
    
    specialty_coding = specialty_mapping.get(specialty, {
        "code": "394802001", 
        "display": "General medicine"
    })
    
    # Create available time slots (business hours)
    available_time = [
        {
            "daysOfWeek": ["mon", "tue", "wed", "thu", "fri"],
            "availableStartTime": "09:00:00",
            "availableEndTime": "17:00:00"
        }
    ]
    
    return FHIRPractitionerRole(
        id=role_id,
        identifier=[
            FHIRIdentifier(
                use="usual",
                system="http://hospital.example.com/practitioner-role-id",
                value=role_id
            )
        ],
        practitioner=FHIRReference(
            reference=f"Practitioner/{practitioner_id}",
            display=doctor_data.get("full_name", "")
        ),
        organization=FHIRReference(
            reference="Organization/hospital-main",
            display="Main Hospital"
        ),
        code=[FHIRCodeableConcept(
            coding=[{
                "system": "http://terminology.hl7.org/CodeSystem/practitioner-role",
                "code": "doctor",
                "display": "Doctor"
            }],
            text=doctor_data.get("DESIGNATION", "Doctor")
        )],
        specialty=[FHIRCodeableConcept(
            coding=[{
                "system": "http://snomed.info/sct",
                "code": specialty_coding["code"],
                "display": specialty_coding["display"]
            }],
            text=specialty
        )],
        location=[FHIRReference(
            reference="Location/main-campus",
            display="Main Campus"
        )],
        availableTime=available_time
    )

def create_fhir_appointment(
    patient_id: str,
    practitioner_id: str,
    slot_id: str,
    start_time: str,
    end_time: str,
    reason: str,
    notes: Optional[str] = None
) -> FHIRAppointment:
    """Create FHIR Appointment resource"""
    
    appointment_id = f"appt_{uuid.uuid4().hex[:8]}"
    
    # Calculate duration
    start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
    end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
    duration = int((end_dt - start_dt).total_seconds() / 60)
    
    return FHIRAppointment(
        id=appointment_id,
        identifier=[
            FHIRIdentifier(
                use="usual",
                system="http://hospital.example.com/appointment-id",
                value=appointment_id
            )
        ],
        status="booked",
        serviceCategory=[FHIRCodeableConcept(
            coding=[{
                "system": "http://terminology.hl7.org/CodeSystem/service-category",
                "code": "17",
                "display": "General Practice"
            }],
            text="General Practice"
        )],
        serviceType=[FHIRCodeableConcept(
            text=reason
        )],
        appointmentType=FHIRCodeableConcept(
            coding=[{
                "system": "http://terminology.hl7.org/CodeSystem/v2-0276",
                "code": "ROUTINE",
                "display": "Routine appointment"
            }],
            text="Routine appointment"
        ),
        reasonCode=[FHIRCodeableConcept(text=reason)],
        description=notes,
        start=start_time,
        end=end_time,
        minutesDuration=duration,
        slot=[FHIRReference(reference=f"Slot/{slot_id}")],
        created=datetime.now(timezone.utc).isoformat(),
        comment=notes,
        participant=[
            {
                "actor": {
                    "reference": f"Patient/{patient_id}",
                    "display": "Patient"
                },
                "required": "required",
                "status": "accepted"
            },
            {
                "actor": {
                    "reference": f"Practitioner/{practitioner_id}",
                    "display": "Doctor"
                },
                "required": "required",
                "status": "accepted"
            }
        ]
    )

def create_fhir_slot(
    schedule_id: str,
    start_time: str,
    end_time: str,
    status: str = "free"
) -> FHIRSlot:
    """Create FHIR Slot resource"""
    
    slot_id = f"slot_{uuid.uuid4().hex[:8]}"
    
    return FHIRSlot(
        id=slot_id,
        identifier=[
            FHIRIdentifier(
                use="usual",
                system="http://hospital.example.com/slot-id",
                value=slot_id
            )
        ],
        serviceCategory=[FHIRCodeableConcept(
            coding=[{
                "system": "http://terminology.hl7.org/CodeSystem/service-category",
                "code": "17",
                "display": "General Practice"
            }],
            text="General Practice"
        )],
        schedule=FHIRReference(reference=f"Schedule/{schedule_id}"),
        status=status,
        start=start_time,
        end=end_time
    )

# FHIR Client Abstraction

class FHIRClient:
    """Abstract FHIR client supporting both native FHIR and local JSON storage"""
    
    def __init__(self, use_native_fhir: bool = False):
        self.use_native_fhir = use_native_fhir
        self.local_storage = {}  # For non-FHIR mode
    
    async def create_resource(self, resource: Union[FHIRPractitioner, FHIRAppointment, FHIRSlot]) -> Dict[str, Any]:
        """Create a FHIR resource"""
        if self.use_native_fhir:
            return await self._create_native_fhir_resource(resource)
        else:
            return await self._create_local_resource(resource)
    
    async def read_resource(self, resource_type: str, resource_id: str) -> Optional[Dict[str, Any]]:
        """Read a FHIR resource"""
        if self.use_native_fhir:
            return await self._read_native_fhir_resource(resource_type, resource_id)
        else:
            return await self._read_local_resource(resource_type, resource_id)
    
    async def update_resource(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        """Update a FHIR resource"""
        if self.use_native_fhir:
            return await self._update_native_fhir_resource(resource)
        else:
            return await self._update_local_resource(resource)
    
    async def search_resources(self, resource_type: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Search FHIR resources"""
        if self.use_native_fhir:
            return await self._search_native_fhir_resources(resource_type, params)
        else:
            return await self._search_local_resources(resource_type, params)
    
    # Native FHIR Server Methods
    async def _create_native_fhir_resource(self, resource: BaseModel) -> Dict[str, Any]:
        """Create resource on native FHIR server"""
        import httpx
        
        # Convert Pydantic model to dict
        resource_dict = resource.model_dump(exclude_none=True)
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.fhir_base_url}/{resource.resourceType}",
                json=resource_dict,
                headers={"Content-Type": "application/fhir+json"}
            )
            response.raise_for_status()
            return response.json()
    
    async def _read_native_fhir_resource(self, resource_type: str, resource_id: str) -> Optional[Dict[str, Any]]:
        """Read resource from native FHIR server"""
        import httpx
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.fhir_base_url}/{resource_type}/{resource_id}",
                headers={"Accept": "application/fhir+json"}
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
    
    # Local Storage Methods
    async def _create_local_resource(self, resource: BaseModel) -> Dict[str, Any]:
        """Create resource in local storage"""
        resource_dict = resource.model_dump(exclude_none=True)
        resource_type = resource.resourceType
        resource_id = resource.id
        
        if resource_type not in self.local_storage:
            self.local_storage[resource_type] = {}
        
        self.local_storage[resource_type][resource_id] = resource_dict
        return resource_dict
    
    async def _read_local_resource(self, resource_type: str, resource_id: str) -> Optional[Dict[str, Any]]:
        """Read resource from local storage"""
        return self.local_storage.get(resource_type, {}).get(resource_id)
    
    async def _search_local_resources(self, resource_type: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Search resources in local storage"""
        resources = self.local_storage.get(resource_type, {}).values()
        
        # Simple filtering based on params
        filtered_resources = []
        for resource in resources:
            matches = True
            for key, value in params.items():
                if key == "practitioner" and "participant" in resource:
                    # Check appointment participants
                    participant_match = any(
                        p.get("actor", {}).get("reference") == f"Practitioner/{value}"
                        for p in resource.get("participant", [])
                    )
                    if not participant_match:
                        matches = False
                        break
                elif key == "date" and "start" in resource:
                    # Check date range
                    resource_date = resource["start"][:10]  # Extract date part
                    if resource_date != value:
                        matches = False
                        break
            
            if matches:
                filtered_resources.append(resource)
        
        return filtered_resources

# Example Usage
async def example_fhir_usage():
    """Example of using FHIR resources"""
    
    # Initialize FHIR client
    fhir_client = FHIRClient(use_native_fhir=USE_NATIVE_FHIR)
    
    # Sample doctor data
    doctor_data = {
        "practitioner_id": "pract_001",
        "full_name": "Dr. Salma Saad",
        "DESIGNATION": "Consultant General Surgeon",
        "SPECIALTY": "General Surgery",
        "EXPERIENCE": "10 years",
        "LANGUAGES": "English, Urdu, Arabic",
        "qualifications": [
            "MD in General Surgery, University of Khartoum, 2002"
        ]
    }
    
    # Create FHIR Practitioner
    practitioner = doctor_json_to_fhir_practitioner(doctor_data)
    await fhir_client.create_resource(practitioner)
    
    # Create FHIR PractitionerRole
    practitioner_role = doctor_json_to_fhir_practitioner_role(doctor_data, practitioner.id)
    await fhir_client.create_resource(practitioner_role)
    
    # Create FHIR Appointment
    appointment = create_fhir_appointment(
        patient_id="patient_123",
        practitioner_id=practitioner.id,
        slot_id="slot_456",
        start_time="2024-12-20T14:00:00Z",
        end_time="2024-12-20T14:30:00Z",
        reason="Consultation for abdominal pain"
    )
    await fhir_client.create_resource(appointment)
    
    # Search appointments
    appointments = await fhir_client.search_resources("Appointment", {
        "practitioner": practitioner.id,
        "date": "2024-12-20"
    })
    
    return {
        "practitioner": practitioner.model_dump(),
        "practitioner_role": practitioner_role.model_dump(), 
        "appointment": appointment.model_dump(),
        "search_results": appointments
    }

if __name__ == "__main__":
    import asyncio
    result = asyncio.run(example_fhir_usage())
    print(json.dumps(result, indent=2))
