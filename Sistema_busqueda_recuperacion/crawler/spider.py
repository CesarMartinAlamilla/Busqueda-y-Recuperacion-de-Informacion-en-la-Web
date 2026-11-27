"""Rastreador web BFS en español para ingesta de documentos HTML hacia Apache Solr."""

from collections import deque
from dataclasses import dataclass, field
import logging
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from crawler.parser import (
    _extract_domain,
    _normalize_url,
    extract_links,
    is_spanish_content,
    parse_html,
)

logger = logging.getLogger(__name__)

HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")


@dataclass
class CrawlResult:
    """Resultado estructurado de una ejecución de rastreo BFS."""

    seed_url: str
    pages_crawled: int = 0
    documents: list[dict] = field(default_factory=list)
    documents_discarded: int = 0
    errors: list[str] = field(default_factory=list)


def _canonical_host(url: str) -> str:
    """Normaliza el dominio removiendo el prefijo 'www.' para comparar sitios equivalentes."""
    return _extract_domain(url).removeprefix("www.")


def _validate_seed_url(seed_url: str) -> str:
    """Valida que la URL semilla sea HTTP/HTTPS y elimina fragmentos."""
    clean = _normalize_url(seed_url)
    parsed = urlparse(clean)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"URL semilla inválida: '{seed_url}'. Debe usar http:// o https://.")
    return clean


def _decode_html_response(response: requests.Response) -> str:
    """Decodifica la respuesta HTML evitando corrupción de tildes y caracteres en español."""
    content_type = response.headers.get("Content-Type", "")
    if "charset=" not in content_type.lower():
        response.encoding = response.apparent_encoding or "utf-8"
    return response.text


class WebSpider:
    """Rastreador HTML en amplitud (BFS) con filtros de dominio, robots.txt e idioma español."""

    def __init__(
        self,
        timeout: int = 10,
        delay: float = 0.25,
        same_domain_only: bool = True,
        min_content_length: int = 50,
        respect_robots: bool = True,
        user_agent: str = "BuscadorES-Bot/1.0 (+https://github.com/CesarMartinAlamilla/Busqueda-y-Recuperacion-de-Informacion-en-la-Web)",
        session: requests.Session | None = None,
    ) -> None:
        self.timeout = timeout
        self.delay = max(0.0, delay)
        self.same_domain_only = same_domain_only
        self.min_content_length = min_content_length
        self.respect_robots = respect_robots
        self.user_agent = user_agent
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = self.user_agent
        self._robots_cache: dict[str, RobotFileParser | None] = {}

    def _is_allowed_by_robots(self, url: str) -> bool:
        """Consulta robots.txt del dominio con caché; ante fallo de red permite continuar."""
        if not self.respect_robots:
            return True

        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._robots_cache:
            robots_url = f"{origin}/robots.txt"
            parser = RobotFileParser()
            try:
                resp = self.session.get(robots_url, timeout=min(self.timeout, 5))
                if resp.status_code == 200:
                    parser.parse(resp.text.splitlines())
                    self._robots_cache[origin] = parser
                else:
                    self._robots_cache[origin] = None
            except requests.RequestException:
                self._robots_cache[origin] = None

        cached = self._robots_cache[origin]
        if cached is None:
            return True
        return cached.can_fetch(self.user_agent, url)

    def _is_same_site(self, url: str, target_host: str) -> bool:
        """Verifica si la URL pertenece al mismo sitio que la semilla."""
        if not self.same_domain_only:
            return True
        return _canonical_host(url) == target_host

    def crawl(
        self,
        seed_url: str,
        max_pages: int = 20,
        max_depth: int = 2,
        category: str = "general",
    ) -> CrawlResult:
        """Ejecuta un rastreo BFS desde seed_url y retorna documentos normalizados para Solr."""
        if max_pages < 1:
            raise ValueError("max_pages debe ser al menos 1.")
        if max_depth < 0:
            raise ValueError("max_depth no puede ser negativo.")

        clean_seed = _validate_seed_url(seed_url)
        allowed_host = _canonical_host(clean_seed)

        result = CrawlResult(seed_url=clean_seed)
        queue: deque[tuple[str, int]] = deque([(clean_seed, 0)])
        visited: set[str] = {clean_seed}
        indexed_ids: set[str] = set()

        while queue and result.pages_crawled < max_pages:
            current_url, depth = queue.popleft()

            if not self._is_allowed_by_robots(current_url):
                result.documents_discarded += 1
                logger.info("URL omitida por robots.txt: %s", current_url)
                continue

            if result.pages_crawled > 0 and self.delay > 0:
                time.sleep(self.delay)

            result.pages_crawled += 1

            try:
                response = self.session.get(current_url, timeout=self.timeout, allow_redirects=True)
            except requests.RequestException as exc:
                result.documents_discarded += 1
                result.errors.append(f"{current_url}: {exc}")
                logger.warning("Error HTTP al rastrear %s: %s", current_url, exc)
                continue

            final_url = _normalize_url(response.url or current_url)
            visited.add(final_url)

            if depth == 0:
                allowed_host = _canonical_host(final_url)

            if response.status_code >= 400:
                result.documents_discarded += 1
                result.errors.append(f"{final_url}: HTTP {response.status_code}")
                continue

            content_type = response.headers.get("Content-Type", "").lower()
            if content_type and not any(ct in content_type for ct in HTML_CONTENT_TYPES):
                result.documents_discarded += 1
                continue

            html_text = _decode_html_response(response)
            doc = parse_html(html_text, final_url, category=category)

            if doc["id"] not in indexed_ids and is_spanish_content(
                html_text,
                doc["content"],
                min_length=self.min_content_length,
            ):
                indexed_ids.add(doc["id"])
                result.documents.append(doc)
            else:
                result.documents_discarded += 1

            if depth < max_depth and self._is_same_site(final_url, allowed_host):
                for link in extract_links(html_text, final_url, same_domain_only=False):
                    if link not in visited and self._is_same_site(link, allowed_host):
                        visited.add(link)
                        queue.append((link, depth + 1))

        return result


def crawl_site(
    seed_url: str,
    max_pages: int = 20,
    max_depth: int = 2,
    category: str = "general",
    **spider_kwargs,
) -> CrawlResult:
    """Atajo funcional para ejecutar un rastreo BFS con WebSpider."""
    spider = WebSpider(**spider_kwargs)
    return spider.crawl(
        seed_url=seed_url,
        max_pages=max_pages,
        max_depth=max_depth,
        category=category,
    )
