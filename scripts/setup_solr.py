#!/usr/bin/env python3
"""
setup_solr.py
Aprovisiona programáticamente Apache Solr 10 para el core 'buscador_es'.
Implementa:
- FieldType 'text_es' con normalización, stopwords, lematización en español y expansión de sinónimos.
- FieldType 'text_es_trigram' basado en EdgeNGram (minGram=3, maxGram=15) para autocompletado y tolerancia a fallos.
- Esquema unificado oficial: id, title, content, url, domain_s, category_s, doc_type_s, published_at_dt, suggest_text, _text_.
- SearchComponent suggest ('spanishSuggester') con AnalyzingInfixLookupFactory (minPrefixChars=3).
- SearchComponent spellcheck ('spanishSpellCheck') con DirectSolrSpellChecker.
- RequestHandlers /suggest, /spell y /select optimizados.
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

DEFAULT_SOLR_URL = os.environ.get("SOLR_URL", "http://localhost:8983/solr/buscador_es")

def send_solr_request(base_url: str, endpoint: str, payload: dict) -> dict:
    url = f"{base_url}/{endpoint}"
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
        err_text = body
        try:
            err_json = json.loads(body)
            msg = err_json.get("error", {}).get("msg", "")
            details = err_json.get("error", {}).get("details", [])
            detail_msgs = []
            for d in details:
                if isinstance(d, dict) and "errorMessages" in d:
                    detail_msgs.extend(d["errorMessages"])
            err_text = f"{msg} | " + " ; ".join(detail_msgs)
        except Exception:
            err_text = body

        # Si ya existe, intentar reemplazar según el comando
        action = list(payload.keys())[0] if payload else ""
        if "already exists" in err_text.lower() or "duplicate" in err_text.lower():
            if action == "add-field-type":
                replace_payload = {"replace-field-type": payload["add-field-type"]}
                print(f"  [INFO] Tipo de campo ya existe. Reemplazando con 'replace-field-type'...")
                return send_solr_request(base_url, endpoint, replace_payload)
            elif action == "add-field":
                replace_payload = {"replace-field": payload["add-field"]}
                print(f"  [INFO] Campo ya existe. Reemplazando con 'replace-field'...")
                return send_solr_request(base_url, endpoint, replace_payload)
            elif action == "add-requesthandler":
                update_payload = {"update-requesthandler": payload["add-requesthandler"]}
                print(f"  [INFO] RequestHandler ya existe. Actualizando con 'update-requesthandler'...")
                return send_solr_request(base_url, endpoint, update_payload)
            elif action == "add-searchcomponent":
                update_payload = {"update-searchcomponent": payload["add-searchcomponent"]}
                print(f"  [INFO] SearchComponent ya existe. Actualizando con 'update-searchcomponent'...")
                return send_solr_request(base_url, endpoint, update_payload)
            elif action == "add-copy-field":
                print(f"  [INFO] CopyField ya existe. Omitiendo.")
                return {"status": "already_exists"}

        print(f"  [ERROR {e.code}] en {endpoint}: {err_text}")
        raise RuntimeError(f"Error HTTP {e.code} en {endpoint}: {err_text}")

def ensure_dictionaries_in_container():
    """Copia los diccionarios locales hacia el core en Docker si se detecta docker."""
    try:
        cmd = [
            "docker", "--context", "desktop-linux", "exec", "solr-ri", "sh", "-c",
            "mkdir -p /var/solr/data/buscador_es/conf && "
            "cp /opt/solr_custom_config/sinonimos.txt /var/solr/data/buscador_es/conf/ && "
            "cp /opt/solr_custom_config/stopwords_es.txt /var/solr/data/buscador_es/conf/ && "
            "cp /opt/solr_custom_config/sinonimos.txt /var/solr/data/buscador_es/ && "
            "cp /opt/solr_custom_config/stopwords_es.txt /var/solr/data/buscador_es/"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            print("  [OK] Diccionarios sincronizados en el contenedor Solr.")
        else:
            print(f"  [AVISO] No se pudieron copiar diccionarios vía Docker: {res.stderr.strip()}")
    except Exception as ex:
        print(f"  [AVISO] Verificación de Docker omitida: {ex}")

def configure_schema(base_url: str):
    print("\n--- 1. Configurando Tipos de Campo (Field Types) ---")

    # 1.1 text_es (Pipeline lingüístico completo en español con sinónimos en consulta)
    send_solr_request(base_url, "schema", {
        "add-field-type": {
            "name": "text_es",
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

    # 1.2 text_es_trigram (Trigramas de caracteres basados en EdgeNGram para autocompletado y typo-tolerance)
    send_solr_request(base_url, "schema", {
        "add-field-type": {
            "name": "text_es_trigram",
            "class": "solr.TextField",
            "positionIncrementGap": "100",
            "indexAnalyzer": {
                "tokenizer": {"class": "solr.StandardTokenizerFactory"},
                "filters": [
                    {"class": "solr.LowerCaseFilterFactory"},
                    {"class": "solr.ASCIIFoldingFilterFactory", "preserveOriginal": "false"},
                    {
                        "class": "solr.EdgeNGramFilterFactory",
                        "minGramSize": "3",
                        "maxGramSize": "15"
                    }
                ]
            },
            "queryAnalyzer": {
                "tokenizer": {"class": "solr.StandardTokenizerFactory"},
                "filters": [
                    {"class": "solr.LowerCaseFilterFactory"},
                    {"class": "solr.ASCIIFoldingFilterFactory", "preserveOriginal": "false"}
                ]
            }
        }
    })

    # 1.3 text_es_completo (Alias para retrocompatibilidad con scripts existentes)
    send_solr_request(base_url, "schema", {
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

    # 1.4 Reemplazar campo por defecto _text_ para usar analizador text_es
    try:
        send_solr_request(base_url, "schema", {
            "replace-field": {
                "name": "_text_",
                "type": "text_es",
                "multiValued": True,
                "indexed": True,
                "stored": False
            }
        })
        print("  [OK] Campo _text_ actualizado a tipo 'text_es'.")
    except Exception as e:
        print(f"  [AVISO] No se pudo reemplazar _text_ (puede que ya esté configurado): {e}")

    print("\n--- 2. Configurando Campos del Contrato Oficial (ADR-0001) ---")
    fields_to_add = [
        {"name": "title", "type": "text_es", "stored": True, "indexed": True, "termVectors": True, "termPositions": True, "termOffsets": True},
        {"name": "content", "type": "text_es", "stored": True, "indexed": True, "termVectors": True, "termPositions": True, "termOffsets": True},
        {"name": "url", "type": "string", "stored": True, "indexed": True},
        {"name": "domain_s", "type": "string", "stored": True, "indexed": True, "docValues": True},
        {"name": "category_s", "type": "string", "stored": True, "indexed": True, "docValues": True},
        {"name": "doc_type_s", "type": "string", "stored": True, "indexed": True, "docValues": True},
        {"name": "published_at_dt", "type": "pdate", "stored": True, "indexed": True},
        {"name": "suggest_text", "type": "text_es_trigram", "stored": True, "indexed": True, "multiValued": True}
    ]

    for field in fields_to_add:
        send_solr_request(base_url, "schema", {"add-field": field})

    print("\n--- 3. Configurando Campos de Copia (Copy Fields) ---")
    copy_fields = [
        {"source": "title", "dest": "_text_"},
        {"source": "content", "dest": "_text_"},
        {"source": "title", "dest": "suggest_text"},
        {"source": "category_s", "dest": "suggest_text"}
    ]
    for cf in copy_fields:
        send_solr_request(base_url, "schema", {"add-copy-field": cf})

def configure_solrconfig(base_url: str):
    print("\n--- 4. Configurando Componentes de SolrConfig (Suggest, SpellCheck, Select) ---")
    
    # 4.1 Deshabilitar autocreación de campos desconocidos (producción estricta)
    try:
        send_solr_request(base_url, "config", {
            "set-user-property": {"update.autoCreateFields": "false"}
        })
    except Exception as ex:
        print(f"  [AVISO] No se pudo fijar autoCreateFields=false: {ex}")

    # 4.2 Suggester con AnalyzingInfixLookupFactory sobre suggest_text (minPrefixChars=3 por trigramas)
    suggest_component = {
        "add-searchcomponent": {
            "name": "suggest",
            "class": "solr.SuggestComponent",
            "suggester": {
                "name": "spanishSuggester",
                "lookupImpl": "AnalyzingInfixLookupFactory",
                "dictionaryImpl": "DocumentDictionaryFactory",
                "field": "suggest_text",
                "suggestAnalyzerFieldType": "text_es_trigram",
                "buildOnStartup": "false",
                "buildOnCommit": "true",
                "minPrefixChars": 3
            }
        }
    }
    send_solr_request(base_url, "config", suggest_component)

    # 4.3 RequestHandler /suggest
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
    send_solr_request(base_url, "config", suggest_handler)

    # 4.4 SpellCheckComponent con DirectSolrSpellChecker
    spell_component = {
        "add-searchcomponent": {
            "name": "spellcheck",
            "class": "solr.SpellCheckComponent",
            "spellchecker": {
                "name": "default",
                "field": "_text_",
                "classname": "solr.DirectSolrSpellChecker",
                "distanceMeasure": "internal",
                "accuracy": 0.7,
                "maxEdits": 2,
                "minPrefix": 1,
                "maxInspections": 5,
                "minQueryLength": 4,
                "maxQueryFrequency": 0.01
            }
        }
    }
    send_solr_request(base_url, "config", spell_component)

    # 4.5 RequestHandler /spell
    spell_handler = {
        "add-requesthandler": {
            "name": "/spell",
            "class": "solr.SearchHandler",
            "startup": "lazy",
            "defaults": {
                "spellcheck": "true",
                "spellcheck.dictionary": "default",
                "spellcheck.collate": "true",
                "spellcheck.extendedResults": "true",
                "spellcheck.count": "5"
            },
            "components": ["spellcheck"]
        }
    }
    send_solr_request(base_url, "config", spell_handler)

    # 4.6 RequestHandler /select con valores por defecto para ranking eDisMax y Highlighting
    update_select_defaults = {
        "update-requesthandler": {
            "name": "/select",
            "class": "solr.SearchHandler",
            "defaults": {
                "echoParams": "explicit",
                "rows": 10,
                "df": "_text_",
                "defType": "edismax",
                "qf": "title^3.5 category_s^2.0 content^1.0",
                "pf": "title^5.0 content^2.0",
                "hl": "true",
                "hl.fl": "title,content",
                "hl.simple.pre": "<mark>",
                "hl.simple.post": "</mark>",
                "hl.snippets": 3,
                "hl.fragsize": 180
            }
        }
    }
    send_solr_request(base_url, "config", update_select_defaults)

def main():
    target_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SOLR_URL

    print(f"  APROVISIONANDO CORE SOLR: {target_url}")
    
    # Sincronizar diccionarios en contenedor
    ensure_dictionaries_in_container()

    # Configurar esquema y componentes
    configure_schema(target_url)
    configure_solrconfig(target_url)

    print("\n[EXITO] Aprovisionamiento de 'buscador_es' completado sin errores.")

if __name__ == "__main__":
    main()
