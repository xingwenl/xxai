from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    embedding_model: str = Field(min_length=1, max_length=120)
    embedding_base_url: str | None = Field(default=None, max_length=500)
    embedding_api_key: str | None = Field(default=None, min_length=1)
    embedding_dimension: int = Field(ge=1, le=65535)
    chunk_size: int = Field(default=512, ge=32, le=8192)
    chunk_overlap: int = Field(default=50, ge=0, le=2048)


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    embedding_model: str | None = Field(default=None, min_length=1, max_length=120)
    embedding_base_url: str | None = Field(default=None, max_length=500)
    embedding_api_key: str | None = Field(default=None, min_length=1)
    embedding_dimension: int | None = Field(default=None, ge=1, le=65535)
    chunk_size: int | None = Field(default=None, ge=32, le=8192)
    chunk_overlap: int | None = Field(default=None, ge=0, le=2048)


class KnowledgeBaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platform_id: int
    name: str
    slug: str
    embedding_model: str
    embedding_base_url: str | None
    embedding_dimension: int
    active_index_version: int
    chunk_size: int
    chunk_overlap: int
    has_embedding_api_key: bool = False
    created_at: datetime
    updated_at: datetime


class KnowledgeBaseListData(BaseModel):
    page_no: int
    page_size: int
    items: list[KnowledgeBaseRead]
    total: int
    pages: int


class UrlDocumentCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    title: str | None = Field(default=None, max_length=255)


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    knowledge_base_id: int
    source_type: str
    title: str
    source_url: str | None
    media_type: str | None
    status: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class Citation(BaseModel):
    title: str
    source_url: str | None = None
    text: str


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=5, ge=1, le=20)


class KnowledgeSearchResponse(BaseModel):
    citations: list[Citation]


class AgentKnowledgeBaseBind(BaseModel):
    knowledge_base_id: int = Field(ge=1)
    sort_order: int = Field(default=0, ge=0)
