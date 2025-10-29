from typing import Optional
from pydantic import BaseModel

class GPXUploadResponse(BaseModel):
    success: bool
    message: str
    city: Optional[str] = None
    role: Optional[str] = None
