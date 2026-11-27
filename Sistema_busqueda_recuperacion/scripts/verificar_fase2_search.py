#!/usr/bin/env python3
"""
verificar_fase2_search.py
Suite de validación automatizada para la Fase 2 (Motor de Búsqueda y Recuperación).
Verifica:
1. Indexación de lote de documentos de prueba controlados (id: test-fase2-*).
2. Relevancia ponderada eDisMax: El término en title obtiene mayor score que solo en content.
3. Búsqueda booleana: Operadores AND, OR, NOT, agrupación con paréntesis y resiliencia a errores de sintaxis.
4. Búsqueda facetada dinámica: Conteos limpios en domain_s, category_s, doc_type_s y filtrado fq combinado.
5. Snippets contextuales: Resaltado con etiquetas <mark>...</mark> y longitud contextual.
6. Autocompletado en tiempo real: /suggest con spanishSuggester y trigramas.
7. Corrección ortográfica y 'did_you_mean': Detección de erratas y sugerencia automática ante 0 resultados.
8. Expansión semántica de sinónimos: Recuperación mediante términos equivalentes definidos en sinonimos.txt.
9. Exportación XML (Extra #2): Documento XML bien formado UTF-8, parseable y con todos los campos.
10. Limpieza controlada: Eliminación de documentos temporales y commit sin ensuciar el índice.
"""

import os
import sys
import xml.etree.ElementTree as ET

# Asegurar que search_engine sea importable
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from search_engine.client import SolrSearchClient
from search_engine.query_builder import QueryBuilder
from search_engine.xml_exporter import export_to_xml, XMLExporter


TEST_DOCS = [
    {
        "id": "test-fase2-doc-title",
        "url": "https://unam.mx/ciencias/inteligencia-artificial",
        "domain_s": "unam.mx",
        "category_s": "Tecnología",
        "doc_type_s": "html",
        "published_at_dt": "2026-11-24T10:00:00Z",
        "title": "Inteligencia artificial y redes neuronales avanzadas",
        "content": "Este artículo analiza algoritmos computacionales y modelos matemáticos de procesamiento de datos."
    },
    {
        "id": "test-fase2-doc-content",
        "url": "https://ipn.mx/computacion/avances-modernos",
        "domain_s": "ipn.mx",
        "category_s": "Ciencia",
        "doc_type_s": "pdf",
        "published_at_dt": "2026-11-24T11:00:00Z",
        "title": "Avances en la ingeniería de sistemas",
        "content": "La inteligencia artificial moderna impulsa la automatización industrial y las redes neuronales en plantas robóticas."
    },
    {
        "id": "test-fase2-doc-sinonimo",
        "url": "https://movilidad.gob.mx/transporte-sostenible",
        "domain_s": "movilidad.gob.mx",
        "category_s": "Transporte",
        "doc_type_s": "docx",
        "published_at_dt": "2026-11-24T12:00:00Z",
        "title": "El automóvil moderno en las ciudades inteligentes",
        "content": "Los coches y carros eficientes transforman el tránsito urbano y reducen la huella de carbono."
    },
    {
        "id": "test-fase2-doc-mecanica",
        "url": "https://unam.mx/ingenieria/mecanica-industrial",
        "domain_s": "unam.mx",
        "category_s": "Ingeniería",
        "doc_type_s": "html",
        "published_at_dt": "2026-11-24T13:00:00Z",
        "title": "Mecánica industrial e hidráulica aplicada",
        "content": "Estudio de transmisiones de engranajes, bombas hidráulicas y sistemas de potencia mecánica pura."
    }
]


def test_index_and_ping(client: SolrSearchClient):
    print("[1/9] Conectando y cargando documentos de prueba temporales...", end=" ")
    assert client.ping(), "El ping contra Solr falló"
    res = client.index_documents(TEST_DOCS, commit=True)
    assert res.get("responseHeader", {}).get("status") == 0, f"Error indexando: {res}"

    # Construir índice del suggester
    try:
        client._get("suggest", {
            "suggest": "true",
            "suggest.build": "true",
            "suggest.dictionary": "spanishSuggester",
            "suggest.q": "inte",
            "wt": "json"
        })
    except Exception:
        pass

    print("OK (4 documentos temporales indexados y commit realizado)")


def test_weighted_relevance(client: SolrSearchClient):
    print("[2/9] Validando Relevancia Ponderada eDisMax (Título > Contenido)...", end=" ")
    # Buscamos 'inteligencia artificial'
    res = client.search("inteligencia artificial", mode="edismax")
    assert res["total"] >= 2, f"Se esperaban al menos 2 resultados, obtenidos: {res['total']}"

    first_doc = res["results"][0]
    second_doc = res["results"][1]

    # El documento con el término en title ('test-fase2-doc-title') debe superar
    # al que solo lo tiene en content ('test-fase2-doc-content')
    assert first_doc["id"] == "test-fase2-doc-title", (
        f"El primer documento debió ser test-fase2-doc-title pero fue {first_doc['id']}"
    )
    assert first_doc["score"] > second_doc["score"], (
        f"Score de título ({first_doc['score']}) debe ser mayor que el de contenido ({second_doc['score']})"
    )
    assert all(doc["score"] > 0 for doc in res["results"][:2]), "Los scores deben ser positivos"
    print(f"OK (Doc título score: {first_doc['score']} > Doc contenido score: {second_doc['score']})")


def test_boolean_search(client: SolrSearchClient):
    print("[3/9] Validando Búsqueda Booleana (AND, OR, NOT, paréntesis y resiliencia)...", end=" ")
    
    # 3.1 AND
    res_and = client.search("inteligencia AND ingeniería", mode="boolean")
    ids_and = {d["id"] for d in res_and["results"]}
    assert "test-fase2-doc-content" in ids_and, "AND falló en encontrar test-fase2-doc-content"
    assert "test-fase2-doc-mecanica" not in ids_and, "AND debió excluir test-fase2-doc-mecanica"

    # 3.2 OR
    res_or = client.search("automóvil OR hidráulica", mode="boolean")
    ids_or = {d["id"] for d in res_or["results"]}
    assert "test-fase2-doc-sinonimo" in ids_or and "test-fase2-doc-mecanica" in ids_or, (
        f"OR no recuperó ambos documentos: {ids_or}"
    )

    # 3.3 NOT
    res_not = client.search("inteligencia NOT automatización", mode="boolean")
    ids_not = {d["id"] for d in res_not["results"]}
    assert "test-fase2-doc-title" in ids_not, "NOT debió incluir test-fase2-doc-title"
    assert "test-fase2-doc-content" not in ids_not, "NOT debió excluir test-fase2-doc-content"

    # 3.4 Agrupación con paréntesis
    res_grouped = client.search("(inteligencia OR mecánica) AND hidráulica", mode="boolean")
    ids_grouped = {d["id"] for d in res_grouped["results"]}
    assert "test-fase2-doc-mecanica" in ids_grouped and len(ids_grouped) == 1, (
        f"Agrupación con paréntesis falló: {ids_grouped}"
    )

    # 3.5 Resiliencia ante errores de sintaxis (paréntesis desbalanceados, operadores colgantes)
    res_err1 = client.search("((inteligencia AND artificial", mode="boolean")
    assert res_err1["total"] > 0, "No debe fallar ante paréntesis no cerrados"

    res_err2 = client.search("inteligencia AND", mode="boolean")
    assert res_err2["total"] > 0, "No debe fallar ante operador colgante al final"

    res_err3 = client.search("AND OR inteligencia", mode="boolean")
    assert res_err3["total"] > 0, "No debe fallar ante operadores múltiples al inicio"

    print("OK (AND, OR, NOT, agrupación '(' ')' y tolerancia a errores sintácticos)")


def test_faceting_and_filters(client: SolrSearchClient):
    print("[4/9] Validando Facetas Dinámicas y Filtros fq Combinados...", end=" ")
    res = client.search("*:*", mode="edismax")
    facets = res.get("facets", {})
    assert "domain_s" in facets, "Falta faceta domain_s"
    assert "category_s" in facets, "Falta faceta category_s"
    assert "doc_type_s" in facets, "Falta faceta doc_type_s"

    assert facets["domain_s"].get("unam.mx", 0) >= 2, "unam.mx debe tener conteo >= 2"

    # Filtrar con fq combinado: categoría 'Tecnología' y tipo 'html'
    filters = {"category_s": "Tecnología", "doc_type_s": "html"}
    res_filtered = client.search("*:*", filters=filters)
    for doc in res_filtered["results"]:
        assert doc["category_s"] == "Tecnología", f"Categoría incorrecta: {doc['category_s']}"
        assert doc["doc_type_s"] == "html", f"Doc type incorrecto: {doc['doc_type_s']}"
    print(f"OK (facetas computadas y filtrado fq estricto)")


def test_snippets_highlighting(client: SolrSearchClient):
    print("[5/9] Validando Snippets Contextuales y Resaltado (<mark>)...", end=" ")
    res = client.search("algoritmos", mode="edismax")
    assert res["total"] > 0, "No se encontró el documento para 'algoritmos'"
    doc = res["results"][0]
    
    snippet = doc.get("snippet", "")
    assert "<mark>" in snippet and "</mark>" in snippet, f"Snippet no contiene etiquetas mark: {snippet}"
    assert "algoritmos" in snippet.lower(), f"Término buscado no está en snippet: {snippet}"
    print(f"OK (snippet generado con <mark>...</mark>)")


def test_autocomplete_suggest(client: SolrSearchClient):
    print("[6/9] Validando Autocompletado por Trigramas (/suggest)...", end=" ")
    suggestions = client.suggest("inte", count=5)
    assert len(suggestions) > 0, "No se obtuvieron sugerencias para 'inte'"
    assert any("inteligencia" in s["term"].lower() for s in suggestions), (
        f"Ninguna sugerencia contiene 'inteligencia': {suggestions}"
    )

    terms = client.autocomplete("inte", count=5)
    assert isinstance(terms, list) and len(terms) > 0, "autocomplete() debe devolver lista de strings"
    print(f"OK ({len(suggestions)} sugerencias recuperadas)")


def test_spellcheck_and_did_you_mean(client: SolrSearchClient):
    print("[7/9] Validando Corrección Ortográfica y Fallback Automático...", end=" ")
    # Búsqueda con errata intencional que devuelve 0 resultados
    res = client.search("investigasion", mode="edismax")
    assert res["total"] == 0, "La errata no debió retornar resultados directos"
    assert res.get("spelling_suggestion") == "investigacion", (
        f"Se esperaba sugerencia 'investigacion', obtenida: {res.get('spelling_suggestion')}"
    )
    assert res.get("did_you_mean") == "investigacion", "did_you_mean debe coincidir con spelling_suggestion"

    # Prueba directa del método spellcheck()
    spell_info = client.spellcheck("investigasion")
    assert not spell_info["correctly_spelled"], "correctly_spelled debe ser False para investigasion"
    assert spell_info["suggestion"] == "investigacion", f"Sugerencia errónea: {spell_info}"
    print(f"OK ('did_you_mean': {res.get('did_you_mean')} ante 0 resultados)")


def test_synonym_expansion(client: SolrSearchClient):
    print("[8/9] Validando Expansión Semántica de Sinónimos en Español...", end=" ")
    # Documento test-fase2-doc-sinonimo tiene 'automóvil', 'coches', 'carros'.
    # Buscamos 'vehículo', que no aparece textualmente en ese documento pero es sinónimo.
    res = client.search("vehículo", mode="edismax")
    matched_ids = {d["id"] for d in res["results"]}
    assert "test-fase2-doc-sinonimo" in matched_ids, (
        f"Expansión semántica falló: test-fase2-doc-sinonimo no recuperado por sinónimo 'vehículo'. Hits: {matched_ids}"
    )
    print("OK (documento recuperado mediante expansión semántica)")


def test_xml_export_and_cleanup(client: SolrSearchClient):
    print("[9/9] Validando Exportación XML (Extra #2) y Limpieza de Índice...", end=" ")
    res = client.search("inteligencia", mode="edismax")
    xml_str = export_to_xml(res)

    assert xml_str.startswith("<?xml"), "Falta declaración XML"
    assert "utf-8" in xml_str.lower(), "Declaración debe especificar UTF-8"
    assert "<search_response>" in xml_str and "</search_response>" in xml_str

    # Validar que sea 100% parseable por ElementTree sin errores
    parsed_root = ET.fromstring(xml_str)
    assert parsed_root.tag == "search_response", f"Tag raíz incorrecto: {parsed_root.tag}"
    assert parsed_root.find("metadata/total").text == str(res["total"]), "Total en XML no coincide"
    
    docs_in_xml = parsed_root.findall("results/document")
    assert len(docs_in_xml) == len(res["results"]), "Cantidad de documentos en XML no coincide"

    # Limpieza: eliminar los documentos temporales indexados
    del_res = client.delete_by_query("id:test-fase2-*", commit=True)
    assert del_res.get("responseHeader", {}).get("status") == 0, f"Error eliminando docs de prueba: {del_res}"

    # Confirmar que ya no están
    check = client.search("id:test-fase2-*")
    assert check["total"] == 0, f"Quedaron {check['total']} documentos de prueba en el índice"

    print("OK (XML válido UTF-8 y documentos temporales depurados)")


def main():
    print("==================================================================")
    print(" SUITE DE VALIDACIÓN FASE 2: MOTOR DE BÚSQUEDA Y RECUPERACIÓN")
    print(f" Conectando a: {client.base_url}")
    print("==================================================================")

    try:
        test_index_and_ping(client)
        test_weighted_relevance(client)
        test_boolean_search(client)
        test_faceting_and_filters(client)
        test_snippets_highlighting(client)
        test_autocomplete_suggest(client)
        test_spellcheck_and_did_you_mean(client)
        test_synonym_expansion(client)
        test_xml_export_and_cleanup(client)
        print("==================================================================")
        print(" ¡TODAS LAS PRUEBAS DE FASE 2 PASARON EXITOSAMENTE EN VERDE! ")
        print("==================================================================")
    except AssertionError as ae:
        print(f"\n[FALLO DE ASERCIÓN]: {ae}")
        # Intentar limpiar de todos modos
        try:
            client.delete_by_query("id:test-fase2-*", commit=True)
        except Exception:
            pass
        sys.exit(1)
    except Exception as ex:
        print(f"\n[ERROR INESPERADO]: {ex}")
        try:
            client.delete_by_query("id:test-fase2-*", commit=True)
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    client = SolrSearchClient()
    main()
