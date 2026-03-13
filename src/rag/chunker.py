"""
Chunker semántico para documentos Saxun.
Estrategia: sección → párrafo → tokens, con overlap configurable.
FAQs y tablas se tratan como chunks atómicos.
"""
import re
import hashlib
from dataclasses import dataclass, field
from typing import Optional
from loguru import logger

from src.config import get_settings


@dataclass
class RawChunk:
    content: str
    section: str = ""
    chunk_index: int = 0
    language: str = "es"
    metadata: dict = field(default_factory=dict)

    def generate_id(self, doc_id: str) -> str:
        hash_input = f"{doc_id}_{self.chunk_index}_{self.content[:50]}"
        short_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:8]
        return f"{doc_id}_chunk_{self.chunk_index:04d}_{short_hash}"


class SemanticChunker:
    """
    Divide documentos en chunks semánticos.
    Prioriza divisiones por encabezados y párrafos sobre tokens fijos.
    """

    # Patrones de encabezados (Markdown y texto plano)
    HEADING_PATTERNS = [
        re.compile(r'^#{1,4}\s+(.+)$', re.MULTILINE),
        re.compile(r'^([A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ\s]{3,50})\n[=\-]{3,}', re.MULTILINE),
        re.compile(r'^\d+\.\s+([A-ZÁÉÍÓÚÜÑ].{5,80})$', re.MULTILINE),
    ]

    FAQ_PATTERN = re.compile(
        r'(?:^|\n)(?:P(?:regunta)?:|Q:)\s*(.+?)(?:\n(?:R(?:espuesta)?:|A:)\s*(.+?)(?=\n(?:P(?:regunta)?:|Q:)|\Z))',
        re.DOTALL | re.IGNORECASE,
    )
    # Patrón para FAQs en formato ¿Pregunta? \n Respuesta (típico de PDFs)
    FAQ_QUESTION_PATTERN = re.compile(
        r'(¿[^?]+\?)\s*\n((?:(?!¿).)+)',
        re.DOTALL,
    )

    def __init__(self):
        s = get_settings()
        self.max_tokens = s.rag_chunk_size
        self.overlap_tokens = s.rag_chunk_overlap

    def chunk_document(
        self,
        text: str,
        doc_type: str = "general",
        language: str = "es",
    ) -> list[RawChunk]:
        """
        Divide el texto en chunks según el tipo de documento.
        doc_type: general | faq | catalog | policy
        """
        text = self._clean_text(text)

        if doc_type == "faq":
            return self._chunk_faq(text, language)

        # Para todos los demás: chunking por secciones + párrafos
        sections = self._split_by_sections(text)
        chunks: list[RawChunk] = []
        chunk_idx = 0

        for section_title, section_text in sections:
            paragraphs = self._split_by_paragraphs(section_text)
            current_chunk = ""
            current_tokens = 0

            for para in paragraphs:
                para_tokens = self._estimate_tokens(para)

                # Tabla completa = chunk atómico
                if self._is_table(para):
                    if current_chunk:
                        chunks.append(RawChunk(
                            content=current_chunk.strip(),
                            section=section_title,
                            chunk_index=chunk_idx,
                            language=language,
                        ))
                        chunk_idx += 1
                        current_chunk = ""
                        current_tokens = 0
                    if para_tokens <= self.max_tokens * 1.5:
                        chunks.append(RawChunk(
                            content=para.strip(),
                            section=section_title,
                            chunk_index=chunk_idx,
                            language=language,
                            metadata={"is_table": True},
                        ))
                        chunk_idx += 1
                    continue

                # Si el párrafo solo no cabe → subdividir por oraciones
                if para_tokens > self.max_tokens:
                    if current_chunk:
                        chunks.append(RawChunk(
                            content=current_chunk.strip(),
                            section=section_title,
                            chunk_index=chunk_idx,
                            language=language,
                        ))
                        chunk_idx += 1
                        current_chunk = ""
                        current_tokens = 0
                    sub_chunks = self._split_by_sentences(para, section_title, language)
                    for sc in sub_chunks:
                        sc.chunk_index = chunk_idx
                        chunks.append(sc)
                        chunk_idx += 1
                    continue

                # Si añadir este párrafo excede el límite → flush y empezar nuevo
                if current_tokens + para_tokens > self.max_tokens and current_chunk:
                    chunks.append(RawChunk(
                        content=current_chunk.strip(),
                        section=section_title,
                        chunk_index=chunk_idx,
                        language=language,
                    ))
                    chunk_idx += 1
                    # Overlap: añadir últimas N palabras del chunk anterior
                    overlap_text = self._get_overlap(current_chunk)
                    current_chunk = overlap_text + "\n" + para
                    current_tokens = self._estimate_tokens(current_chunk)
                else:
                    current_chunk = current_chunk + "\n" + para if current_chunk else para
                    current_tokens += para_tokens

            # Flush chunk pendiente
            if current_chunk.strip():
                chunks.append(RawChunk(
                    content=current_chunk.strip(),
                    section=section_title,
                    chunk_index=chunk_idx,
                    language=language,
                ))
                chunk_idx += 1

        # Filtrar chunks demasiado cortos
        valid = [c for c in chunks if self._estimate_tokens(c.content) >= 20]
        logger.debug(f"Chunking: {len(chunks)} chunks → {len(valid)} válidos (≥20 tokens)")
        return valid

    # ── Métodos privados ──────────────────────────────────────────────────────

    def _chunk_faq(self, text: str, language: str) -> list[RawChunk]:
        """FAQs: cada par pregunta+respuesta = 1 chunk atómico."""
        chunks = []
        idx = 0

        # Intentar patrones FAQ estructurados (P:/R: format)
        for m in self.FAQ_PATTERN.finditer(text):
            question = m.group(1).strip()
            answer = (m.group(2) or "").strip()
            content = f"Pregunta: {question}\nRespuesta: {answer}"
            chunks.append(RawChunk(
                content=content,
                section="FAQ",
                chunk_index=idx,
                language=language,
                metadata={"is_faq": True},
            ))
            idx += 1

        # Intentar patrón ¿Pregunta? \n Respuesta (típico de PDFs en español)
        if not chunks:
            for m in self.FAQ_QUESTION_PATTERN.finditer(text):
                question = m.group(1).strip()
                answer = m.group(2).strip()
                if len(answer) < 10:
                    continue
                content = f"Pregunta: {question}\nRespuesta: {answer}"
                chunks.append(RawChunk(
                    content=content,
                    section="FAQ",
                    chunk_index=idx,
                    language=language,
                    metadata={"is_faq": True},
                ))
                idx += 1

        # Fallback: chunking general si no se detectaron FAQs
        if not chunks:
            logger.debug("No se detectaron FAQs estructuradas, usando chunking general")
            return self.chunk_document(text, "general", language)

        return chunks

    def _clean_text(self, text: str) -> str:
        """Limpieza básica del texto."""
        # Normalizar saltos de línea
        text = re.sub(r'\r\n', '\n', text)
        # Eliminar líneas de solo espacios repetidas
        text = re.sub(r'\n{3,}', '\n\n', text)
        # Eliminar espacios al final de línea
        text = re.sub(r' +\n', '\n', text)
        return text.strip()

    def _split_by_sections(self, text: str) -> list[tuple[str, str]]:
        """Divide el texto por encabezados. Devuelve (título, contenido)."""
        parts = re.split(r'\n(?=#{1,4}\s|\d+\.\s)', text)
        heading_re = re.compile(r'^(#{1,4}\s+|\d+\.\s+)')
        sections = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            lines = part.split('\n', 1)
            first_line = lines[0].strip()
            # Solo extraer título si la primera línea es un encabezado real
            if heading_re.match(first_line):
                title = heading_re.sub('', first_line).strip()
                content = lines[1].strip() if len(lines) > 1 else ""
            else:
                title = "General"
                content = part
            if content:
                sections.append((title, content))
        return sections if sections else [("General", text)]

    def _split_by_paragraphs(self, text: str) -> list[str]:
        """Divide por párrafos (doble salto de línea)."""
        paragraphs = re.split(r'\n\n+', text)
        return [p.strip() for p in paragraphs if p.strip()]

    def _split_by_sentences(
        self, text: str, section: str, language: str
    ) -> list[RawChunk]:
        """Divide texto largo en oraciones."""
        sentences = re.split(r'(?<=[.!?])\s+', text)
        chunks = []
        current = ""
        idx = 0
        for sent in sentences:
            if self._estimate_tokens(current + " " + sent) > self.max_tokens and current:
                chunks.append(RawChunk(
                    content=current.strip(),
                    section=section,
                    chunk_index=idx,
                    language=language,
                ))
                idx += 1
                current = sent
            else:
                current = (current + " " + sent).strip()
        if current:
            chunks.append(RawChunk(
                content=current.strip(),
                section=section,
                chunk_index=idx,
                language=language,
            ))
        return chunks

    def _get_overlap(self, text: str) -> str:
        """Devuelve las últimas N palabras para overlap."""
        words = text.split()
        overlap_words = max(0, len(words) - self.overlap_tokens)
        return " ".join(words[overlap_words:])

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Estimación rápida de tokens (4 chars ≈ 1 token para español)."""
        return len(text) // 4

    @staticmethod
    def _is_table(text: str) -> bool:
        """Detecta si el texto es una tabla (Markdown o delimitada)."""
        lines = text.strip().split('\n')
        if len(lines) < 2:
            return False
        pipe_lines = sum(1 for line in lines if '|' in line)
        return pipe_lines >= len(lines) * 0.6
