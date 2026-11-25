#!/usr/bin/env python3
"""
query_builder.py
Módulo de construcción segura, sanitización y normalización de consultas para Solr 10.
Soporta:
1. Modo Relevancia Ponderada / Libre (eDisMax):
    - Sanitización de caracteres peligrosos.
    - Balanceo de comillas de frase.
    - Preservación de caracteres en español y compatibilidad con expansión de sinónimos.
2. Modo Booleano Explícito:
    - Soporte para operadores AND, OR, NOT y agrupación con paréntesis.
    - Balanceo y corrección automática de paréntesis anidados.
    - Normalización de operadores en minúsculas (and, or, not) fuera de comillas.
    - Eliminación de operadores colgantes (dangling operators) y colapsado de operadores consecutivos.
    - Manejo seguro de consultas puramente negativas (ej. 'NOT término' -> '*:* NOT término').
    - Cero excepciones no controladas ante entradas arbitrarias del usuario.
"""

import re
from typing import Optional


class QueryBuilder:
    """Constructor y sanitizador de consultas para Apache Solr 10."""

    # Caracteres especiales de Lucene que requieren atención
    LUCENE_SPECIAL_CHARS = re.compile(r'([\+\-\!\(\)\{\}\[\]\^\"~*\?:\\/])')

    @classmethod
    def sanitize_edismax(cls, query: Optional[str]) -> str:
        """
        Sanitiza una consulta libre destinada al parser eDisMax.
        eDisMax maneja la mayoría de signos de puntuación, pero comillas desbalanceadas
        o caracteres especiales sueltos (como dos puntos aislados o slashes) pueden causar
        comportamientos no deseados o errores 400.
        """
        if not query or not query.strip():
            return "*:*"

        q = query.strip()

        # Balancear comillas dobles si el usuario dejó una abierta
        quote_count = q.count('"')
        if quote_count % 2 != 0:
            q += '"'

        # Limpiar secuencias de dos puntos sueltos que no correspondan a sintaxis de campo
        # e.g., 'tecnologia:' o ':tecnologia' sin valor
        q = re.sub(r'(?<=\s):+|:(?=\s|$)', ' ', q)

        # Colapsar espacios múltiples
        q = re.sub(r'\s+', ' ', q).strip()

        return q if q else "*:*"

    @classmethod
    def balance_parentheses(cls, text: str) -> str:
        """
        Garantiza que todos los paréntesis estén correctamente balanceados y cerrados.
        Elimina paréntesis de cierre huérfanos y cierra los paréntesis abiertos al final.
        """
        stack = []
        result = []
        
        # Procesar preservando comillas
        in_quotes = False
        i = 0
        while i < len(text):
            char = text[i]
            if char == '"':
                in_quotes = not in_quotes
                result.append(char)
            elif not in_quotes:
                if char == '(':
                    stack.append(len(result))
                    result.append(char)
                elif char == ')':
                    if stack:
                        stack.pop()
                        result.append(char)
                    else:
                        # Paréntesis de cierre sin apertura previa: ignorar
                        pass
                else:
                    result.append(char)
            else:
                result.append(char)
            i += 1

        # Si quedaron paréntesis abiertos sin cerrar en el stack, cerrarlos al final
        while stack:
            stack.pop()
            result.append(')')

        cleaned = "".join(result)
        # Eliminar paréntesis vacíos "()" o "(   )"
        cleaned = re.sub(r'\(\s*\)', '', cleaned)
        return cleaned

    @classmethod
    def sanitize_boolean(cls, query: Optional[str], default_field: str = "_text_") -> str:
        """
        Sanitiza y normaliza una consulta para modo booleano explícito.
        - Balancea comillas y paréntesis.
        - Normaliza 'and', 'or', 'not' a mayúsculas 'AND', 'OR', 'NOT'.
        - Elimina operadores colgantes iniciales o finales (ej. 'AND coche' -> 'coche', 'coche AND' -> 'coche').
        - Colapsa operadores consecutivos (ej. 'AND OR' -> 'OR').
        - Convierte consultas puramente negativas 'NOT x' en '*:* NOT x'.
        """
        if not query or not query.strip():
            return "*:*"

        q = query.strip()

        # Balancear comillas dobles
        if q.count('"') % 2 != 0:
            q += '"'

        # Balancear paréntesis
        q = cls.balance_parentheses(q)

        # Normalizar operadores booleanos fuera de comillas
        parts = []
        tokens = re.split(r'("[^"]*")', q)
        for token in tokens:
            if token.startswith('"') and token.endswith('"'):
                parts.append(token)
            else:
                # Reemplazar operadores en minúsculas rodeados de límites de palabra
                sub = token
                sub = re.sub(r'\band\b', 'AND', sub, flags=re.IGNORECASE)
                sub = re.sub(r'\bor\b', 'OR', sub, flags=re.IGNORECASE)
                sub = re.sub(r'\bnot\b', 'NOT', sub, flags=re.IGNORECASE)
                parts.append(sub)

        q = "".join(parts)

        # Limpiar operadores booleanos repetidos o en conflicto (ej. 'AND AND', 'OR AND')
        q = re.sub(r'\b(AND|OR)\s+(AND|OR)\b', r'\2', q)
        q = re.sub(r'\bNOT\s+NOT\b', '', q)
        q = re.sub(r'\b(AND|OR)\s+NOT\b', r'NOT', q)  # 'AND NOT' en Lucene se reduce a 'NOT'

        # Limpiar paréntesis internos vacíos o con solo operadores
        q = re.sub(r'\(\s*(AND|OR|NOT)\s*', '(', q)
        q = re.sub(r'\s*(AND|OR|NOT)\s*\)', ')', q)
        q = re.sub(r'\(\s*\)', '', q)

        # Colapsar espacios
        q = re.sub(r'\s+', ' ', q).strip()

        # Limpiar operadores colgantes al inicio o al final
        q = re.sub(r'^(AND|OR)\s+', '', q)
        q = re.sub(r'\s+(AND|OR|NOT)$', '', q)

        # Si la consulta empieza con NOT o es únicamente negativa (ej. 'NOT x'), anteponer '*:*'
        if re.match(r'^NOT\s+', q):
            q = f"*:* {q}"
        elif q == "NOT":
            return "*:*"

        # Re-balancear paréntesis si la limpieza eliminó contenido
        q = cls.balance_parentheses(q).strip()

        return q if q else "*:*"

    @classmethod
    def build(cls, query: Optional[str], mode: str = "edismax", default_field: str = "_text_") -> str:
        """
        Método unificado para construir y sanitizar consultas según el modo elegido.
        
        :param query: Texto ingresado por el usuario.
        :param mode: 'edismax' (relevancia libre) o 'boolean' (operadores AND/OR/NOT).
        :param default_field: Campo por defecto en Solr (generalmente '_text_').
        :return: Consulta sanitizada y lista para enviarse a Solr.
        """
        if mode == "boolean":
            return cls.sanitize_boolean(query, default_field=default_field)
        return cls.sanitize_edismax(query)
