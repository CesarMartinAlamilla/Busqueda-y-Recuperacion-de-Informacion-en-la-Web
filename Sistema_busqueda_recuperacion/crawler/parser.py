"""Limpiador DOM, extractor de metadatos HTML y normalizador para Apache Solr 10."""

from datetime import datetime, timezone
import os
import re
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup, Comment, FeatureNotFound

NOISE_TAGS = (
    "script",
    "style",
    "nav",
    "footer",
    "header",
    "noscript",
    "aside",
    "svg",
    "iframe",
    "template",
    "canvas",
    "button",
    "input",
    "select",
    "textarea",
)

NOISE_SELECTORS = (
    "[role='navigation']",
    "[role='banner']",
    "[role='search']",
    "[role='complementary']",
    "[role='contentinfo']",
    "[aria-hidden='true']",
    "[hidden]",
    ".noprint",
    ".mw-editsection",
    ".mw-jump-link",
    ".mw-indicators",
    ".catlinks",
    ".printfooter",
    ".vector-page-toolbar",
    ".vector-column-start",
    ".vector-column-end",
    ".ambox",
    "#siteSub",
    "#contentSub",
    "sup.reference",
)

NON_HTML_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
    ".css",
    ".js",
    ".json",
    ".xml",
    ".zip",
    ".rar",
    ".tar",
    ".gz",
    ".mp3",
    ".mp4",
    ".avi",
    ".mov",
}

SPANISH_FUNCTION_WORDS = {
    "el",
    "la",
    "los",
    "las",
    "un",
    "una",
    "unos",
    "unas",
    "de",
    "del",
    "al",
    "en",
    "y",
    "o",
    "que",
    "es",
    "son",
    "por",
    "para",
    "con",
    "como",
    "se",
    "su",
    "sus",
    "más",
    "mas",
    "pero",
    "sobre",
    "entre",
    "esta",
    "este",
}


def _make_soup(html: str) -> BeautifulSoup:
    """Construye un árbol BeautifulSoup usando lxml con respaldo a html.parser."""
    content = html if isinstance(html, str) else ""
    try:
        return BeautifulSoup(content, "lxml")
    except FeatureNotFound:
        return BeautifulSoup(content, "html.parser")


def _normalize_whitespace(text: str) -> str:
    """Colapsa espacios múltiples y corrige espaciado alrededor de signos de puntuación."""
    collapsed = " ".join(text.split())
    collapsed = re.sub(r"\s+([,.;:!?%)\]}»])", r"\1", collapsed)
    collapsed = re.sub(r"([(\[{«¿¡])\s+", r"\1", collapsed)
    return collapsed


def _normalize_url(url: str) -> str:
    """Valida y limpia una URL removiendo espacios y fragmentos (#)."""
    if not isinstance(url, str) or not url.strip():
        raise ValueError("La URL del documento no puede estar vacía.")
    clean_url, _ = urldefrag(url.strip())
    return clean_url


def _extract_domain(url: str) -> str:
    """Obtiene el dominio normalizado en minúsculas a partir de la URL."""
    parsed = urlparse(url)
    return (parsed.hostname or parsed.netloc).lower()


def _extract_title(soup: BeautifulSoup, fallback_url: str) -> str:
    """Extrae el título antes de limpiar etiquetas estructurales como <header>."""
    if soup.title:
        title_text = _normalize_whitespace(soup.title.get_text(" ", strip=True))
        if title_text:
            return title_text

    for meta_attrs in ({"property": "og:title"}, {"name": "twitter:title"}, {"name": "title"}):
        meta_tag = soup.find("meta", attrs=meta_attrs)
        if meta_tag and meta_tag.get("content"):
            meta_title = _normalize_whitespace(str(meta_tag["content"]))
            if meta_title:
                return meta_title

    h1_tag = soup.find("h1")
    if h1_tag:
        h1_text = _normalize_whitespace(h1_tag.get_text(" ", strip=True))
        if h1_text:
            return h1_text

    return fallback_url


def _parse_iso_datetime(raw_value: str) -> str | None:
    """Convierte una fecha ISO-8601 a formato UTC compatible con Solr."""
    candidate = raw_value.strip()
    if not candidate:
        return None
    if candidate.endswith(("Z", "z")):
        candidate = f"{candidate[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def _extract_published_at(soup: BeautifulSoup) -> str:
    """Extrae la fecha de publicación desde metadatos HTML o usa la fecha UTC actual."""
    meta_candidates = (
        {"property": "article:published_time"},
        {"property": "og:published_time"},
        {"name": "pubdate"},
        {"name": "publishdate"},
        {"name": "date"},
        {"name": "DC.date.issued"},
    )
    for attrs in meta_candidates:
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            iso_date = _parse_iso_datetime(str(tag["content"]))
            if iso_date:
                return iso_date

    time_tag = soup.find("time", attrs={"datetime": True})
    if time_tag:
        iso_date = _parse_iso_datetime(str(time_tag["datetime"]))
        if iso_date:
            return iso_date

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean_dom_node(node: BeautifulSoup) -> str:
    """Elimina comentarios, etiquetas de ruido y selectores de interfaz en un nodo DOM."""
    for comment in node.find_all(string=lambda item: isinstance(item, Comment)):
        comment.extract()

    for selector in NOISE_SELECTORS:
        for tag in node.select(selector):
            if tag.parent is not None:
                tag.decompose()

    for tag in node.find_all(NOISE_TAGS):
        if tag.parent is not None:
            tag.decompose()

    raw_text = node.get_text(separator=" ", strip=True)
    return _normalize_whitespace(raw_text)


def _extract_clean_content(soup: BeautifulSoup) -> str:
    """Elimina ruido del DOM priorizando <main>/<article> y extrae texto legible."""
    if soup.head is not None:
        soup.head.decompose()

    main_tag = soup.find("main")
    if main_tag is not None:
        text = _clean_dom_node(main_tag)
        if len(text) >= 50:
            return text

    articles = soup.find_all("article")
    if len(articles) == 1:
        text = _clean_dom_node(articles[0])
        if len(text) >= 50:
            return text

    target = soup.body if soup.body is not None else soup
    return _clean_dom_node(target)


def extract_links(html: str, base_url: str, same_domain_only: bool = False) -> list[str]:
    """Extrae y normaliza enlaces HTTP/HTTPS válidos desde un documento HTML."""
    if not html or not base_url:
        return []

    clean_base = _normalize_url(base_url)
    base_domain = _extract_domain(clean_base)
    soup = _make_soup(html)

    links: list[str] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"]).strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
            continue

        resolved, _ = urldefrag(urljoin(clean_base, href))
        parsed = urlparse(resolved)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue

        ext = os.path.splitext(parsed.path.lower())[1]
        if ext in NON_HTML_EXTENSIONS:
            continue

        if same_domain_only and _extract_domain(resolved) != base_domain:
            continue

        if resolved not in seen:
            seen.add(resolved)
            links.append(resolved)

    return links


def is_spanish_content(html: str, text: str, min_length: int = 50) -> bool:
    """Valida si un documento tiene contenido suficiente y está en español."""
    if not text or len(text.strip()) < min_length:
        return False

    soup = _make_soup(html)
    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang"):
        raw_lang = str(html_tag["lang"]).strip().lower()
        primary_lang = raw_lang.split("-")[0].split("_")[0]
        if primary_lang:
            return primary_lang == "es"

    tokens = re.findall(r"[a-záéíóúüñ]+", text.lower())
    if len(tokens) < 5:
        return False

    spanish_hits = sum(1 for token in tokens if token in SPANISH_FUNCTION_WORDS)
    return spanish_hits >= 2 and (spanish_hits / len(tokens)) >= 0.08


def parse_html(html: str, url: str, category: str = "general") -> dict:
    """Extrae título y texto limpio de un HTML y lo normaliza al esquema de Solr."""
    clean_url = _normalize_url(url)
    soup = _make_soup(html)

    # Extraer metadatos antes de descomponer etiquetas como <header> o <head>
    title = _extract_title(soup, clean_url)
    published_at = _extract_published_at(soup)
    clean_content = _extract_clean_content(soup)

    clean_category = _normalize_whitespace(category) if isinstance(category, str) else ""

    return {
        "id": clean_url,
        "title": title,
        "content": clean_content,
        "url": clean_url,
        "domain_s": _extract_domain(clean_url),
        "category_s": clean_category or "general",
        "doc_type_s": "html",
        "published_at_dt": published_at,
    }
