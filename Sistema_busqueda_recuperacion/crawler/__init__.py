"""Módulo de ingesta y rastreo web para el Sistema de Búsqueda en Español."""

from crawler.indexer import IndexResult, SolrIndexer, compute_doc_id, index_documents, prepare_solr_document
from crawler.parser import extract_links, is_spanish_content, parse_html
from crawler.spider import CrawlResult, WebSpider, crawl_site

__all__ = [
    "CrawlResult",
    "IndexResult",
    "PipelineResult",
    "SolrIndexer",
    "WebSpider",
    "compute_doc_id",
    "crawl_site",
    "extract_links",
    "index_documents",
    "is_spanish_content",
    "parse_html",
    "prepare_solr_document",
    "run_crawl_pipeline",
]


def __getattr__(name: str):
    """Carga diferida de pipeline para evitar RuntimeWarning al ejecutar `python -m crawler.pipeline`."""
    if name in {"PipelineResult", "run_crawl_pipeline"}:
        from crawler import pipeline

        return getattr(pipeline, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
