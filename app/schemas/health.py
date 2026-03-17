from pydantic import BaseModel, ConfigDict


class HealthStatus(BaseModel):
    status: str
    service: str

    model_config = ConfigDict(from_attributes=True)


class ReadinessStatus(BaseModel):
    status: str
    checks: dict[str, str]

    model_config = ConfigDict(from_attributes=True)

