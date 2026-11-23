"""Aplicación FastAPI temporal para verificación base del contenedor web."""

import os

import requests
from fastapi import FastAPI

SOLR_URL = os.getenv("SOLR_URL", "http://solr:8983/solr/buscador_es")

app = FastAPI(
    title="Sistema de Búsqueda y Recuperación en Español",
    version="0.1.0",
)


@app.get("/")
def root() -> dict:
    """Endpoint raíz temporal."""
    return {
        "service": "buscador-web",
        "status": "running",
        "solr_url": SOLR_URL,
    }


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
