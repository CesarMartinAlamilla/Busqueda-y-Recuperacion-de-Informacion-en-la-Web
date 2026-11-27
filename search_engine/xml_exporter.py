#!/usr/bin/env python3
"""
xml_exporter.py
Serializador de resultados de búsqueda a formato XML bien formado (Extra #2).
Utiliza xml.etree.ElementTree para estructurar:
- Metadatos de la consulta (término, modo, total, paginación, tiempo de respuesta).
- Facetas dinámicas con conteos por categoría, dominio y tipo.
- Documentos recuperados con identificadores, metadatos, relevancia ponderada (score) y snippets resaltados.
- Sugerencias ortográficas ('did_you_mean').
- Salida garantizada con declaración UTF-8 y escape automático de caracteres especiales.
"""

import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional


class XMLExporter:
    """Serializador para transformar diccionarios de respuesta de búsqueda en XML estándar."""

    @classmethod
    def dict_to_xml_element(cls, response_data: Dict[str, Any]) -> ET.Element:
        """Construye un árbol XML de ElementTree a partir de la respuesta del buscador."""
        root = ET.Element("search_response")

        # 1. Metadatos de la búsqueda
        meta = ET.SubElement(root, "metadata")
        ET.SubElement(meta, "query").text = str(response_data.get("query", ""))
        ET.SubElement(meta, "sanitized_query").text = str(response_data.get("sanitized_query", ""))
        ET.SubElement(meta, "mode").text = str(response_data.get("mode", "edismax"))
        ET.SubElement(meta, "total").text = str(response_data.get("total", 0))
        ET.SubElement(meta, "page").text = str(response_data.get("page", 1))
        ET.SubElement(meta, "page_size").text = str(response_data.get("page_size", 10))
        ET.SubElement(meta, "total_pages").text = str(response_data.get("total_pages", 0))
        ET.SubElement(meta, "query_time_ms").text = str(response_data.get("query_time_ms", 0))

        spelling = response_data.get("spelling_suggestion") or response_data.get("did_you_mean")
        if spelling:
            ET.SubElement(meta, "spelling_suggestion").text = str(spelling)

        # 2. Facetas dinámicas
        facets_elem = ET.SubElement(root, "facets")
        facets_data = response_data.get("facets", {})
        for field_name, items in facets_data.items():
            facet_elem = ET.SubElement(facets_elem, "facet", name=field_name)
            if isinstance(items, dict):
                for val, count in items.items():
                    ET.SubElement(facet_elem, "item", value=str(val), count=str(count))
            elif isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        ET.SubElement(
                            facet_elem,
                            "item",
                            value=str(item.get("value", "")),
                            count=str(item.get("count", 0))
                        )

        # 3. Resultados de documentos
        results_elem = ET.SubElement(root, "results")
        docs = response_data.get("results", [])
        for doc in docs:
            doc_id = str(doc.get("id", ""))
            doc_elem = ET.SubElement(results_elem, "document", id=doc_id)

            ET.SubElement(doc_elem, "title").text = str(doc.get("title", ""))
            ET.SubElement(doc_elem, "url").text = str(doc.get("url", ""))
            ET.SubElement(doc_elem, "domain").text = str(doc.get("domain_s", ""))
            ET.SubElement(doc_elem, "category").text = str(doc.get("category_s", ""))
            ET.SubElement(doc_elem, "doc_type").text = str(doc.get("doc_type_s", ""))
            ET.SubElement(doc_elem, "published_at").text = str(doc.get("published_at_dt", ""))
            ET.SubElement(doc_elem, "score").text = str(doc.get("score", 0.0))

            # Contenido (opcional, truncado para evitar payloads gigantescos en XML)
            content_text = str(doc.get("content", ""))
            ET.SubElement(doc_elem, "content").text = content_text

            # Snippets contextuales
            snippets_elem = ET.SubElement(doc_elem, "snippets")
            
            # Snippet principal
            main_snippet = doc.get("snippet", "")
            if main_snippet:
                ET.SubElement(snippets_elem, "snippet", field="main").text = str(main_snippet)

            # Snippets desglosados
            doc_snippets = doc.get("snippets", {})
            if isinstance(doc_snippets, dict):
                for field_s, s_list in doc_snippets.items():
                    if isinstance(s_list, list):
                        for s_text in s_list:
                            ET.SubElement(snippets_elem, "snippet", field=field_s).text = str(s_text)

        return root

    @classmethod
    def export(cls, response_data: Dict[str, Any], pretty: bool = True) -> str:
        """
        Serializa la respuesta estructurada a una cadena XML bien formada con declaración UTF-8.
        Escapa automáticamente caracteres especiales (&, <, >, etc.) mediante ElementTree.
        """
        root = cls.dict_to_xml_element(response_data)
        if pretty and hasattr(ET, "indent"):
            ET.indent(root, space="  ", level=0)

        xml_bytes = ET.tostring(root, encoding="utf-8", method="xml", xml_declaration=True)
        return xml_bytes.decode("utf-8")

    @classmethod
    def export_bytes(cls, response_data: Dict[str, Any], pretty: bool = True) -> bytes:
        """Retorna los bytes XML directos codificados en UTF-8, ideal para StreamingResponse en FastAPI."""
        root = cls.dict_to_xml_element(response_data)
        if pretty and hasattr(ET, "indent"):
            ET.indent(root, space="  ", level=0)
        return ET.tostring(root, encoding="utf-8", method="xml", xml_declaration=True)


def export_to_xml(response_data: Dict[str, Any], pretty: bool = True) -> str:
    """Función de nivel superior para exportar a XML."""
    return XMLExporter.export(response_data, pretty=pretty)


def export_to_xml_bytes(response_data: Dict[str, Any], pretty: bool = True) -> bytes:
    """Función de nivel superior para exportar a bytes XML."""
    return XMLExporter.export_bytes(response_data, pretty=pretty)
