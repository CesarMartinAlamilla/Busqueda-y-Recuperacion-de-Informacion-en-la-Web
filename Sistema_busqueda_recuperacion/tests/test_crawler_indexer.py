"""Pruebas unitarias para crawler/indexer.py y crawler/pipeline.py."""

import hashlib
from unittest.mock import MagicMock

import pytest
import requests

from api.schemas import CrawlResponse
from crawler.indexer import SolrIndexer, compute_doc_id, prepare_solr_document
from crawler.pipeline import run_crawl_pipeline
from crawler.spider import CrawlResult


def _make_doc(idx: int, **overrides) -> dict:
    url = overrides.pop("url", f"https://ejemplo.edu/articulo-{idx}")
    doc = {
        "id": url,
        "title": f"Artículo de prueba número {idx}",
        "content": f"Contenido extenso en español sobre recuperación de información {idx}.",
        "url": url,
        "domain_s": "ejemplo.edu",
        "category_s": "Tecnología",
        "doc_type_s": "html",
        "published_at_dt": "2026-11-27T00:00:00Z",
    }
    doc.update(overrides)
    return doc


def _mock_response(status_code: int = 200, payload: dict | None = None, text: str = "") -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.text = text
    if payload is not None:
        resp.json.return_value = payload
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


def test_compute_doc_id_is_deterministic_sha256_and_ignores_fragment():
    url_a = "  https://ciencia.gob.mx/energia-solar#seccion-1  "
    url_b = "https://ciencia.gob.mx/energia-solar"
    expected = hashlib.sha256(url_b.encode("utf-8")).hexdigest()

    assert compute_doc_id(url_a) == expected
    assert compute_doc_id(url_b) == expected
    assert len(expected) == 64


def test_compute_doc_id_rejects_invalid_urls():
    with pytest.raises(ValueError):
        compute_doc_id("")
    with pytest.raises(ValueError):
        compute_doc_id("ftp://ejemplo.edu/archivo")


def test_prepare_solr_document_validates_non_empty_fields_and_strips_extras():
    raw = _make_doc(1, extra_field="ignorar")
    prepared, reason = prepare_solr_document(raw)

    assert reason is None
    assert prepared is not None
    assert prepared["id"] == compute_doc_id(raw["url"])
    assert "extra_field" not in prepared

    empty_content_doc, err = prepare_solr_document(_make_doc(2, content="   "))
    assert empty_content_doc is None
    assert err is not None and "content" in err

    empty_title_doc, err_title = prepare_solr_document(_make_doc(3, title=""))
    assert empty_title_doc is None
    assert err_title is not None and "title" in err_title


def test_solr_indexer_sends_batches_of_25_with_commit_and_suggest_rebuild():
    session = MagicMock(spec=requests.Session)
    session.post.return_value = _mock_response(200, {"responseHeader": {"status": 0}})
    session.get.return_value = _mock_response(200, {"responseHeader": {"status": 0}})

    docs = [_make_doc(i) for i in range(60)]
    indexer = SolrIndexer(
        solr_url="http://solr:8983/solr/buscador_es",
        batch_size=25,
        session=session,
    )
    result = indexer.index_documents(docs)

    assert result.total_received == 60
    assert result.documents_indexed == 60
    assert result.documents_discarded == 0
    assert result.batches_sent == 3
    assert result.batches_failed == 0
    assert result.suggest_rebuilt is True
    assert len(result.indexed_ids) == 60

    assert session.post.call_count == 3
    sent_sizes = [len(call.kwargs["json"]) for call in session.post.call_args_list]
    assert sent_sizes == [25, 25, 10]
    for call in session.post.call_args_list:
        assert call.args[0] == "http://solr:8983/solr/buscador_es/update"
        assert call.kwargs["params"] == {"commit": "true"}

    session.get.assert_called_once_with(
        "http://solr:8983/solr/buscador_es/suggest",
        params={"suggest": "true", "suggest.build": "true", "wt": "json"},
        timeout=15,
    )


def test_solr_indexer_deduplicates_and_handles_http_errors():
    session = MagicMock(spec=requests.Session)
    session.post.side_effect = [
        _mock_response(200, {"responseHeader": {"status": 0}}),
        _mock_response(400, {"error": {"msg": "Bad Request"}}),
    ]
    session.get.return_value = _mock_response(200, {"responseHeader": {"status": 0}})

    docs = [
        _make_doc(1),
        _make_doc(1),  # duplicado
        _make_doc(2, content=""),  # inválido
        _make_doc(3),
        _make_doc(4),
    ]
    indexer = SolrIndexer(solr_url="http://solr:8983/solr/buscador_es", batch_size=2, session=session)
    result = indexer.index_documents(docs)

    assert result.total_received == 5
    assert result.documents_indexed == 2
    assert result.documents_discarded == 3
    assert result.batches_sent == 2
    assert result.batches_failed == 1
    assert any("HTTP 400" in err for err in result.errors)


def test_run_crawl_pipeline_integrates_spider_indexer_and_count():
    fake_spider = MagicMock()
    fake_spider.crawl.return_value = CrawlResult(
        seed_url="https://ejemplo.edu/",
        pages_crawled=3,
        documents=[_make_doc(1), _make_doc(2)],
        documents_discarded=1,
        errors=[],
    )

    session = MagicMock(spec=requests.Session)
    session.post.return_value = _mock_response(200, {"responseHeader": {"status": 0}})
    session.get.side_effect = [
        _mock_response(200, {"responseHeader": {"status": 0}}),  # /suggest rebuild
        _mock_response(200, {"response": {"numFound": 42}}),  # /select count
    ]
    indexer = SolrIndexer(solr_url="http://solr:8983/solr/buscador_es", batch_size=25, session=session)

    res = run_crawl_pipeline(
        seed_urls="https://ejemplo.edu/",
        max_pages=10,
        max_depth=1,
        spider=fake_spider,
        indexer=indexer,
        verify_count=True,
    )

    assert res.pages_crawled == 3
    assert res.documents_extracted == 2
    assert res.documents_indexed == 2
    assert res.documents_discarded == 1
    assert res.solr_total_count == 42

    validated = CrawlResponse(**res.to_crawl_response_dict())
    assert validated.documents_indexed == 2
    assert validated.pages_crawled == 3
