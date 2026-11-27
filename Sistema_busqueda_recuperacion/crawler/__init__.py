"""Módulo de ingesta y rastreo web para el Sistema de Búsqueda en Español."""

from crawler.parser import extract_links, is_spanish_content, parse_html
from crawler.spider import CrawlResult, WebSpider, crawl_site

__all__ = [
    "CrawlResult",
    "WebSpider",
    "crawl_site",
    "extract_links",
    "is_spanish_content",
    "parse_html",
]
