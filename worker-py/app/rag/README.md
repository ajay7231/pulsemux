# Clinical RAG

Python 3.10+ (Docker uses 3.12). PostgreSQL remains the system of record for
workspaces, ingestion state, approval, published snapshots, and provenance. Qdrant
stores local 384-dimensional BGE dense vectors and BM25 sparse vectors.

## Local acceptance run

From the repository root:

```sh
docker compose -f deploy/docker-compose.yml up -d qdrant
docker build -t pulsemux-rag:dev -f deploy/rag.Dockerfile .
docker run --rm --network deploy_pulsemux-net \
  -e QDRANT_URL=http://qdrant:6333 \
  -v "$PWD/worker-py:/app:ro" -v pulsemux-rag-models:/models \
  pulsemux-rag:dev
```

The synthetic clinical fixture checks the 512-token cap, preservation of dosage
text, deterministic upserts, and warm retrieval p95 <25ms across 20 requests.
Measured time includes query embeddings, thread scheduling, gRPC, and result
formatting. Hardware/load/network/corpus size affect latency; failure is reported
rather than hidden by mocked embeddings or changing the threshold. Verification
uses a unique tenant and retains its points; it never deletes hospital knowledge.

Model downloads happen on first setup. Docker explicitly installs CPU-only PyTorch
for Docling; FastEmbed inference uses ONNX CPU. Persist the model cache in production.

## Hospital workflow

Set `QDRANT_URL` and `RAG_MODEL_CACHE` for the API and a separate ingestion process,
run `alembic -c worker-py/alembic.ini upgrade head`, then start:

```sh
python -m app.rag.worker
```

`deploy/platform-compose.yml` includes a Qdrant service and `ingestion-worker` with
shared source/model storage. Run the ingestion worker separately from campaign
workers. The API warms embeddings and the Qdrant connection before startup completes.
Do not use the repository's existing Python 3.9 virtualenv for the enabled RAG backend.

Multiple documents can be uploaded in one dashboard selection (up to 10 files,
5 MB each). API uploads persist sources with private permissions and queue a SQL
job, returning immediately. Markdown/text additions use the same pipeline.
An ingestion-only worker claims jobs with a 30-minute lease and a fencing token;
interrupted processing is reclaimed. Failed jobs expose a generic status and an
explicit retry action. Parsing and inference run outside the request event loop.
No campaign scheduler or calling service is needed for ingestion.

PDF conversion uses Docling's accurate TableFormer configuration. HybridChunker
uses the BGE tokenizer with a 450-token target and peer merging; Markdown table
serialization preserves row/column labels. Every final enriched string, including
protocol prefix and special tokens, is independently checked against 512 tokens.
Oversized metadata fails ingestion instead of silently truncating a dosage or
breadcrumb. Large tables may be split by Docling; clinical reviewers must verify
source interpretation, especially diagram-heavy/scanned protocols.

Points are UUID5 derived from protocol/enriched content; hospital indexing adds a
workspace/document namespace. Successful upserts precede a single SQL transaction
that publishes the document's chunks as ready. Failed/partial upserts remain
unreferenced and cannot enter the agent's approved snapshot. Old content revisions
are retained for immutable published references; this intentionally differs from
blindly deleting every old point on re-ingestion.

Approval remains mandatory. Runtime retrieval filters both prefetch stages and
fusion by workspace and the exact point IDs in the approved agent snapshot, not
just a potentially duplicated protocol name. Expired snapshot evidence is removed.
An unavailable Qdrant falls back only to lexical retrieval of the same approved
snapshot, and emits a content-free warning. Legacy snapshots remain usable and
can be migrated through indexing, approval, and agent republication.

The standalone `ClinicalKnowledgeBase` API can search an entire collection by
default; application integrations must always use a workspace scope and an approved
ID allowlist. `RetrievedChunk.formatted_text` includes section/page citations;
`raw_text` stays separate for prompts. Markdown has no reliable PDF page numbers.
The latency logger records only elapsed time and result count, never the query.

## Network and storage

The requested development Compose service publishes 6333/6334; restrict these
ports to trusted development networks. Production platform Compose keeps Qdrant
on its private Docker network. Configure `QDRANT_API_KEY` for secured external
Qdrant deployments and secure/backup both Qdrant storage and PostgreSQL/source
volumes. The verification image builds tooling only; do not expose it as an API.

## Implementation references

- [Docling chunking and Markdown table serialization](https://docling-project.github.io/docling/_generated/examples/advanced_chunking_and_serialization/)
- [Qdrant hybrid prefetch and fusion](https://qdrant.tech/documentation/search/hybrid-queries/)
- [FastEmbed BM25 query embedding and server IDF](https://github.com/qdrant/fastembed/blob/main/fastembed/sparse/bm25.py)

Observed acceptance result on the local Docker/ARM CPU environment during this
implementation: 3 protocol chunks, max 231 tokens, warm median 6.52ms and p95 6.92ms
(20 requests). The extended check also validates a 100-row Markdown table and
workspace/protocol isolation. These are local fixture measurements, not a clinical
workload service-level guarantee.
