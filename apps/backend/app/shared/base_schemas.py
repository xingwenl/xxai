from datetime import datetime

from pydantic import BaseModel, field_serializer


class TimeSchemas(BaseModel):
    @field_serializer("created_at", "updated_at", check_fields=False)
    def serialize_datetime(self, value: datetime) -> str:
        return value.strftime("%Y-%m-%d %H:%M:%S")
