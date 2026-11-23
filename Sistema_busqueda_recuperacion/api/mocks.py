"""Mocks realistas en memoria para probar los contratos REST durante el Día 2."""

from collections import Counter
import re
import time
import unicodedata

from api.schemas import (
    CrawlRequest,
    CrawlResponse,
    FacetItem,
    SearchFacets,
    SearchMode,
    SearchResponse,
    SearchResultItem,
    SuggestResponse,
)

ALLOWED_FACET_FIELDS = {"domain_s", "category_s", "doc_type_s"}

MOCK_DOCUMENTS: list[dict] = [
    {
        "id": "doc-001",
        "title": "Inteligencia artificial y recuperación de información en español",
        "content": (
            "Los sistemas modernos de recuperación de información combinan análisis "
            "morfológico, n-gramas y modelos probabilísticos para mejorar la relevancia "
            "en documentos académicos y portales web en español."
        ),
        "url": "https://revista.unam.mx/inteligencia-artificial-recuperacion",
        "domain_s": "revista.unam.mx",
        "category_s": "Tecnología",
        "doc_type_s": "html",
        "published_at_dt": "2026-10-15T12:00:00Z",
    },
    {
        "id": "doc-002",
        "title": "Guía práctica de Apache Solr 10 y búsqueda facetada",
        "content": (
            "Apache Solr permite configurar cadenas de análisis con trigramas, "
            "sinónimos en español, facetas dinámicas y resaltado contextual de fragmentos "
            "mediante parámetros eDisMax."
        ),
        "url": "https://docs.tecnologia.org/solr-10-facetas",
        "domain_s": "docs.tecnologia.org",
        "category_s": "Tecnología",
        "doc_type_s": "html",
        "published_at_dt": "2026-11-02T09:30:00Z",
    },
    {
        "id": "doc-003",
        "title": "Energía limpia y automóviles eléctricos en ciudades latinoamericanas",
        "content": (
            "El despliegue de vehículos y coches eléctricos reduce las emisiones urbanas "
            "cuando se combina con redes de electricidad renovable e infraestructura "
            "inteligente de recarga."
        ),
        "url": "https://ciencia.gob.mx/energia-vehiculos-electricos",
        "domain_s": "ciencia.gob.mx",
        "category_s": "Ciencia",
        "doc_type_s": "html",
        "published_at_dt": "2026-09-20T16:45:00Z",
    },
    {
        "id": "doc-004",
        "title": "Manual técnico de procesamiento de lenguaje natural con trigramas",
        "content": (
            "El uso de trigramas de caracteres facilita la tolerancia a errores "
            "tipográficos y la búsqueda aproximada en corpus multilingües sin depender "
            "exclusivamente de diccionarios estáticos."
        ),
        "url": "https://repositorio.academico.edu/manual-nlp-trigramas.pdf",
        "domain_s": "repositorio.academico.edu",
        "category_s": "Académico",
        "doc_type_s": "pdf",
        "published_at_dt": "2026-08-11T10:15:00Z",
    },
    {
        "id": "doc-005",
        "title": "Arquitectura de microservicios web con FastAPI y contenedores Docker",
        "content": (
            "Contenedorizar servicios Python junto con motores de búsqueda garantiza "
            "entornos reproducibles, contratos REST claros y exportación estructurada "
            "en formatos JSON y XML."
        ),
        "url": "https://ingenieria.dev/arquitectura-fastapi-docker.docx",
        "domain_s": "ingenieria.dev",
        "category_s": "Ingeniería",
        "doc_type_s": "docx",
        "published_at_dt": "2026-11-10T14:20:00Z",
    },
    {
        "id": "doc-006",
        "title": "Innovación en tecnología educativa para bibliotecas digitales",
        "content": (
            "Las bibliotecas y catálogos universitarios integran buscadores con "
            "autocompletado en vivo y expansión semántica para localizar artículos "
            "científicos con mayor precisión."
        ),
        "url": "https://ciencia.gob.mx/tecnologia-bibliotecas-digitales",
        "domain_s": "ciencia.gob.mx",
        "category_s": "Educación",
        "doc_type_s": "html",
        "published_at_dt": "2026-10-28T08:00:00Z",
    },
]

SUGGEST_PHRASES: list[str] = [
    "inteligencia artificial",
    "recuperación de información",
    "tecnología educativa",
    "trigramas en español",
    "apache solr facetas",
    "automóviles eléctricos",
    "energía limpia",
    "arquitectura fastapi docker",
    "bibliotecas digitales",
    "procesamiento de lenguaje natural",
]

# Vocabulario con tildes correctas para simular sugerencias ortográficas por trigramas.
MOCK_VOCABULARY: list[str] = [
    "inteligencia",
    "artificial",
    "recuperación",
    "información",
    "tecnología",
    "trigramas",
    "energía",
    "automóviles",
    "eléctricos",
    "bibliotecas",
    "arquitectura",
    "procesamiento",
    "lenguaje",
    "búsqueda",
    "facetada",
]


def _normalize(text: str) -> str:
    """Convierte a minúsculas y remueve diacríticos para comparación aproximada."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def _trigrams(word: str) -> set[str]:
    """Genera trigramas con padding para similitud aproximada."""
    padded = f"  {word}  "
    if len(padded) < 3:
        return {padded}
    return {padded[i : i + 3] for i in range(len(padded) - 2)}


def _trigram_similarity(a: str, b: str) -> float:
    """Calcula similitud de Jaccard sobre trigramas normalizados."""
    ta = _trigrams(_normalize(a))
    tb = _trigrams(_normalize(b))
    union = ta | tb
    if not union:
        return 0.0
    return len(ta & tb) / len(union)


def _parse_fq_filters(fq_list: list[str] | None) -> list[tuple[str, str]]:
    """Valida y parsea parámetros fq en pares (campo, valor)."""
    if not fq_list:
        return []
    parsed: list[tuple[str, str]] = []
    for raw_filter in fq_list:
        if ":" not in raw_filter:
            raise ValueError(f"Filtro facetado inválido '{raw_filter}'. Usa formato campo:valor.")
        field, value = raw_filter.split(":", 1)
        field = field.strip()
        value = value.strip().strip('"')
        if field not in ALLOWED_FACET_FIELDS or not value:
            raise ValueError(
                f"Campo o valor de faceta no permitido en '{raw_filter}'. "
                f"Campos válidos: {', '.join(sorted(ALLOWED_FACET_FIELDS))}."
            )
        parsed.append((field, value))
    return parsed


def _validate_parentheses(query: str) -> None:
    """Verifica balanceo de paréntesis para consultas booleanas."""
    depth = 0
    for ch in query:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                raise ValueError("Paréntesis desbalanceados en la consulta booleana.")
    if depth != 0:
        raise ValueError("Paréntesis sin cerrar en la consulta booleana.")


def _matches_boolean(doc: dict, query: str) -> tuple[bool, list[str]]:
    """Evalúa una consulta booleana (AND, OR, NOT y paréntesis) sin usar eval."""
    _validate_parentheses(query)
    haystack = _normalize(f"{doc['title']} {doc['category_s']} {doc['content']}")
    cleaned = query.replace("(", " ( ").replace(")", " ) ")
    raw_tokens = cleaned.split()
    if not raw_tokens:
        raise ValueError("La consulta booleana no puede estar vacía.")

    terms: list[str] = []
    pos = 0

    def peek() -> str | None:
        return raw_tokens[pos] if pos < len(raw_tokens) else None

    def consume() -> str:
        nonlocal pos
        tok = raw_tokens[pos]
        pos += 1
        return tok

    def parse_or() -> bool:
        left = parse_and()
        while (tok := peek()) is not None and tok.upper() == "OR":
            consume()
            right = parse_and()
            left = left or right
        return left

    def parse_and() -> bool:
        left = parse_not()
        while (tok := peek()) is not None and tok.upper() == "AND":
            consume()
            right = parse_not()
            left = left and right
        return left

    def parse_not() -> bool:
        if (tok := peek()) is not None and tok.upper() == "NOT":
            consume()
            return not parse_not()
        return parse_primary()

    def parse_primary() -> bool:
        tok = peek()
        if tok is None:
            raise ValueError("Sintaxis booleana incompleta: falta un término después del operador.")
        if tok == "(":
            consume()
            val = parse_or()
            if peek() != ")":
                raise ValueError("Paréntesis sin cerrar en la consulta booleana.")
            consume()
            return val
        if tok == ")" or tok.upper() in {"AND", "OR"}:
            raise ValueError(f"Token inesperado '{tok}' en la consulta booleana.")
        consume()
        norm_tok = _normalize(tok.strip('"'))
        if not norm_tok:
            raise ValueError("Término vacío en la consulta booleana.")
        terms.append(norm_tok)
        return norm_tok in haystack

    matched = parse_or()
    if pos != len(raw_tokens):
        raise ValueError(f"Sintaxis booleana inválida cerca de '{raw_tokens[pos]}'.")
    return matched, terms


def _score_weighted(doc: dict, query: str) -> tuple[float, list[str]]:
    """Simula puntuación eDisMax (title^3.5, category_s^2.0, content^1.0)."""
    norm_terms = [t for t in re.findall(r"\w+", _normalize(query)) if len(t) > 1]
    if not norm_terms:
        norm_terms = [_normalize(query.strip())]

    title_norm = _normalize(doc["title"])
    cat_norm = _normalize(doc["category_s"])
    content_norm = _normalize(doc["content"])

    score = 0.0
    for term in norm_terms:
        if term in title_norm:
            score += 3.5
        if term in cat_norm:
            score += 2.0
        if term in content_norm:
            score += 1.0
    return round(score, 2), norm_terms


def _highlight_text(text: str, terms: list[str]) -> tuple[str, bool]:
    """Aplica etiquetas <mark> a coincidencias normalizadas; indica si hubo resaltado."""
    words = text.split(" ")
    matched = False
    highlighted: list[str] = []
    valid_terms = [t for t in sorted(set(terms), key=len, reverse=True) if len(t) >= 2]
    for word in words:
        norm_word = _normalize(word)
        if any(term in norm_word for term in valid_terms):
            highlighted.append(f"<mark>{word}</mark>")
            matched = True
        else:
            highlighted.append(word)
    return " ".join(highlighted), matched


def _build_snippet(title: str, content: str, terms: list[str], max_len: int = 180) -> str:
    """Genera un fragmento contextual con etiquetas <mark> para términos coincidentes."""
    excerpt = content[:max_len].rstrip()
    if len(content) > max_len:
        excerpt = f"{excerpt}..."

    highlighted_content, content_matched = _highlight_text(excerpt, terms)
    if content_matched or not terms:
        return highlighted_content

    highlighted_title, title_matched = _highlight_text(title, terms)
    if title_matched:
        return f"{highlighted_title} — {excerpt}"
    return highlighted_content


def _suggest_spelling(query: str) -> str | None:
    """Sugiere corrección ortográfica usando similitud por trigramas."""
    tokens = re.findall(r"\w+", query)
    if not tokens:
        return None
    corrected_tokens: list[str] = []
    changed = False
    for token in tokens:
        best_word = token
        best_sim = 0.0
        norm_tok = _normalize(token)
        for vocab_word in MOCK_VOCABULARY:
            if norm_tok == _normalize(vocab_word):
                best_word = vocab_word
                best_sim = 1.0
                break
            sim = _trigram_similarity(token, vocab_word)
            if sim > best_sim:
                best_sim = sim
                best_word = vocab_word
        if best_sim >= 0.35 and _normalize(best_word) != norm_tok:
            corrected_tokens.append(best_word)
            changed = True
        else:
            corrected_tokens.append(token)
    return " ".join(corrected_tokens) if changed else None


def mock_search(
    q: str,
    mode: SearchMode,
    fq: list[str] | None,
    rows: int,
    start: int,
) -> SearchResponse:
    """Ejecuta una búsqueda simulada respetando el contrato REST del Día 2."""
    t0 = time.perf_counter()
    clean_q = q.strip()
    if not clean_q:
        raise ValueError("El parámetro de búsqueda 'q' no puede estar vacío.")

    filters = _parse_fq_filters(fq)

    matched_items: list[tuple[float, dict, list[str]]] = []
    for doc in MOCK_DOCUMENTS:
        if any(doc.get(field) != value for field, value in filters):
            continue

        if clean_q == "*:*":
            matched_items.append((1.0, doc, []))
            continue

        if mode == "boolean":
            is_match, terms = _matches_boolean(doc, clean_q)
            if is_match:
                matched_items.append((1.0, doc, terms))
        else:
            score, terms = _score_weighted(doc, clean_q)
            if score > 0:
                matched_items.append((score, doc, terms))

    matched_items.sort(key=lambda item: item[0], reverse=True)

    domain_counts = Counter(item[1]["domain_s"] for item in matched_items)
    category_counts = Counter(item[1]["category_s"] for item in matched_items)
    doc_type_counts = Counter(item[1]["doc_type_s"] for item in matched_items)

    facets = SearchFacets(
        domain_s=[FacetItem(value=k, count=v) for k, v in domain_counts.most_common()],
        category_s=[FacetItem(value=k, count=v) for k, v in category_counts.most_common()],
        doc_type_s=[FacetItem(value=k, count=v) for k, v in doc_type_counts.most_common()],
    )

    page = matched_items[start : start + rows]
    results = [
        SearchResultItem(
            id=doc["id"],
            title=doc["title"],
            url=doc["url"],
            domain_s=doc["domain_s"],
            category_s=doc["category_s"],
            doc_type_s=doc["doc_type_s"],
            published_at_dt=doc["published_at_dt"],
            score=score,
            snippet=_build_snippet(doc["title"], doc["content"], terms),
        )
        for score, doc, terms in page
    ]

    did_you_mean = _suggest_spelling(clean_q) if len(matched_items) == 0 and clean_q != "*:*" else None
    elapsed_ms = max(1, int((time.perf_counter() - t0) * 1000))

    return SearchResponse(
        query=clean_q,
        mode=mode,
        total=len(matched_items),
        elapsed_ms=elapsed_ms,
        results=results,
        facets=facets,
        did_you_mean=did_you_mean,
    )


def mock_suggest(prefix: str, limit: int = 10) -> SuggestResponse:
    """Retorna sugerencias de autocompletado (prefijo o infijo normalizado)."""
    clean_prefix = prefix.strip()
    norm_prefix = _normalize(clean_prefix)
    if len(norm_prefix) < 2:
        return SuggestResponse(prefix=clean_prefix, suggestions=[])

    starts_with = [p for p in SUGGEST_PHRASES if _normalize(p).startswith(norm_prefix)]
    contains = [
        p
        for p in SUGGEST_PHRASES
        if norm_prefix in _normalize(p) and p not in starts_with
    ]
    suggestions = (starts_with + contains)[:limit]
    return SuggestResponse(prefix=clean_prefix, suggestions=suggestions)


def mock_crawl(payload: CrawlRequest) -> CrawlResponse:
    """Simula la respuesta de un rastreo HTML e indexación en lotes."""
    simulated_crawled = min(payload.max_pages, 12)
    return CrawlResponse(
        status="simulated",
        seed_url=str(payload.seed_url),
        max_pages=payload.max_pages,
        max_depth=payload.max_depth,
        pages_crawled=simulated_crawled,
        documents_indexed=simulated_crawled,
        documents_discarded=0,
        message=(
            f"Simulación de rastreo completada ({simulated_crawled} páginas) "
            "en espera de conectar crawler/spider.py y crawler/indexer.py en Día 3."
        ),
    )
