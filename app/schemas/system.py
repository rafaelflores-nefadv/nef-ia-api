from pydantic import BaseModel


class SystemInfoResponse(BaseModel):
    app_name: str
    environment: str
    api_prefix: str
    queue_backend: str
    storage_path: str

