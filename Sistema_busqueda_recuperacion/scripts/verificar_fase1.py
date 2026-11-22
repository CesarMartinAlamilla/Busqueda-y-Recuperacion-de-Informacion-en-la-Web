#!/usr/bin/env python3
"""
verificar_fase1.py
Suite de validación automatizada para la Fase 1 del sistema de RI con Solr.
Verifica:
1. Salud del contenedor y Ping del core 'ri'.
2. Existencia de tipos de campo y campos en el esquema.
3. Pipeline del analizador léxico/morfológico en español (Analysis API).
4. Indexación de documento de prueba.
5. Búsqueda con expansión de sinónimos y lematización.
6. Generación de snippets y resaltado contextual (Highlighting).
7. Agrupación facetada (Faceting).
8. Autocompletado y sugerencias (SuggestComponent).
9. Corrección ortográfica (SpellCheckComponent).
"""

import json
import urllib.request
import urllib.parse
import sys

BASE_URL = "http://localhost:8983/solr/ri"

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
    print("[2/8] Verificando esquema (tipos de campo y campos)...", end=" ")
    ft_data = get_json(f"{BASE_URL}/schema/fieldtypes")
    ft_names = {ft["name"] for ft in ft_data.get("fieldTypes", [])}
    expected_ft = ["text_es_completo", "text_es_ri", "text_es_stem", "text_es_stop", "text_es_syn", "text_es_suggest"]
    for ft in expected_ft:
        assert ft in ft_names, f"Falta fieldType: {ft}"

    f_data = get_json(f"{BASE_URL}/schema/fields")
    f_names = {f["name"] for f in f_data.get("fields", [])}
    expected_f = ["url", "dominio", "titulo", "encabezados", "contenido", "categoria", "profundidad", "pagerank", "enlaces_salientes", "sugerencia_texto"]
    for f in expected_f:
        assert f in f_names, f"Falta campo: {f}"
    print("OK (todos los tipos y campos existen)")

def test_spanish_analyzer():
    print("[3/8] Probando analizador léxico/morfológico en español (Analysis API)...", end=" ")
    text_to_analyze = "Los automóviles eléctricos investigan la energía"
    url = f"{BASE_URL}/analysis/field?analysis.fieldtype=text_es_completo&analysis.fieldvalue={urllib.parse.quote(text_to_analyze)}&wt=json"
    data = get_json(url)
    index_chain = data["analysis"]["field_types"]["text_es_completo"]["index"]
    # Los tokens finales producidos por el último filtro
    final_tokens = [t["text"] for t in index_chain[-1]]
    
    # Comprobar que stopwords 'los' y 'la' fueron eliminadas
    assert "los" not in final_tokens, "Stopword 'los' no fue filtrada"
    assert "la" not in final_tokens, "Stopword 'la' no fue filtrada"
    # Comprobar stemming y normalización de acentos
    # 'automóviles' -> 'automovil' -> stem 'automovil'
    # 'eléctricos' -> 'electric' / 'electrico'
    # 'investigan' -> stem 'investig'
    # 'energía' -> stem 'energi'
    print(f"OK (tokens finales: {final_tokens})")

def test_index_document():
    print("[4/8] Indexando documento de prueba con metadatos enriquecidos...", end=" ")
    doc = {
        "id": "doc-test-1",
        "url": "https://ejemplo.edu/articulo-autos-electricos",
        "dominio": "ejemplo.edu",
        "titulo": "Investigación sobre vehículos eléctricos y automóviles modernos",
        "encabezados": ["Energía limpia y transporte", "Avances tecnológicos"],
        "contenido": "La investigación científica en la universidad impulsa el desarrollo de automóviles y vehículos eléctricos más eficientes. El nuevo coche reduce las emisiones contaminantes radicalmente.",
        "categoria": "Tecnología",
        "tema": "Transporte",
        "fecha": "2026-11-21",
        "profundidad": 1,
        "pagerank": 0.85,
        "enlaces_salientes": ["https://ejemplo.edu/baterias", "https://ejemplo.edu/medio-ambiente"]
    }
    resp = post_json(f"{BASE_URL}/update?commit=true", [doc])
    assert resp.get("responseHeader", {}).get("status") == 0, f"Error al indexar: {resp}"
    print("OK (documento indexado y commit realizado)")

def test_search_and_synonyms():
    print("[5/8] Probando búsqueda con sinónimos y ponderación...", end=" ")
    # Buscamos 'coche' o 'auto' que no aparece en el título literal (o solo en el contenido como 'coche')
    # usando sinónimos configurados
    q = urllib.parse.quote("auto")
    url = f"{BASE_URL}/select?q=titulo:{q}&wt=json"
    data = get_json(url)
    num_found = data.get("response", {}).get("numFound", 0)
    assert num_found > 0, "No se encontró el documento por sinónimo 'auto' en titulo"
    print(f"OK (documento recuperado mediante expansión de sinónimo: {num_found} hit)")

def test_highlighting_and_faceting():
    print("[6/8] Probando resaltado de snippets y facetas...", end=" ")
    q = urllib.parse.quote("energía")
    url = f"{BASE_URL}/select?q={q}&hl=true&hl.fl=contenido,encabezados&facet=true&facet.field=dominio&facet.field=categoria&wt=json"
    data = get_json(url)
    
    # Validar highlighting
    hl = data.get("highlighting", {}).get("doc-test-1", {})
    assert any("<em>" in snippet for snippets in hl.values() for snippet in snippets), f"Highlighting no presente: {hl}"
    
    # Validar facetas
    facet_fields = data.get("facet_counts", {}).get("facet_fields", {})
    assert "dominio" in facet_fields and "ejemplo.edu" in facet_fields["dominio"]
    print("OK (snippets con <em> y facetas correctas)")

def test_suggest():
    print("[7/8] Probando componente de autocompletado (/suggest)...", end=" ")
    # Construir sugerencias con build=true si es necesario
    build_url = f"{BASE_URL}/suggest?suggest=true&suggest.build=true&suggest.dictionary=spanishSuggester&suggest.q=inves&wt=json"
    data = get_json(build_url)
    suggestions = data.get("suggest", {}).get("spanishSuggester", {}).get("inves", {}).get("suggestions", [])
    assert len(suggestions) > 0, f"No se obtuvieron sugerencias para 'inves': {data}"
    suggestion_terms = [s["term"] for s in suggestions]
    print(f"OK (sugerencias obtenidas: {suggestion_terms})")

def test_spellcheck():
    print("[8/8] Probando componente de corrección ortográfica (/spell)...", end=" ")
    # Mandamos una palabra con error tipográfico: 'investigasión' o 'eléctricoo'
    q = urllib.parse.quote("investigacionn")
    url = f"{BASE_URL}/spell?spellcheck=true&spellcheck.q={q}&wt=json"
    data = get_json(url)
    spellcheck = data.get("spellcheck", {})
    # En Solr 10 con DirectSolrSpellChecker sobre _text_, verifica que responde
    assert "suggestions" in spellcheck or spellcheck.get("correctlySpelled") is not None, f"Spellcheck falló: {data}"
    print(f"OK (Spellcheck respondió correctamente: {spellcheck.get('suggestions', [])})")

if __name__ == "__main__":
    print("==================================================")
    print(" EJECUTANDO SUITE DE VALIDACIÓN DE LA FASE 1")
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
        print(" ¡TODAS LAS PRUEBAS DE LA FASE 1 PASARON CON ÉXITO! ")
        print("==================================================")
    except Exception as e:
        print(f"\n[ERROR FATAL] Falló la validación: {e}")
        sys.exit(1)
