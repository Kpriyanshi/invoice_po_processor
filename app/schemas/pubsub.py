from pydantic import BaseModel, Field


class PubSubMessage(BaseModel):
    data: str = ''
    message_id: str | None = Field(default=None, alias='messageId')

    model_config = {'populate_by_name': True}


class PubSubEnvelope(BaseModel):
    message: PubSubMessage = Field(default_factory=PubSubMessage)


class StatusResponse(BaseModel):
    status: str
