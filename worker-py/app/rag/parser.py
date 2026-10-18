"""Layout-aware parsing with exact embedding-token validation, never truncation."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from threading import RLock

from pydantic import BaseModel, ConfigDict, Field

DENSE_MODEL = "BAAI/bge-small-en-v1.5"
MAX_EMBEDDING_TOKENS = 512
CHUNK_TOKENS = 450


class ClinicalChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol_name: str
    headings: list[str] = Field(default_factory=list)
    page_numbers: list[int] = Field(default_factory=list)
    raw_text: str
    enriched_text: str
    token_count: int = Field(le=MAX_EMBEDDING_TOKENS, gt=0)


class ChunkBudgetError(ValueError):
    """The document cannot be represented without silently losing clinical content."""


class ClinicalDocumentProcessor:
    def __init__(self, cache_dir: str = "./model_cache"):
        from docling.chunking import HybridChunker
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import (
            PdfPipelineOptions,
            TableFormerMode,
        )
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling_core.transforms.chunker.hierarchical_chunker import (
            ChunkingDocSerializer,
            ChunkingSerializerProvider,
        )
        from docling_core.transforms.serializer.markdown import MarkdownTableSerializer
        from transformers import AutoTokenizer

        class ClinicalTableSerializer(ChunkingSerializerProvider):
            def get_serializer(self, doc):
                return ChunkingDocSerializer(
                    doc=doc, table_serializer=MarkdownTableSerializer()
                )

        self.tokenizer = AutoTokenizer.from_pretrained(DENSE_MODEL, cache_dir=cache_dir)
        options = PdfPipelineOptions(do_table_structure=True)
        options.table_structure_options.mode = TableFormerMode.ACCURATE
        self.converter = DocumentConverter(
            allowed_formats=[InputFormat.PDF, InputFormat.MD],
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)},
        )
        # Docling applies this budget to contextualized text, including section headings.
        self.chunker = HybridChunker(
            tokenizer=self.tokenizer,
            max_tokens=CHUNK_TOKENS,
            merge_peers=True,
            serializer_provider=ClinicalTableSerializer(),
        )
        self._lock = RLock()

    def token_count(self, text: str) -> int:
        return len(
            self.tokenizer.encode(text, add_special_tokens=True, truncation=False)
        )

    def _chunks(self, document, protocol_name: str) -> list[ClinicalChunk]:
        if not protocol_name.strip() or len(protocol_name) > 256:
            raise ValueError("Protocol name must contain 1–256 characters")
        prefix = f"[Protocol: {protocol_name}] "
        if self.token_count(prefix) >= MAX_EMBEDDING_TOKENS - 16:
            raise ChunkBudgetError(
                "Protocol header leaves insufficient room for document content"
            )
        result = []
        for chunk in self.chunker.chunk(document):
            enriched = prefix + self.chunker.contextualize(chunk)
            count = self.token_count(enriched)
            # The nominal 62-token buffer is not a proof: headers can exceed it.
            # Fail closed rather than truncate a table, dosage, or breadcrumb silently.
            if count > MAX_EMBEDDING_TOKENS:
                raise ChunkBudgetError(
                    "Contextualized chunk exceeds 512 tokens; shorten the protocol name or section headings"
                )
            if not chunk.text.strip():
                continue
            pages = sorted(
                {
                    p.page_no
                    for item in chunk.meta.doc_items
                    for p in (getattr(item, "prov", None) or [])
                }
            )
            result.append(
                ClinicalChunk(
                    protocol_name=protocol_name,
                    headings=list(chunk.meta.headings or []),
                    page_numbers=pages,
                    raw_text=chunk.text,
                    enriched_text=enriched,
                    token_count=count,
                )
            )
        if not result:
            raise ValueError("Document contains no readable clinical content")
        return result

    def parse_document(
        self, file_path: str, protocol_name: str
    ) -> tuple[str, list[ClinicalChunk]]:
        path = Path(file_path)
        if not path.is_file() or path.suffix.lower() not in {
            ".pdf",
            ".md",
            ".markdown",
        }:
            raise ValueError("Provide a local PDF or Markdown file")
        if path.stat().st_size > 5 * 1024 * 1024:
            raise ValueError("Document exceeds the 5 MB limit")
        with self._lock:
            converted = self.converter.convert(
                path, raises_on_error=True, max_num_pages=100
            )
            document = converted.document
            return document.export_to_markdown(), self._chunks(document, protocol_name)

    def process_document(
        self, file_path: str, protocol_name: str
    ) -> list[ClinicalChunk]:
        return self.parse_document(file_path, protocol_name)[1]

    def chunk_markdown(self, md_text: str, protocol_name: str) -> list[ClinicalChunk]:
        from docling.datamodel.base_models import DocumentStream

        if not md_text.strip() or len(md_text) > 200000:
            raise ValueError("Reference text must contain 1–200,000 characters")
        with self._lock:
            source = DocumentStream(
                name="protocol.md", stream=BytesIO(md_text.encode("utf-8"))
            )
            converted = self.converter.convert(source, raises_on_error=True)
            return self._chunks(converted.document, protocol_name)
