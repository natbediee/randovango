from typing import Optional
from pydantic import BaseModel

class GPXUploadResponse(BaseModel):
    success: bool
    message: str
    city: Optional[str] = None
    role: Optional[str] = None

class GPXDeleteResponse(BaseModel):
    success: bool
    message: str
    deleted_file: Optional[str] = None
