from pydantic import BaseModel
from typing import List
    
    
class DocVerifierRequest(BaseModel):
    query: List[dict]


class DocVerifierResponse(BaseModel):
    response: List[dict]
    
    
class DocUploadResponse(BaseModel):
    url: str 
    ranking: int