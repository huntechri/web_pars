from datetime import datetime
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    username: str


class CategoryNode(BaseModel):
    code: str | int | None = None
    title: str = ""
    children: list["CategoryNode"] = Field(default_factory=list)


class StartParseRequest(BaseModel):
    selected_categories: list[dict] = Field(default_factory=list)
    max_products_per_cat: int | None = None


class ParseJobResponse(BaseModel):
    id: str
    status: str
    output_file: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


CategoryNode.model_rebuild()
