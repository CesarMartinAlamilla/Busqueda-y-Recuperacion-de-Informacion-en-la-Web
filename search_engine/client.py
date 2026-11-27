#!/usr/bin/env python3
"""
client.py
Cliente de conexión y búsqueda contra Apache Solr 10 para el core 'buscador_es'.
Implementa:
a) Búsqueda con relevancia ponderada usando eDisMax (qf=title^3.5 category_s^2.0 content^1.0, pf=title^5.0 content^2.0)
y retorno explícito del campo 'score'.
b) Búsqueda booleana robusta con operadores AND, OR, NOT y paréntesis balanceados vía QueryBuilder.
c) Búsqueda facetada dinámica (domain_s, category_s, doc_type_s) con soporte para múltiples filtros combinados 'fq'.
d) Snippets contextuales de resultados con etiquetas <mark>...</mark> (hl=true, hl.fl=title,content, hl.fragsize=180).
e) Autocompletado en tiempo real con trigramas de caracteres vía /suggest (spanishSuggester).
f) Corrección ortográfica vía /spell (DirectSolrSpellChecker) con activación automática ante 0 resultados o baja coincidencia.
g) Respuestas estructuradas en diccionarios estándar JSON listos para FastAPI y la interfaz web.
"""

import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Union

from .query_builder import QueryBuilder

logger = logging.getLogger("search_engine.client")

DEFAULT_SOLR_URL = os.environ.get("SOLR_URL", "http://localhost:8983/solr/buscador_es")


class SolrSearchClient:
    """Cliente unificado para Apache Solr 10 (core buscador_es)."""

    def __init__(self, base_url: Optional[str] = None, timeout: int = 10):
        self.base_url = (base_url or DEFAULT_SOLR_URL).rstrip("/")
        self.timeout = timeout

    # -------------------------------------------------------------------------
    # Métodos Auxiliares HTTP
    # -------------------------------------------------------------------------

    def _get(self, handler: str, params: Union[Dict[str, Any], List[tuple]]) -> Dict[str, Any]:
        """Realiza una petición GET codificando parámetros múltiples de forma segura."""
        if isinstance(params, dict):
            # Convertir listas en secuencias para urlencode(doseq=True)
            encoded_params = urllib.parse.urlencode(params, doseq=True)
        else:
            encoded_params = urllib.parse.urlencode(params)

        endpoint = handler.lstrip("/")
        url = f"{self.base_url}/{endpoint}?{encoded_params}"

        req = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "SolrSearchClient/1.0"}
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw_bytes = resp.read()
                return json.loads(raw_bytes.decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            logger.error("Error HTTP %d en GET %s: %s", e.code, url, err_body)
            raise RuntimeError(f"Solr HTTPError {e.code}: {err_body}")
        except urllib.error.URLError as e:
            logger.error("Error de conexión en GET %s: %s", url, e.reason)
            raise ConnectionError(f"No fue posible conectar con Solr en {self.base_url}: {e.reason}")

    def _post_json(self, handler: str, payload: Any, commit: bool = False) -> Dict[str, Any]:
        """Envía datos JSON vía POST a un handler de Solr (por ejemplo /update)."""
        endpoint = handler.lstrip("/")
        url = f"{self.base_url}/{endpoint}"
        if commit:
            url += "?commit=true"

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            logger.error("Error HTTP %d en POST %s: %s", e.code, url, err_body)
            raise RuntimeError(f"Solr HTTPError {e.code}: {err_body}")
        except urllib.error.URLError as e:
            logger.error("Error de conexión en POST %s: %s", url, e.reason)
            raise ConnectionError(f"No fue posible conectar con Solr en {self.base_url}: {e.reason}")

    # -------------------------------------------------------------------------
    # Operaciones Básicas y de Mantenimiento
    # -------------------------------------------------------------------------

    def ping(self) -> bool:
        """Verifica la salud y disponibilidad del core de Solr."""
        try:
            resp = self._get("admin/ping", {"wt": "json"})
            return resp.get("status") == "OK"
        except Exception as e:
            logger.warning("Ping fallido a Solr: %s", e)
            return False

    def commit(self) -> Dict[str, Any]:
        """Realiza un commit explícito sobre el índice."""
        return self._post_json("update", {}, commit=True)

    def index_documents(self, docs: List[Dict[str, Any]], commit: bool = True) -> Dict[str, Any]:
        """Indexa una lista de documentos respetando el contrato de datos."""
        return self._post_json("update", docs, commit=commit)

    def delete_by_id(self, doc_ids: Union[str, List[str]], commit: bool = True) -> Dict[str, Any]:
        """Elimina uno o más documentos por su ID."""
        if isinstance(doc_ids, str):
            doc_ids = [doc_ids]
        payload = {"delete": doc_ids}
        return self._post_json("update", payload, commit=commit)

    def delete_by_query(self, query: str, commit: bool = True) -> Dict[str, Any]:
        """Elimina documentos que coincidan con una consulta."""
        payload = {"delete": {"query": query}}
        return self._post_json("update", payload, commit=commit)

    # -------------------------------------------------------------------------
    # Autocompletado y Corrección Ortográfica
    # -------------------------------------------------------------------------

    def suggest(self, prefix: str, count: int = 10) -> List[Dict[str, Any]]:
        """
        Consulta el SuggestComponent (/suggest) configurado con AnalyzingInfixLookupFactory
        y trigramas de caracteres sobre 'suggest_text'.
        Devuelve sugerencias con término limpio y versión resaltada.
        """
        if not prefix or not prefix.strip():
            return []

        clean_prefix = prefix.strip()
        params = {
            "suggest": "true",
            "suggest.dictionary": "spanishSuggester",
            "suggest.q": clean_prefix,
            "suggest.count": count,
            "wt": "json"
        }

        try:
            data = self._get("suggest", params)
            suggester_data = data.get("suggest", {}).get("spanishSuggester", {})
            entry = suggester_data.get(clean_prefix, {})
            raw_suggestions = entry.get("suggestions", [])

            results = []
            seen_terms = set()
            for s in raw_suggestions:
                term = s.get("term", "")
                # Eliminar etiquetas HTML para el término puro
                clean_term = re.sub(r'<[^>]+>', '', term).strip()
                if clean_term and clean_term.lower() not in seen_terms:
                    seen_terms.add(clean_term.lower())
                    results.append({
                        "term": clean_term,
                        "highlighted": term,
                        "weight": s.get("weight", 0)
                    })
            return results
        except Exception as e:
            logger.warning("Error al consultar sugerencias para '%s': %s", prefix, e)
            return []

    def autocomplete(self, prefix: str, count: int = 10) -> List[str]:
        """Retorna únicamente la lista de strings sugeridos para integración rápida en UI."""
        return [item["term"] for item in self.suggest(prefix, count=count)]

    def spellcheck(self, query: str, count: int = 5) -> Dict[str, Any]:
        """
        Consulta el SpellCheckComponent (/spell) configurado con DirectSolrSpellChecker.
        Devuelve la sugerencia corregida ('did_you_mean') y detalles fonético-ortográficos.
        """
        if not query or not query.strip() or query.strip() == "*:*":
            return {"correctly_spelled": True, "suggestion": None, "details": []}

        clean_query = query.strip()
        params = {
            "spellcheck": "true",
            "spellcheck.dictionary": "default",
            "spellcheck.q": clean_query,
            "spellcheck.collate": "true",
            "spellcheck.extendedResults": "true",
            "spellcheck.count": count,
            "wt": "json"
        }

        try:
            data = self._get("spell", params)
            spell_info = data.get("spellcheck", {})
            correctly_spelled = spell_info.get("correctlySpelled", True)

            # Extraer collation sugerida (ej. 'investigacion' para 'investigasion')
            collations = spell_info.get("collations", [])
            suggestion = None
            if collations:
                # En Solr, collations puede ser [ "collation", "termino", ... ] o [ { "collationQuery": "..." } ]
                if isinstance(collations, list):
                    for idx, val in enumerate(collations):
                        if val == "collation" and idx + 1 < len(collations):
                            suggestion = collations[idx + 1]
                            break
                        elif isinstance(val, dict) and "collationQuery" in val:
                            suggestion = val["collationQuery"]
                            break
                    if not suggestion and len(collations) > 0 and isinstance(collations[0], str) and collations[0] != "collation":
                        suggestion = collations[0]

            # Si no hubo collation pero hay sugerencias por término
            if not suggestion:
                raw_sugg = spell_info.get("suggestions", [])
                for idx, val in enumerate(raw_sugg):
                    if isinstance(val, dict) and "suggestion" in val:
                        sug_list = val["suggestion"]
                        if sug_list and isinstance(sug_list[0], dict) and "word" in sug_list[0]:
                            suggestion = sug_list[0]["word"]
                            break

            return {
                "query": clean_query,
                "correctly_spelled": correctly_spelled,
                "suggestion": suggestion,
                "details": spell_info.get("suggestions", [])
            }
        except Exception as e:
            logger.warning("Error al consultar spellcheck para '%s': %s", query, e)
            return {"correctly_spelled": True, "suggestion": None, "details": []}

    # -------------------------------------------------------------------------
    # Búsqueda Central (eDisMax / Booleano / Facetas / Snippets / Relevancia)
    # -------------------------------------------------------------------------

    def search(
        self,
        query: str = "*:*",
        mode: str = "edismax",
        filters: Optional[Union[Dict[str, Any], List[str], str]] = None,
        page: int = 1,
        page_size: int = 10,
        sort: Optional[str] = None,
        facet_fields: Optional[List[str]] = None,
        highlight: bool = True,
        spellcheck: bool = True
    ) -> Dict[str, Any]:
        """
        Ejecuta una búsqueda completa contra Solr 10 integrando:
        - Relevancia ponderada eDisMax (qf=title^3.5 category_s^2.0 content^1.0, pf=title^5.0 content^2.0)
        - Búsqueda booleana con QueryBuilder (AND, OR, NOT, paréntesis)
        - Facetas dinámicas (domain_s, category_s, doc_type_s) con conteos limpios
        - Snippets contextuales con etiquetas <mark>...</mark>
        - Retorno explícito del campo 'score'
        - Fallback automático a corrección ortográfica ante 0 resultados o baja coincidencia
        """
        page = max(1, page)
        page_size = max(1, page_size)
        start = (page - 1) * page_size

        # 1. Sanitizar y construir la consulta según el modo
        clean_query = QueryBuilder.build(query, mode=mode)

        # 2. Configurar lista de campos a retornar (incluyendo explícitamente 'score')
        fl = "id,title,content,url,domain_s,category_s,doc_type_s,published_at_dt,score"

        # 3. Construir parámetros para Solr /select
        params: List[tuple] = [
            ("wt", "json"),
            ("q", clean_query),
            ("fl", fl),
            ("start", str(start)),
            ("rows", str(page_size)),
            ("echoParams", "explicit")
        ]

        # 4. Configurar Parser y Boosting
        if mode == "boolean":
            # Modo booleano: aplicamos eDisMax con operadores booleanos respetando ponderación de campos
            params.extend([
                ("defType", "edismax"),
                ("df", "_text_"),
                ("qf", "title^3.5 category_s^2.0 content^1.0"),
                ("pf", "title^5.0 content^2.0"),
            ])
        else:
            # Modo ponderado estándar eDisMax
            params.extend([
                ("defType", "edismax"),
                ("df", "_text_"),
                ("qf", "title^3.5 category_s^2.0 content^1.0"),
                ("pf", "title^5.0 content^2.0"),
            ])

        # Ordenamiento si se especifica
        if sort:
            params.append(("sort", sort))
        else:
            params.append(("sort", "score desc"))

        # 5. Configurar Filtros fq
        if filters:
            if isinstance(filters, str):
                params.append(("fq", filters))
            elif isinstance(filters, list):
                for f in filters:
                    if f:
                        params.append(("fq", f))
            elif isinstance(filters, dict):
                for k, v in filters.items():
                    if v is not None and v != "":
                        # Escapar comillas internas si las hay
                        v_escaped = str(v).replace('"', '\\"')
                        params.append(("fq", f'{k}:"{v_escaped}"'))

        # 6. Configurar Facetas Dinámicas
        default_facets = ["domain_s", "category_s", "doc_type_s"]
        target_facets = facet_fields if facet_fields is not None else default_facets
        if target_facets:
            params.extend([
                ("facet", "true"),
                ("facet.mincount", "1"),
                ("facet.limit", "50")
            ])
            for ff in target_facets:
                params.append(("facet.field", ff))

        # 7. Configurar Snippets Contextuales (Highlighting)
        if highlight:
            params.extend([
                ("hl", "true"),
                ("hl.fl", "title,content"),
                ("hl.simple.pre", "<mark>"),
                ("hl.simple.post", "</mark>"),
                ("hl.snippets", "3"),
                ("hl.fragsize", "180")
            ])

        # 8. Ejecutar petición a Solr
        try:
            raw_response = self._get("select", params)
        except Exception as ex:
            logger.error("Error ejecutando select en Solr: %s", ex)
            # Retornar respuesta vacía estructurada en caso de fallo crítico
            return {
                "query": query,
                "sanitized_query": clean_query,
                "mode": mode,
                "total": 0,
                "page": page,
                "page_size": page_size,
                "total_pages": 0,
                "query_time_ms": 0,
                "results": [],
                "facets": {},
                "spelling_suggestion": None,
                "did_you_mean": None,
                "error": str(ex)
            }

        response_header = raw_response.get("responseHeader", {})
        solr_response = raw_response.get("response", {})
        highlighting = raw_response.get("highlighting", {})
        facet_counts_raw = raw_response.get("facet_counts", {})

        total = solr_response.get("numFound", 0)
        query_time = response_header.get("QTime", 0)
        total_pages = (total + page_size - 1) // page_size if total > 0 else 0

        # 9. Procesar Resultados y Asociar Snippets + Score
        docs = solr_response.get("docs", [])
        results = []
        for doc in docs:
            doc_id = doc.get("id", "")
            doc_score = doc.get("score", 0.0)
            doc_hl = highlighting.get(doc_id, {})

            # Extraer snippets de title y content
            title_snippets = doc_hl.get("title", [])
            content_snippets = doc_hl.get("content", [])

            # Snippet principal contextual
            if content_snippets:
                main_snippet = " ... ".join(content_snippets)
            elif title_snippets:
                main_snippet = " ... ".join(title_snippets)
            else:
                raw_content = doc.get("content", "")
                main_snippet = (raw_content[:180] + "...") if len(raw_content) > 180 else raw_content

            formatted_doc = {
                "id": doc_id,
                "title": doc.get("title", ""),
                "content": doc.get("content", ""),
                "url": doc.get("url", ""),
                "domain_s": doc.get("domain_s", ""),
                "category_s": doc.get("category_s", ""),
                "doc_type_s": doc.get("doc_type_s", ""),
                "published_at_dt": doc.get("published_at_dt", ""),
                "score": round(float(doc_score), 4) if doc_score is not None else 0.0,
                "snippets": {
                    "title": title_snippets,
                    "content": content_snippets
                },
                "snippet": main_snippet
            }
            results.append(formatted_doc)

        # 10. Limpiar Conteos de Facetas
        # Solr devuelve listas alternadas: ["unam.mx", 10, "ipn.mx", 5]
        parsed_facets: Dict[str, Dict[str, int]] = {}
        raw_facet_fields = facet_counts_raw.get("facet_fields", {})
        for field_name, flat_list in raw_facet_fields.items():
            field_dict = {}
            if isinstance(flat_list, list):
                for i in range(0, len(flat_list), 2):
                    val = flat_list[i]
                    count = flat_list[i + 1]
                    field_dict[val] = count
            parsed_facets[field_name] = field_dict

        # 11. Activación Automática de Corrección Ortográfica (SpellCheck)
        spelling_suggestion = None
        if spellcheck and query and query.strip() != "*:*":
            # Disparar automáticamente si hay 0 resultados o baja coincidencia
            if total == 0 or total <= 1:
                spell_res = self.spellcheck(query)
                if not spell_res.get("correctly_spelled", True) or spell_res.get("suggestion"):
                    spelling_suggestion = spell_res.get("suggestion")

        return {
            "query": query,
            "sanitized_query": clean_query,
            "mode": mode,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "query_time_ms": query_time,
            "results": results,
            "facets": parsed_facets,
            "spelling_suggestion": spelling_suggestion,
            "did_you_mean": spelling_suggestion
        }
