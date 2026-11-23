"""API REST del Sistema de Búsqueda y Recuperación en Español (Contratos Día 2)."""

import os

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
import requests

from api.mocks import mock_crawl, mock_search, mock_suggest
from api.schemas import (
    CrawlRequest,
    CrawlResponse,
    SearchMode,
    SearchResponse,
    SuggestResponse,
)

SOLR_URL = os.getenv("SOLR_URL", "http://solr:8983/solr/buscador_es")

app = FastAPI(
    title="Sistema de Búsqueda y Recuperación en Español",
    description="API REST para búsqueda ponderada/booleana, autocompletado, facetas e ingesta.",
    version="0.2.0",
)


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    """Interfaz mínima temporal hasta implementar templates/index.html en el Día 4."""
    html = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <title>Buscador Web en Español — API</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 720px; margin: 3rem auto; padding: 0 1rem; color: #1f2937; }
    a { color: #2563eb; text-decoration: none; font-weight: 600; }
    code { background: #f3f4f6; padding: 0.15rem 0.4rem; border-radius: 4px; }
  </style>
</head>
<body>
  <h1>Sistema de Búsqueda y Recuperación en Español</h1>
  <p>Contratos REST activos (Día 2 con datos simulados). La interfaz web completa se integrará en el Día 4.</p>
  <ul>
    <li>Documentación interactiva: <a href="/docs">/docs</a></li>
    <li>Estado del servicio y Solr: <a href="/health">/health</a></li>
    <li>Ejemplo búsqueda: <code>/api/search?q=inteligencia&amp;mode=weighted</code></li>
    <li>Ejemplo sugerencias: <code>/api/suggest?prefix=int</code></li>
  </ul>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.get("/health")
def health() -> dict:
    """Verifica disponibilidad del servicio web y conexión con Solr."""
    solr_ping_url = f"{SOLR_URL.rstrip('/')}/admin/ping"
    try:
        resp = requests.get(solr_ping_url, timeout=3)
        solr_status = resp.json().get("status", "UNKNOWN") if resp.ok else f"HTTP {resp.status_code}"
    except requests.RequestException as exc:
        solr_status = f"UNREACHABLE: {exc}"

    return {
        "status": "ok",
        "solr_url": SOLR_URL,
        "solr_status": solr_status,
    }


@app.get("/api/search", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=1, description="Consulta de búsqueda en español."),
    mode: SearchMode = Query(
        default="weighted",
        description="Modo de búsqueda: weighted (relevancia ponderada) o boolean.",
    ),
    fq: list[str] | None = Query(
        default=None,
        description="Filtros facetados en formato campo:valor (ej. domain_s:ciencia.gob.mx).",
    ),
    rows: int = Query(default=10, ge=1, le=100, description="Cantidad de resultados por página."),
    start: int = Query(default=0, ge=0, description="Desplazamiento inicial para paginación."),
) -> SearchResponse:
    """Ejecuta búsqueda en español con facetas, snippets y sugerencia ortográfica."""
    try:
        return mock_search(q=q, mode=mode, fq=fq, rows=rows, start=start)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/suggest", response_model=SuggestResponse)
def suggest(
    prefix: str = Query(..., min_length=1, description="Prefijo o subcadena para autocompletado."),
    limit: int = Query(default=10, ge=1, le=20, description="Número máximo de sugerencias."),
) -> SuggestResponse:
    """Retorna sugerencias de llenado para la barra de búsqueda."""
    return mock_suggest(prefix=prefix, limit=limit)


@app.post("/api/crawl", response_model=CrawlResponse)
def crawl(payload: CrawlRequest) -> CrawlResponse:
    """Inicia un rastreo HTML desde una URL semilla (contrato simulado en Día 2)."""
    return mock_crawl(payload)
