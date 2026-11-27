"""
Módulo de Motor de Búsqueda y Recuperación de Información en Español (Apache Solr 10).
Parte de la arquitectura del Sistema de Búsqueda y Recuperación (ADR-0001).
Responsable: César.
"""

from .client import SolrSearchClient
from .query_builder import QueryBuilder
from .xml_exporter import XMLExporter, export_to_xml, export_to_xml_bytes

__all__ = [
    "SolrSearchClient",
    "QueryBuilder",
    "XMLExporter",
    "export_to_xml",
    "export_to_xml_bytes",
]
