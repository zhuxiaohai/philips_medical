from pydantic import BaseModel
from typing import List
    
    
class DocVerifierRequest(BaseModel):
    url: str
    ranking: int = 1
    
    
class DocUploadResponse(BaseModel):
    url: str 
    ranking: int