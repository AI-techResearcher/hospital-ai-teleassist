"""
FAISS RAG Integration for Hospital Chatbot
Uses existing FAISS vector store with doctor profile embeddings
"""

from pathlib import Path
from typing import List, Dict, Any, Optional
import json

try:
    from langchain_community.vectorstores import FAISS
    from langchain_core.documents import Document
except ImportError as e:
    raise ImportError("Missing required packages: langchain-community. Please install with 'pip install langchain-community faiss-cpu'") from e

class FAISSRAGIntegration:
    """Integration wrapper for FAISS-based RAG functionality"""
    
    def __init__(self, faiss_dir: str = ".faiss_index"):
        self.faiss_dir = Path(faiss_dir)
        self.store = None
        self.retriever = None
        self.available = False
        self._setup_faiss()
    
    def _setup_faiss(self):
        """Initialize FAISS vector store and retriever"""
        try:
            if not self.faiss_dir.exists():
                print(f"⚠️ FAISS index not found at {self.faiss_dir}")
                print("Run 'python ingest_doctors_Faiss.py' to create the index first")
                return
            
            # Import the embedding adapter from the existing code
            from ingest_doctors_Faiss import LCEmbeddingAdapter
            
            print(f"📚 Loading FAISS index from {self.faiss_dir}...")
            embed = LCEmbeddingAdapter()
            
            # Load the FAISS store
            self.store = FAISS.load_local(
                str(self.faiss_dir), 
                embed, 
                allow_dangerous_deserialization=True
            )
            
            # Create retriever with good defaults
            self.retriever = self.store.as_retriever(
                search_type="mmr",  # Use Maximal Marginal Relevance for diverse results
                search_kwargs={
                    "k": 5,
                    "fetch_k": 20,  # Fetch more candidates for MMR
                    "lambda_mult": 0.7  # Balance between similarity and diversity
                }
            )
            
            self.available = True
            print("✅ FAISS RAG system initialized successfully")
            
        except Exception as e:
            print(f"❌ FAISS initialization failed: {e}")
            self.available = False
    
    def search_knowledge(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Search the FAISS knowledge base and return formatted results"""
        if not self.available or not self.retriever:
            return [{
                "content": "Knowledge search temporarily unavailable. FAISS index not loaded.",
                "source": "System",
                "score": 0.0,
                "metadata": {}
            }]
        
        try:
            # Update retriever for this query
            self.retriever.search_kwargs["k"] = top_k
            
            # Get relevant documents (invoke replaces deprecated get_relevant_documents)
            docs = self.retriever.invoke(query)
            
            results = []
            for doc in docs:
                # Extract meaningful information from metadata
                metadata = doc.metadata or {}
                
                # Create a readable source identifier
                source = self._format_source(metadata)
                
                # Format the content for better readability
                content = self._format_content(doc.page_content, metadata)
                
                results.append({
                    "content": content,
                    "source": source,
                    "score": metadata.get("score", 0.0),
                    "metadata": metadata
                })
            
            return results
            
        except Exception as e:
            print(f"Knowledge search error: {e}")
            return [{
                "content": f"Search error: {str(e)}",
                "source": "System",
                "score": 0.0,
                "metadata": {}
            }]
    
    def _format_source(self, metadata: Dict[str, Any]) -> str:
        """Format source information from metadata"""
        full_name = metadata.get("full_name", "")
        specialty = metadata.get("specialty", "")
        section = metadata.get("section", "")
        
        if full_name and specialty:
            return f"Dr. {full_name} ({specialty})"
        elif full_name:
            return f"Dr. {full_name}"
        elif specialty:
            return f"{specialty} Department"
        elif section:
            return section
        else:
            return "Hospital Database"
    
    def _format_content(self, content: str, metadata: Dict[str, Any]) -> str:
        """Format content for better readability"""
        if not content.strip():
            return "No detailed information available."
        
        # Clean up the content
        content = content.strip()
        
        # If it's very short, might be just metadata - enhance it
        if len(content) < 50 and metadata:
            enhanced_content = []
            
            full_name = metadata.get("full_name", "")
            specialty = metadata.get("specialty", "")
            experience = metadata.get("experience", "")
            languages = metadata.get("languages", "")
            designation = metadata.get("designation", "")
            
            if full_name:
                enhanced_content.append(f"Doctor: {full_name}")
            if specialty:
                enhanced_content.append(f"Specialty: {specialty}")
            if designation:
                enhanced_content.append(f"Designation: {designation}")
            if experience:
                enhanced_content.append(f"Experience: {experience}")
            if languages:
                enhanced_content.append(f"Languages: {languages}")
            
            if enhanced_content:
                return "\n".join(enhanced_content) + f"\n\nDetails: {content}"
        
        return content
    
    def get_doctor_profile(self, doctor_name: str) -> Optional[Dict[str, Any]]:
        """Get specific doctor profile by name"""
        if not self.available:
            return None
        
        try:
            # Search for the specific doctor
            results = self.search_knowledge(f"Dr. {doctor_name} doctor profile", top_k=3)
            
            # Find the best match by doctor name
            for result in results:
                metadata = result.get("metadata", {})
                if doctor_name.lower() in metadata.get("full_name", "").lower():
                    return {
                        "name": metadata.get("full_name", doctor_name),
                        "specialty": metadata.get("specialty", ""),
                        "designation": metadata.get("designation", ""),
                        "experience": metadata.get("experience", ""),
                        "languages": metadata.get("languages", ""),
                        "profile": result["content"],
                        "source": result["source"]
                    }
            
            return None
            
        except Exception as e:
            print(f"Error getting doctor profile: {e}")
            return None
    
    def search_by_specialty(self, specialty: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Search doctors by specialty"""
        query = f"{specialty} specialist doctor cardiologist"
        return self.search_knowledge(query, top_k)
    
    def get_all_specialties(self) -> List[str]:
        """Get list of all available specialties"""
        if not self.available:
            return []
        
        try:
            # This is a simple approach - in production you might cache this
            all_docs = self.search_knowledge("specialty doctor", top_k=50)
            specialties = set()
            
            for doc in all_docs:
                specialty = doc.get("metadata", {}).get("specialty", "")
                if specialty and specialty.strip():
                    specialties.add(specialty.strip())
            
            return sorted(list(specialties))
            
        except Exception as e:
            print(f"Error getting specialties: {e}")
            return []
    
    def health_check(self) -> Dict[str, Any]:
        """Check the health of the FAISS system"""
        status = {
            "available": self.available,
            "faiss_dir_exists": self.faiss_dir.exists(),
            "store_loaded": self.store is not None,
            "retriever_ready": self.retriever is not None
        }
        
        if self.available:
            try:
                # Test with a simple query
                test_results = self.search_knowledge("doctor", top_k=1)
                status["test_query_success"] = len(test_results) > 0
                status["index_size"] = len(test_results)
            except Exception as e:
                status["test_query_success"] = False
                status["error"] = str(e)
        
        return status

def test_faiss_integration():
    """Test the FAISS integration"""
    print("🧪 Testing FAISS RAG Integration")
    print("=" * 40)
    
    # Initialize integration
    faiss_rag = FAISSRAGIntegration()
    
    # Health check
    health = faiss_rag.health_check()
    print("Health Check:")
    for key, value in health.items():
        print(f"  {key}: {value}")
    
    if not faiss_rag.available:
        print("❌ FAISS system not available. Please run 'python ingest_doctors_Faiss.py' first.")
        return
    
    print("\n" + "=" * 40)
    
    # Test queries
    test_queries = [
        "cardiologist doctor",
        "Arabic speaking doctor",
        "pediatric specialist",
        "emergency medicine"
    ]
    
    for query in test_queries:
        print(f"\n🔍 Query: '{query}'")
        results = faiss_rag.search_knowledge(query, top_k=2)
        
        for i, result in enumerate(results, 1):
            print(f"  {i}. {result['source']}")
            content_preview = result['content'][:100] + "..." if len(result['content']) > 100 else result['content']
            print(f"     {content_preview}")
    
    # Test specialty search
    print(f"\n🏥 Available Specialties:")
    specialties = faiss_rag.get_all_specialties()
    for specialty in specialties[:10]:  # Show first 10
        print(f"  - {specialty}")
    
    print(f"\n✅ FAISS integration test completed!")

if __name__ == "__main__":
    test_faiss_integration()
