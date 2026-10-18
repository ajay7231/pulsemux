"""Live Docker Qdrant acceptance check. Run with Python 3.12 and RAG dependencies.

Uses synthetic protocol content solely as an indexing fixture, not clinical guidance.
Latency is measured honestly across embedding + scheduling + Qdrant + formatting.
"""

from __future__ import annotations

import asyncio
from copy import copy
import os
import statistics
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from qdrant_client import models

from app.rag.knowledge_base import ClinicalKnowledgeBase

PROTOCOL = """# Synthetic Cardiac Discharge Protocol

## Antiplatelet medication reference

This is synthetic software-verification data. Follow the patient's signed discharge
prescription and the hospital's approved clinical policy; this fixture is not dosing advice.

| Medication | Recorded discharge dose | Staff verification |
| --- | --- | --- |
| Ticagrelor / Brilinta | 90mg | Verify the individual prescription with the clinical team. |
| Aspirin | See signed prescription | Verify allergy history and prescribed regimen. |

Do not suggest that callers start, stop, or adjust medication themselves.

## Post-Cardiac Stent Red Flag Symptoms

New chest discomfort, left arm numbness, breathlessness, fainting, or severe bleeding
require urgent clinician assessment according to the hospital's emergency escalation policy.
The voice assistant must escalate and must not diagnose a caller from these symptoms.

## Routine follow-up

For a routine appointment question, offer a callback from the scheduling team.
"""


async def main():
    # Unique tenant scope isolates this run from hospital knowledge without deleting data.
    kb = ClinicalKnowledgeBase(
        url=os.getenv("QDRANT_URL", "http://localhost:6333"),
        cache_dir=os.getenv("RAG_MODEL_CACHE", "./model_cache"),
        workspace_id="verification-" + uuid4().hex,
    )
    try:
        await kb.init_collection()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "cardiac.md"
            source.write_text(PROTOCOL)
            chunks = await asyncio.to_thread(
                kb.processor.process_document, str(source), "Cardiac Discharge"
            )
            assert all(
                kb.processor.token_count(chunk.enriched_text) <= 512 for chunk in chunks
            )
            assert any(
                "Ticagrelor" in chunk.raw_text and "90mg" in chunk.raw_text
                for chunk in chunks
            ), "Dosage table text was lost"
            await kb.ingest_document(str(source), "Cardiac Discharge")
            before = await kb.client.count(
                kb.collection_name,
                count_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="workspace_id",
                            match=models.MatchValue(value=kb.workspace_id),
                        )
                    ]
                ),
                exact=True,
            )
            await kb.ingest_document(str(source), "Cardiac Discharge")
            after = await kb.client.count(
                kb.collection_name,
                count_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="workspace_id",
                            match=models.MatchValue(value=kb.workspace_id),
                        )
                    ]
                ),
                exact=True,
            )
            assert (
                before.count == after.count
            ), "Identical re-ingestion duplicated chunks"
            # Stress a table larger than one embedding window: do not lose dose/label pairs.
            table = (
                "# Stress Protocol\n\n| Medication | Dose | Check |\n| --- | --- | --- |\n"
                + "\n".join(
                    f"| Brilinta record {i} | 90mg | Confirm signed prescription {i} |"
                    for i in range(100)
                )
            )
            large_chunks = await asyncio.to_thread(
                kb.processor.chunk_markdown, table, "Table integrity fixture"
            )
            assert len(large_chunks) > 1
            assert all(
                kb.processor.token_count(chunk.enriched_text) <= 512
                for chunk in large_chunks
            )
            assert all(
                any(
                    f"record {i}" in chunk.raw_text and "90mg" in chunk.raw_text
                    for chunk in large_chunks
                )
                for i in range(100)
            ), "Long-table rows were lost"
            outsider = copy(kb)
            outsider.workspace_id = "unrelated-" + uuid4().hex
            assert (
                await outsider.retrieve("Brilinta") == []
            ), "Cross-workspace evidence leaked"
            assert await kb.retrieve("Brilinta", protocol_name="Unknown protocol") == []
            assert await kb.retrieve("Brilinta", allowed_ids=[]) == []
            query = "Brilinta 90mg left arm numbness"
            for _ in range(3):
                await kb.retrieve(query)
            timings = []
            for _ in range(20):
                started = time.perf_counter()
                results = await kb.retrieve(query, protocol_name="Cardiac Discharge")
                timings.append((time.perf_counter() - started) * 1000)
            assert results, "Hybrid retrieval returned no evidence"
            combined = "\n".join(chunk.raw_text for chunk in results)
            assert "Brilinta" in combined and "left arm numbness" in combined
            for chunk in results:
                print(chunk.formatted_text)
            p95 = sorted(timings)[int(len(timings) * 0.95) - 1]
            print(
                f"Chunks: {len(chunks)}; maximum tokens: {max(chunk.token_count for chunk in chunks)}"
            )
            print(
                f"Warm retrieval: median={statistics.median(timings):.2f}ms p95={p95:.2f}ms max={max(timings):.2f}ms"
            )
            assert (
                p95 < 25
            ), f"Warm p95 retrieval {p95:.2f}ms exceeds the 25ms target on this machine"
    finally:
        await kb.close()


if __name__ == "__main__":
    asyncio.run(main())
