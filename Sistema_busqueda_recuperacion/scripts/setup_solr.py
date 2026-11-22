#!/usr/bin/env python3
"""
setup_solr.py
Configura el esquema (Schema API) y componentes (Config API) en Apache Solr 10
para el core 'ri' con soporte integral para el idioma español.
"""

import json
import urllib.request
import urllib.error
import sys

BASE_URL = "http://localhost:8983/solr/ri"

def send_solr_request(endpoint: str, payload: dict) -> dict:
    url = f"{BASE_URL}/{endpoint}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            err_json = json.loads(body)
            msg = err_json.get("error", {}).get("msg", body)
        except Exception:
            msg = body
        if "already exists" in msg.lower() or "duplicate" in msg.lower():
            print(f"  [AVISO] Ya existe: {payload.keys()} -> omitiendo...")
            return {"status": "already_exists", "msg": msg}
        print(f"  [ERROR {e.code}] en {endpoint}: {msg}")
        raise RuntimeError(f"Error HTTP {e.code} en {endpoint}: {msg}")

def configure_schema():
    print("--- 1. Configurando Tipos de Campo (Field Types) ---")
    
    # 1. text_es_ri (Línea base del kit docente)
    send_solr_request("schema", {
        "add-field-type": {
            "name": "text_es_ri",
            "class": "solr.TextField",
            "positionIncrementGap": "100",
            "indexAnalyzer": {
                "tokenizer": {"class": "solr.StandardTokenizerFactory"},
                "filters": [
                    {"class": "solr.LowerCaseFilterFactory"},
                    {"class": "solr.ASCIIFoldingFilterFactory", "preserveOriginal": "true"}
                ]
            },
            "queryAnalyzer": {
                "tokenizer": {"class": "solr.StandardTokenizerFactory"},
                "filters": [
                    {"class": "solr.LowerCaseFilterFactory"},
                    {"class": "solr.ASCIIFoldingFilterFactory", "preserveOriginal": "true"}
                ]
            }
        }
    })

    # 2. text_es_stem (Stemming Snowball)
    send_solr_request("schema", {
        "add-field-type": {
            "name": "text_es_stem",
            "class": "solr.TextField",
            "positionIncrementGap": "100",
            "indexAnalyzer": {
                "tokenizer": {"class": "solr.StandardTokenizerFactory"},
                "filters": [
                    {"class": "solr.LowerCaseFilterFactory"},
                    {"class": "solr.ASCIIFoldingFilterFactory", "preserveOriginal": "true"},
                    {"class": "solr.SnowballPorterFilterFactory", "language": "Spanish"}
                ]
            },
            "queryAnalyzer": {
                "tokenizer": {"class": "solr.StandardTokenizerFactory"},
                "filters": [
                    {"class": "solr.LowerCaseFilterFactory"},
                    {"class": "solr.ASCIIFoldingFilterFactory", "preserveOriginal": "true"},
                    {"class": "solr.SnowballPorterFilterFactory", "language": "Spanish"}
                ]
            }
        }
    })

    # 3. text_es_stop (Stopwords en español)
    send_solr_request("schema", {
        "add-field-type": {
            "name": "text_es_stop",
            "class": "solr.TextField",
            "positionIncrementGap": "100",
            "indexAnalyzer": {
                "tokenizer": {"class": "solr.StandardTokenizerFactory"},
                "filters": [
                    {"class": "solr.LowerCaseFilterFactory"},
                    {"class": "solr.ASCIIFoldingFilterFactory", "preserveOriginal": "true"},
                    {"class": "solr.StopFilterFactory", "words": "stopwords_es.txt", "ignoreCase": "true"}
                ]
            },
            "queryAnalyzer": {
                "tokenizer": {"class": "solr.StandardTokenizerFactory"},
                "filters": [
                    {"class": "solr.LowerCaseFilterFactory"},
                    {"class": "solr.ASCIIFoldingFilterFactory", "preserveOriginal": "true"},
                    {"class": "solr.StopFilterFactory", "words": "stopwords_es.txt", "ignoreCase": "true"}
                ]
            }
        }
    })

    # 4. text_es_syn (Sinónimos en español)
    send_solr_request("schema", {
        "add-field-type": {
            "name": "text_es_syn",
            "class": "solr.TextField",
            "positionIncrementGap": "100",
            "indexAnalyzer": {
                "tokenizer": {"class": "solr.StandardTokenizerFactory"},
                "filters": [
                    {"class": "solr.LowerCaseFilterFactory"},
                    {"class": "solr.ASCIIFoldingFilterFactory", "preserveOriginal": "true"}
                ]
            },
            "queryAnalyzer": {
                "tokenizer": {"class": "solr.StandardTokenizerFactory"},
                "filters": [
                    {"class": "solr.LowerCaseFilterFactory"},
                    {"class": "solr.SynonymGraphFilterFactory", "synonyms": "sinonimos.txt", "expand": "true", "ignoreCase": "true"},
                    {"class": "solr.ASCIIFoldingFilterFactory", "preserveOriginal": "true"}
                ]
            }
        }
    })

    # 5. text_es_suggest (Autocompletado e infijos)
    send_solr_request("schema", {
        "add-field-type": {
            "name": "text_es_suggest",
            "class": "solr.TextField",
            "positionIncrementGap": "100",
            "analyzer": {
                "tokenizer": {"class": "solr.StandardTokenizerFactory"},
                "filters": [
                    {"class": "solr.LowerCaseFilterFactory"},
                    {"class": "solr.ASCIIFoldingFilterFactory", "preserveOriginal": "false"}
                ]
            }
        }
    })

    # 6. text_es_completo (Pipeline integral en español)
    send_solr_request("schema", {
        "add-field-type": {
            "name": "text_es_completo",
            "class": "solr.TextField",
            "positionIncrementGap": "100",
            "indexAnalyzer": {
                "tokenizer": {"class": "solr.StandardTokenizerFactory"},
                "filters": [
                    {"class": "solr.LowerCaseFilterFactory"},
                    {"class": "solr.ASCIIFoldingFilterFactory", "preserveOriginal": "false"},
                    {"class": "solr.StopFilterFactory", "words": "stopwords_es.txt", "ignoreCase": "true"},
                    {"class": "solr.SnowballPorterFilterFactory", "language": "Spanish"}
                ]
            },
            "queryAnalyzer": {
                "tokenizer": {"class": "solr.StandardTokenizerFactory"},
                "filters": [
                    {"class": "solr.LowerCaseFilterFactory"},
                    {"class": "solr.ASCIIFoldingFilterFactory", "preserveOriginal": "false"},
                    {"class": "solr.StopFilterFactory", "words": "stopwords_es.txt", "ignoreCase": "true"},
                    {"class": "solr.SynonymGraphFilterFactory", "synonyms": "sinonimos.txt", "expand": "true", "ignoreCase": "true"},
                    {"class": "solr.SnowballPorterFilterFactory", "language": "Spanish"}
                ]
            }
        }
    })

    # Actualizar _text_ para usar el analizador de español completo
    try:
        send_solr_request("schema", {
            "replace-field": {
                "name": "_text_",
                "type": "text_es_completo",
                "multiValued": True,
                "indexed": True,
                "stored": False
            }
        })
    except Exception as e:
        print(f"  [AVISO] No se pudo reemplazar _text_: {e}")

    print("--- 2. Configurando Campos del Esquema Web ---")
    fields_to_add = [
        {"name": "url", "type": "string", "stored": True, "indexed": True},
        {"name": "dominio", "type": "string", "stored": True, "indexed": True, "docValues": True},
        {"name": "categoria", "type": "string", "stored": True, "indexed": True, "docValues": True},
        {"name": "tema", "type": "string", "stored": True, "indexed": True, "docValues": True},
        {"name": "fecha", "type": "string", "stored": True, "indexed": True},
        {"name": "profundidad", "type": "pint", "stored": True, "indexed": True, "docValues": True},
        {"name": "pagerank", "type": "pdouble", "stored": True, "indexed": True, "docValues": True},
        {"name": "enlaces_salientes", "type": "strings", "stored": True, "indexed": False, "multiValued": True},
        {"name": "titulo", "type": "text_es_completo", "stored": True, "indexed": True, "termVectors": True, "termPositions": True, "termOffsets": True},
        {"name": "encabezados", "type": "text_es_completo", "stored": True, "indexed": True, "multiValued": True},
        {"name": "contenido", "type": "text_es_completo", "stored": True, "indexed": True, "termVectors": True, "termPositions": True, "termOffsets": True},
        {"name": "sugerencia_texto", "type": "text_es_suggest", "stored": True, "indexed": True, "multiValued": True}
    ]

    for field in fields_to_add:
        send_solr_request("schema", {"add-field": field})

    print("--- 3. Configurando Campos de Copia (Copy Fields) ---")
    copy_fields = [
        {"source": "titulo", "dest": "_text_"},
        {"source": "encabezados", "dest": "_text_"},
        {"source": "contenido", "dest": "_text_"},
        {"source": "titulo", "dest": "sugerencia_texto"}
    ]
    for cf in copy_fields:
        send_solr_request("schema", {"add-copy-field": cf})

def configure_solrconfig():
    print("--- 4. Configurando Componentes de SolrConfig ---")
    
    # Configurar SearchComponent suggest
    suggest_component = {
        "add-searchcomponent": {
            "name": "suggest",
            "class": "solr.SuggestComponent",
            "suggester": {
                "name": "spanishSuggester",
                "lookupImpl": "AnalyzingInfixLookupFactory",
                "dictionaryImpl": "DocumentDictionaryFactory",
                "field": "sugerencia_texto",
                "suggestAnalyzerFieldType": "text_es_suggest",
                "buildOnStartup": "false",
                "buildOnCommit": "true",
                "minPrefixChars": 2
            }
        }
    }
    send_solr_request("config", suggest_component)

    # Configurar RequestHandler /suggest
    suggest_handler = {
        "add-requesthandler": {
            "name": "/suggest",
            "class": "solr.SearchHandler",
            "startup": "lazy",
            "defaults": {
                "suggest": "true",
                "suggest.dictionary": "spanishSuggester",
                "suggest.count": "10"
            },
            "components": ["suggest"]
        }
    }
    send_solr_request("config", suggest_handler)

    # Configurar /select con valores por defecto para búsqueda en español y highlighting
    update_select_defaults = {
        "update-requesthandler": {
            "name": "/select",
            "class": "solr.SearchHandler",
            "defaults": {
                "echoParams": "explicit",
                "rows": 10,
                "df": "_text_",
                "hl": "true",
                "hl.fl": "titulo,contenido",
                "hl.simple.pre": "<em>",
                "hl.simple.post": "</em>",
                "hl.snippets": 3,
                "hl.fragsize": 160
            }
        }
    }
    send_solr_request("config", update_select_defaults)

if __name__ == "__main__":
    print("Iniciando aprovisionamiento de Solr (Schema y Config)...")
    configure_schema()
    configure_solrconfig()
    print("¡Aprovisionamiento de Solr completado con éxito!")
