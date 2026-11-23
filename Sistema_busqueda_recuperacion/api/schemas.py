"""Esquemas Pydantic y contratos REST de la API del sistema de búsqueda."""

from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, Field

SearchMode = Literal["weighted", "boolean"]


class FacetItem(BaseModel):
    """Elemento individual de una faceta con su conteo de documentos."""

    value: str = Field(..., description="Valor de la faceta.")
    count: int = Field(..., ge=0, description="Cantidad de documentos coincidentes.")


class SearchFacets(BaseModel):
    """Facetas dinámicas alineadas al esquema del ADR."""

    domain_s: list[FacetItem] = Field(default_factory=list)
    category_s: list[FacetItem] = Field(default_factory=list)
    doc_type_s: list[FacetItem] = Field(default_factory=list)


class SearchResultItem(BaseModel):
    """Documento retornado en los resultados de búsqueda."""

    id: str
    title: str
    url: str
    domain_s: str
    category_s: str
    doc_type_s: str
    published_at_dt: str
    score: float = Field(..., ge=0.0)
    snippet: str


class SearchResponse(BaseModel):
    """Contrato de respuesta para GET /api/search."""

    query: str
    mode: SearchMode
    total: int = Field(..., ge=0)
    elapsed_ms: int = Field(..., ge=0)
    results: list[SearchResultItem] = Field(default_factory=list)
    facets: SearchFacets = Field(default_factory=SearchFacets)
    did_you_mean: str | None = None


class SuggestResponse(BaseModel):
    """Contrato de respuesta para GET /api/suggest."""

    prefix: str
    suggestions: list[str] = Field(default_factory=list)


class CrawlRequest(BaseModel):
    """Contrato de entrada para POST /api/crawl."""

    seed_url: AnyHttpUrl = Field(..., description="URL semilla inicial en español.")
    max_pages: int = Field(default=20, ge=1, le=200, description="Máximo de páginas a rastrear.")
    max_depth: int = Field(default=2, ge=0, le=5, description="Profundidad máxima de rastreo BFS.")


class CrawlResponse(BaseModel):
    """Contrato de respuesta para POST /api/crawl."""

    status: str
    seed_url: str
    max_pages: int
    max_depth: int
    pages_crawled: int = Field(..., ge=0)
    documents_indexed: int = Field(..., ge=0)
    documents_discarded: int = Field(..., ge=0)
    message: str
