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
    product_qty: int = 0
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


class ParseResultRowResponse(BaseModel):
    id: int
    article: str | None = None
    name: str = ""
    unit: str | None = None
    price: str | None = None
    brand: str | None = None
    weight: str | None = None
    level1: str | None = None
    level2: str | None = None
    level3: str | None = None
    level4: str | None = None
    level5: str | None = None
    level6: str | None = None
    image: str | None = None
    url: str | None = None
    supplier: str | None = None


class ParseJobResultsResponse(BaseModel):
    job_id: str
    total: int
    limit: int
    offset: int
    items: list[ParseResultRowResponse] = Field(default_factory=list)


class ParseJobProgressResponse(BaseModel):
    status: str
    progress_percent: int = 0
    products_collected: int = 0
    categories_done: int = 0
    categories_total: int = 0


CategoryNode.model_rebuild()
