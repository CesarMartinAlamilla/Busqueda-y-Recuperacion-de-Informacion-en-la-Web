"""Indexador por lotes hacia Apache Solr 10 con ID determinista SHA-256 y validación de contrato."""

from dataclasses import dataclass, field
import hashlib
import logging
import os
from typing import Iterable
from urllib.parse import urlparse

import requests

from crawler.parser import _normalize_url

logger = logging.getLogger(__name__)

DEFAULT_SOLR_URL = "http://solr:8983/solr/buscador_es"
DEFAULT_BATCH_SIZE = 25

CONTRACT_FIELDS = (
    "id",
    "title",
    "content",
    "url",
    "domain_s",
    "category_s",
    "doc_type_s",
    "published_at_dt",
)

REQUIRED_NON_EMPTY_FIELDS = (
    "url",
    "title",
    "content",
    "domain_s",
    "category_s",
    "doc_type_s",
    "published_at_dt",
)


@dataclass
class IndexResult:
    """Resumen estructurado de una ejecución de indexación por lotes en Solr."""

    total_received: int = 0
    documents_indexed: int = 0
    documents_discarded: int = 0
    batches_sent: int = 0
    batches_failed: int = 0
    suggest_rebuilt: bool = False
    errors: list[str] = field(default_factory=list)
    discarded_reasons: list[str] = field(default_factory=list)
    indexed_ids: list[str] = field(default_factory=list)


def compute_doc_id(url: str) -> str:
    """Genera un identificador determinista SHA-256 a partir de la URL normalizada."""
    clean_url = _normalize_url(url)
    parsed = urlparse(clean_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"URL inválida para generar ID: '{url}'.")
    return hashlib.sha256(clean_url.encode("utf-8")).hexdigest()


def _clean_text_field(value: object) -> str:
    """Normaliza un valor a cadena limpia sin espacios extremos."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).strip()


def prepare_solr_document(doc: dict) -> tuple[dict | None, str | None]:
    """Valida campos requeridos no vacíos y normaliza un documento al esquema oficial de Solr."""
    if not isinstance(doc, dict):
        return None, "El documento no es un diccionario válido."

    raw_url = doc.get("url")
    if not isinstance(raw_url, str) or not raw_url.strip():
        return None, "Campo obligatorio 'url' vacío o ausente."

    try:
        clean_url = _normalize_url(raw_url)
        doc_id = compute_doc_id(clean_url)
    except ValueError as exc:
        return None, str(exc)

    normalized: dict[str, str] = {
        "id": doc_id,
        "url": clean_url,
    }

    for field_name in REQUIRED_NON_EMPTY_FIELDS:
        if field_name == "url":
            continue
        cleaned = _clean_text_field(doc.get(field_name))
        if not cleaned:
            return None, f"Documento '{clean_url}' descartado: campo '{field_name}' vacío o ausente."
        normalized[field_name] = cleaned

    return normalized, None


def _chunk_documents(documents: list[dict], batch_size: int) -> Iterable[list[dict]]:
    """Divide una lista de documentos en lotes de tamaño fijo."""
    for start in range(0, len(documents), batch_size):
        yield documents[start : start + batch_size]


class SolrIndexer:
    """Cliente de ingesta por lotes hacia Apache Solr 10 (/update y /suggest)."""

    def __init__(
        self,
        solr_url: str | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        timeout: int = 15,
        rebuild_suggest: bool = True,
        session: requests.Session | None = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size debe ser al menos 1.")
        if timeout <= 0:
            raise ValueError("timeout debe ser mayor que 0.")

        resolved_url = solr_url or os.getenv("SOLR_URL") or DEFAULT_SOLR_URL
        self.solr_url = resolved_url.rstrip("/")
        self.batch_size = batch_size
        self.timeout = timeout
        self.rebuild_suggest = rebuild_suggest
        self.session = session or requests.Session()

    def _post_batch(self, batch: list[dict], commit: bool = True) -> tuple[bool, str | None]:
        """Envía un lote de documentos JSON a {SOLR_URL}/update manejando errores HTTP y de red."""
        update_url = f"{self.solr_url}/update"
        params = {"commit": "true"} if commit else None

        try:
            response = self.session.post(
                update_url,
                params=params,
                json=batch,
                headers={"Content-Type": "application/json; charset=utf-8", "Accept": "application/json"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            msg = f"Error de conexión al enviar lote a {update_url}: {exc}"
            logger.error(msg)
            return False, msg

        if response.status_code >= 400:
            detail = _extract_solr_error(response)
            msg = f"HTTP {response.status_code} en {update_url}: {detail}"
            logger.error(msg)
            return False, msg

        try:
            payload = response.json()
        except ValueError:
            return True, None

        solr_status = payload.get("responseHeader", {}).get("status", 0)
        if solr_status != 0:
            error_msg = payload.get("error", {}).get("msg", f"status={solr_status}")
            msg = f"Respuesta de error de Solr en {update_url}: {error_msg}"
            logger.error(msg)
            return False, msg

        return True, None

    def rebuild_suggester(self) -> tuple[bool, str | None]:
        """Reconstruye el diccionario de autocompletado en {SOLR_URL}/suggest."""
        suggest_url = f"{self.solr_url}/suggest"
        params = {"suggest": "true", "suggest.build": "true", "wt": "json"}
        try:
            response = self.session.get(suggest_url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            msg = f"No se pudo reconstruir /suggest en {suggest_url}: {exc}"
            logger.warning(msg)
            return False, msg

        if response.status_code >= 400:
            detail = _extract_solr_error(response)
            msg = f"HTTP {response.status_code} al reconstruir /suggest: {detail}"
            logger.warning(msg)
            return False, msg

        return True, None

    def count_documents(self, query: str = "*:*") -> int:
        """Consulta el conteo actual de documentos en Solr mediante /select."""
        select_url = f"{self.solr_url}/select"
        try:
            response = self.session.get(
                select_url,
                params={"q": query, "rows": 0, "wt": "json"},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"Error de conexión consultando {select_url}: {exc}") from exc

        if response.status_code >= 400:
            detail = _extract_solr_error(response)
            raise RuntimeError(f"HTTP {response.status_code} consultando {select_url}: {detail}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Respuesta JSON inválida desde {select_url}: {exc}") from exc

        return int(payload.get("response", {}).get("numFound", 0))

    def index_documents(
        self,
        documents: Iterable[dict],
        commit: bool = True,
        rebuild_suggest: bool | None = None,
    ) -> IndexResult:
        """Valida, deduplica por SHA-256 de URL e indexa documentos en Solr en lotes."""
        result = IndexResult()
        valid_docs: list[dict] = []
        seen_ids: set[str] = set()

        for raw_doc in documents:
            result.total_received += 1
            prepared, reason = prepare_solr_document(raw_doc)
            if prepared is None:
                result.documents_discarded += 1
                if reason:
                    result.discarded_reasons.append(reason)
                continue

            doc_id = prepared["id"]
            if doc_id in seen_ids:
                result.documents_discarded += 1
                result.discarded_reasons.append(
                    f"Documento duplicado en el mismo lote descartado: '{prepared['url']}'."
                )
                continue

            seen_ids.add(doc_id)
            valid_docs.append(prepared)

        for batch in _chunk_documents(valid_docs, self.batch_size):
            result.batches_sent += 1
            ok, err_msg = self._post_batch(batch, commit=commit)
            if ok:
                result.documents_indexed += len(batch)
                result.indexed_ids.extend(doc["id"] for doc in batch)
            else:
                result.batches_failed += 1
                result.documents_discarded += len(batch)
                if err_msg:
                    result.errors.append(err_msg)

        should_rebuild = self.rebuild_suggest if rebuild_suggest is None else rebuild_suggest
        if should_rebuild and result.documents_indexed > 0:
            rebuilt, suggest_err = self.rebuild_suggester()
            result.suggest_rebuilt = rebuilt
            if not rebuilt and suggest_err:
                result.errors.append(suggest_err)

        logger.info(
            "Resumen indexación Solr (%s): recibidos=%d, indexados=%d, descartados=%d, "
            "lotes=%d (fallidos=%d), suggest_rebuilt=%s",
            self.solr_url,
            result.total_received,
            result.documents_indexed,
            result.documents_discarded,
            result.batches_sent,
            result.batches_failed,
            result.suggest_rebuilt,
        )
        return result


def _extract_solr_error(response: requests.Response) -> str:
    """Extrae un mensaje legible desde una respuesta HTTP de error de Solr."""
    try:
        data = response.json()
        msg = data.get("error", {}).get("msg")
        if msg:
            return str(msg)
    except ValueError:
        pass
    text = response.text.strip()
    return text[:300] if text else "Sin detalle adicional"


def index_documents(
    documents: Iterable[dict],
    solr_url: str | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    commit: bool = True,
    rebuild_suggest: bool = True,
    **indexer_kwargs,
) -> IndexResult:
    """Atajo funcional para indexar documentos en Solr usando SolrIndexer."""
    indexer = SolrIndexer(
        solr_url=solr_url,
        batch_size=batch_size,
        rebuild_suggest=rebuild_suggest,
        **indexer_kwargs,
    )
    return indexer.index_documents(documents, commit=commit, rebuild_suggest=rebuild_suggest)
