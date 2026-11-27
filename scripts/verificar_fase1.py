#!/usr/bin/env python3
"""
verificar_fase1.py
Suite de validación automatizada para el core 'buscador_es' de Apache Solr 10.
Verifica:
1. Ping y salud del core 'buscador_es'.
2. Existencia de los tipos de campo (text_es, text_es_trigram) y campos del contrato oficial (ADR-0001).
3. Pipeline del analizador léxico/morfológico en español (Analysis API: stopwords, acentos, lematización).
4. Indexación de documento de prueba con el contrato acordado.
5. Búsqueda y expansión semántica de sinónimos.
6. Snippets resaltados (<mark>...</mark>) y cómputo de facetas dinámicas (domain_s, category_s).
7. Autocompletado rápido basado en trigramas de caracteres (/suggest con AnalyzingInfixLookupFactory).
8. Corrección ortográfica (/spell con DirectSolrSpellChecker).
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = os.environ.get("SOLR_URL", "http://localhost:8983/solr/buscador_es")

def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def post_json(url: str, payload) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def test_ping():
    print("[1/8] Verificando estado del Core Solr (Ping)...", end=" ")
    data = get_json(f"{BASE_URL}/admin/ping")
    assert data.get("status") == "OK", f"Ping falló: {data}"
    print("OK (status: OK)")

def test_schema_elements():
    print("[2/8] Verificando esquema oficial (tipos y campos)...", end=" ")
    ft_data = get_json(f"{BASE_URL}/schema/fieldtypes")
    ft_names = {ft["name"] for ft in ft_data.get("fieldTypes", [])}
    expected_ft = ["text_es", "text_es_trigram"]
    for ft in expected_ft:
        assert ft in ft_names, f"Falta fieldType requerido: {ft}"

    f_data = get_json(f"{BASE_URL}/schema/fields")
    f_names = {f["name"] for f in f_data.get("fields", [])}
    expected_f = ["id", "title", "content", "url", "domain_s", "category_s", "doc_type_s", "published_at_dt", "suggest_text", "_text_"]
    for f in expected_f:
        assert f in f_names, f"Falta campo del contrato: {f}"
    print("OK (todos los tipos y campos existen)")

def test_spanish_analyzer():
    print("[3/8] Probando analizador en español y trigramas (Analysis API)...", end=" ")
    text_to_analyze = "Los automóviles eléctricos investigan la energía"
    url = f"{BASE_URL}/analysis/field?analysis.fieldtype=text_es&analysis.fieldvalue={urllib.parse.quote(text_to_analyze)}&wt=json"
    data = get_json(url)
    index_chain = data["analysis"]["field_types"]["text_es"]["index"]
    final_tokens = [t["text"] for t in index_chain[-1]]

    # Comprobar eliminación de stopwords
    assert "los" not in final_tokens, "Stopword 'los' no fue filtrada"
    assert "la" not in final_tokens, "Stopword 'la' no fue filtrada"
    # Comprobar lematización y acentos
    assert "vehicul" in final_tokens or "automovil" in final_tokens or "electr" in final_tokens or "energi" in final_tokens

    # Comprobar trigramas
    trigram_url = f"{BASE_URL}/analysis/field?analysis.fieldtype=text_es_trigram&analysis.fieldvalue={urllib.parse.quote('inteligencia')}&wt=json"
    tri_data = get_json(trigram_url)
    tri_tokens = [t["text"] for t in tri_data["analysis"]["field_types"]["text_es_trigram"]["index"][-1]]
    assert "int" in tri_tokens, f"Trigrama de prefijo 'int' no generado: {tri_tokens}"
    print(f"OK (tokens finales: {final_tokens}, trigramas activos)")

def test_index_document():
    print("[4/8] Indexando documento de prueba con contrato oficial...", end=" ")
    doc = {
        "id": "doc-test-1",
        "url": "https://unam.mx/investigacion/vehiculos-electricos",
        "domain_s": "unam.mx",
        "category_s": "Tecnología",
        "doc_type_s": "html",
        "published_at_dt": "2026-11-23T12:00:00Z",
        "title": "Investigación sobre vehículos eléctricos y transporte sostenible",
        "content": "La investigación científica en la universidad impulsa el desarrollo de automóviles y vehículos eléctricos más eficientes. El nuevo coche reduce las emisiones contaminantes radicalmente y aprovecha la energía renovable."
    }
    resp = post_json(f"{BASE_URL}/update?commit=true", [doc])
    assert resp.get("responseHeader", {}).get("status") == 0, f"Error al indexar: {resp}"
    print("OK (documento indexado y commit realizado)")

def test_search_and_synonyms():
    print("[5/8] Probando búsqueda y expansión de sinónimos...", end=" ")
    # Buscamos 'coche' o 'auto' que coincide mediante sinonimia con 'automóviles'/'vehículos'
    q = urllib.parse.quote("coche")
    url = f"{BASE_URL}/select?q={q}&df=title&wt=json"
    data = get_json(url)
    num_found = data.get("response", {}).get("numFound", 0)
    assert num_found > 0, "No se encontró el documento por sinónimo 'coche' en title"
    print(f"OK (documento recuperado por expansión semántica: {num_found} hit)")

def test_highlighting_and_faceting():
    print("[6/8] Probando resaltado de snippets y cómputo de facetas...", end=" ")
    q = urllib.parse.quote("energía")
    url = f"{BASE_URL}/select?q={q}&hl=true&hl.fl=title,content&facet=true&facet.field=domain_s&facet.field=category_s&facet.field=doc_type_s&wt=json"
    data = get_json(url)
    
    # Validar highlighting (<mark>...</mark>)
    hl = data.get("highlighting", {}).get("doc-test-1", {})
    assert any("<mark>" in snippet for snippets in hl.values() for snippet in snippets), f"Highlighting no presente: {hl}"
    
    # Validar facetas
    facet_fields = data.get("facet_counts", {}).get("facet_fields", {})
    assert "domain_s" in facet_fields and "unam.mx" in facet_fields["domain_s"]
    assert "category_s" in facet_fields and "Tecnología" in facet_fields["category_s"]
    print("OK (snippets con <mark> y facetas dinámicas correctas)")

def test_suggest():
    print("[7/8] Probando autocompletado por trigramas (/suggest)...", end=" ")
    build_url = f"{BASE_URL}/suggest?suggest=true&suggest.build=true&suggest.dictionary=spanishSuggester&suggest.q=inves&wt=json"
    data = get_json(build_url)
    suggestions = data.get("suggest", {}).get("spanishSuggester", {}).get("inves", {}).get("suggestions", [])
    assert len(suggestions) > 0, f"No se obtuvieron sugerencias para 'inves': {data}"
    suggestion_terms = [s["term"] for s in suggestions]
    print(f"OK (sugerencias obtenidas: {suggestion_terms})")

def test_spellcheck():
    print("[8/8] Probando corrector ortográfico (/spell)...", end=" ")
    q = urllib.parse.quote("investigasion")
    url = f"{BASE_URL}/spell?spellcheck=true&spellcheck.q={q}&wt=json"
    data = get_json(url)
    spellcheck = data.get("spellcheck", {})
    assert "suggestions" in spellcheck or spellcheck.get("correctlySpelled") is not None, f"Spellcheck falló: {data}"
    print(f"OK (Spellcheck respondió operativamente: {spellcheck.get('suggestions', [])})")

if __name__ == "__main__":
    print("==================================================")
    print(f" EJECUTANDO SUITE DE VALIDACIÓN: {BASE_URL}")
    print("==================================================")
    try:
        test_ping()
        test_schema_elements()
        test_spanish_analyzer()
        test_index_document()
        test_search_and_synonyms()
        test_highlighting_and_faceting()
        test_suggest()
        test_spellcheck()
        print("==================================================")
        print(" ¡TODAS LAS PRUEBAS DEL MOTOR SOLR PASARON EN VERDE! ")
        print("==================================================")
    except Exception as e:
        print(f"\n[ERROR FATAL] Falló la validación: {e}")
        sys.exit(1)
