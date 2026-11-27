"""Pipeline de ingesta end-to-end: rastreo HTML (WebSpider) e indexación en Solr (SolrIndexer)."""

import argparse
from dataclasses import dataclass, field
import logging
import sys
from typing import Sequence

from crawler.indexer import DEFAULT_BATCH_SIZE, IndexResult, SolrIndexer, compute_doc_id
from crawler.spider import WebSpider

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Resumen consolidado de rastreo e indexación en Solr."""

    seed_urls: list[str]
    max_pages: int
    max_depth: int
    pages_crawled: int = 0
    documents_extracted: int = 0
    documents_indexed: int = 0
    documents_discarded: int = 0
    batches_sent: int = 0
    batches_failed: int = 0
    suggest_rebuilt: bool = False
    solr_total_count: int | None = None
    errors: list[str] = field(default_factory=list)

    def to_crawl_response_dict(self) -> dict:
        """Retorna un diccionario compatible con el contrato CrawlResponse de la API."""
        has_fatal_error = self.documents_indexed == 0 and bool(self.errors)
        status = "error" if has_fatal_error else ("partial" if self.errors else "ok")
        seed_label = self.seed_urls[0] if self.seed_urls else ""
        return {
            "status": status,
            "seed_url": seed_label,
            "max_pages": self.max_pages,
            "max_depth": self.max_depth,
            "pages_crawled": self.pages_crawled,
            "documents_indexed": self.documents_indexed,
            "documents_discarded": self.documents_discarded,
            "message": (
                f"Rastreo completado: {self.pages_crawled} páginas visitadas, "
                f"{self.documents_indexed} documentos indexados, "
                f"{self.documents_discarded} descartados."
            ),
        }


def _normalize_seeds(seed_urls: str | Sequence[str]) -> list[str]:
    """Normaliza una URL semilla o secuencia de semillas a una lista no vacía."""
    if isinstance(seed_urls, str):
        seeds = [seed_urls.strip()] if seed_urls.strip() else []
    else:
        seeds = [str(url).strip() for url in seed_urls if isinstance(url, str) and url.strip()]

    if not seeds:
        raise ValueError("Debe proporcionar al menos una URL semilla.")
    return seeds


def run_crawl_pipeline(
    seed_urls: str | Sequence[str],
    max_pages: int = 50,
    max_depth: int = 2,
    category: str = "general",
    solr_url: str | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    delay: float = 0.25,
    timeout: int = 10,
    same_domain_only: bool = True,
    respect_robots: bool = True,
    verify_count: bool = True,
    spider: WebSpider | None = None,
    indexer: SolrIndexer | None = None,
) -> PipelineResult:
    """Ejecuta WebSpider sobre una o varias semillas e indexa los resultados en Apache Solr."""
    if max_pages < 1:
        raise ValueError("max_pages debe ser al menos 1.")
    if max_depth < 0:
        raise ValueError("max_depth no puede ser negativo.")

    seeds = _normalize_seeds(seed_urls)
    active_spider = spider or WebSpider(
        timeout=timeout,
        delay=delay,
        same_domain_only=same_domain_only,
        respect_robots=respect_robots,
    )
    active_indexer = indexer or SolrIndexer(
        solr_url=solr_url,
        batch_size=batch_size,
    )

    pipeline_result = PipelineResult(
        seed_urls=seeds,
        max_pages=max_pages,
        max_depth=max_depth,
    )

    collected_docs: list[dict] = []
    seen_doc_ids: set[str] = set()
    crawl_discarded = 0

    for seed in seeds:
        remaining_budget = max_pages - pipeline_result.pages_crawled
        if remaining_budget <= 0:
            break

        try:
            crawl_res = active_spider.crawl(
                seed_url=seed,
                max_pages=remaining_budget,
                max_depth=max_depth,
                category=category,
            )
        except Exception as exc:
            msg = f"Error al rastrear semilla '{seed}': {exc}"
            logger.error(msg)
            pipeline_result.errors.append(msg)
            continue

        pipeline_result.pages_crawled += crawl_res.pages_crawled
        crawl_discarded += crawl_res.documents_discarded
        pipeline_result.errors.extend(crawl_res.errors)

        for doc in crawl_res.documents:
            url = doc.get("url", "")
            try:
                doc_id = compute_doc_id(url)
            except ValueError:
                crawl_discarded += 1
                continue

            if doc_id in seen_doc_ids:
                crawl_discarded += 1
                continue

            seen_doc_ids.add(doc_id)
            doc_copy = dict(doc)
            doc_copy["id"] = doc_id
            collected_docs.append(doc_copy)

    pipeline_result.documents_extracted = len(collected_docs)

    index_res = IndexResult()
    if collected_docs:
        index_res = active_indexer.index_documents(collected_docs, commit=True)
    else:
        logger.info("No se extrajeron documentos válidos para indexar en Solr.")

    pipeline_result.documents_indexed = index_res.documents_indexed
    pipeline_result.documents_discarded = crawl_discarded + index_res.documents_discarded
    pipeline_result.batches_sent = index_res.batches_sent
    pipeline_result.batches_failed = index_res.batches_failed
    pipeline_result.suggest_rebuilt = index_res.suggest_rebuilt
    pipeline_result.errors.extend(index_res.errors)

    if verify_count:
        try:
            pipeline_result.solr_total_count = active_indexer.count_documents("*:*")
        except RuntimeError as exc:
            pipeline_result.errors.append(str(exc))

    logger.info(
        "Resumen pipeline: semillas=%d, paginas=%d, extraidos=%d, indexados=%d, "
        "descartados=%d, solr_total=%s",
        len(seeds),
        pipeline_result.pages_crawled,
        pipeline_result.documents_extracted,
        pipeline_result.documents_indexed,
        pipeline_result.documents_discarded,
        pipeline_result.solr_total_count,
    )
    return pipeline_result


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ejecuta el rastreo HTML en español y la indexación por lotes en Solr."
    )
    parser.add_argument(
        "--seed",
        dest="seeds",
        action="append",
        required=True,
        help="URL semilla en español (puede repetirse múltiples veces).",
    )
    parser.add_argument("--max-pages", type=int, default=50, help="Máximo total de páginas a visitar.")
    parser.add_argument("--max-depth", type=int, default=2, help="Profundidad máxima BFS.")
    parser.add_argument("--category", default="general", help="Categoría asignada en Solr (category_s).")
    parser.add_argument("--solr-url", default=None, help="URL base del core Solr (default: SOLR_URL).")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Tamaño de lote para /update.")
    parser.add_argument("--delay", type=float, default=0.2, help="Espera entre peticiones HTTP en segundos.")
    parser.add_argument(
        "--allow-external-domains",
        action="store_true",
        help="Permite seguir enlaces fuera del dominio de cada semilla.",
    )
    parser.add_argument(
        "--ignore-robots",
        action="store_true",
        help="Ignora robots.txt (usar solo en entornos de prueba autorizados).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = _parse_args(argv)
    result = run_crawl_pipeline(
        seed_urls=args.seeds,
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        category=args.category,
        solr_url=args.solr_url,
        batch_size=args.batch_size,
        delay=args.delay,
        same_domain_only=not args.allow_external_domains,
        respect_robots=not args.ignore_robots,
        verify_count=True,
    )
    print(
        f"Pipeline finalizado | páginas={result.pages_crawled} | "
        f"extraídos={result.documents_extracted} | indexados={result.documents_indexed} | "
        f"descartados={result.documents_discarded} | lotes={result.batches_sent} | "
        f"total_solr={result.solr_total_count}"
    )
    if result.errors:
        print(f"Incidencias registradas ({len(result.errors)}):")
        for err in result.errors[:10]:
            print(f"  - {err}")
    return 0 if result.documents_indexed > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
