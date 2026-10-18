import asyncio
import logging
import os
import sys
import time
import uuid
from typing import AsyncGenerator, Dict, Optional

from dotenv import load_dotenv
load_dotenv()

# Try enabling uvloop if available
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

import grpc
from concurrent import futures

from app.agent.graph import ClinicalState, ClinicalTriageGraph
from app.pipeline.canceller import CancellationEngine
from app.pipeline.stt_stream import STTStreamClient
from app.pipeline.turn_detector import TurnDetector
from app.pipeline.tts_stream import ClauseSplitter, TTSStreamClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pulse-worker")


class CallPipelineContext:
    """Encapsulates all streaming components and state for a single active call."""

    def __init__(self, call_id: str, patient_id: str, triage_graph: ClinicalTriageGraph):
        self.call_id = call_id
        self.patient_id = patient_id
        self.triage_graph = triage_graph

        self.stt = STTStreamClient(groq_api_key=os.getenv("GROQ_API_KEY"))
        self.turn_detector = TurnDetector()
        self.tts = TTSStreamClient()
        self.canceller = CancellationEngine()
        self.clause_splitter = ClauseSplitter()

        self.outbound_queue: asyncio.Queue[Dict] = asyncio.Queue()
        self.clinical_state: ClinicalState = {
            "call_id": call_id,
            "patient_id": patient_id,
            "messages": [],
            "current_node": "INIT",
            "symptoms": "",
            "is_emergency": False,
            "recommended_slot": None,
            "confirmation_code": None,
        }

        self.active_turn_id: Optional[str] = None
        self.is_processing_turn = False


class PulseVoiceService:
    """Core Voice Orchestrator business logic."""

    def __init__(self):
        self.triage_graph = ClinicalTriageGraph(
            redis_url=os.getenv("REDIS_URL"),
            groq_api_key=os.getenv("GROQ_API_KEY"),
        )
        self.active_calls: Dict[str, CallPipelineContext] = {}

    def get_or_create_context(self, call_id: str, patient_id: str = "anon") -> CallPipelineContext:
        if call_id not in self.active_calls:
            ctx = CallPipelineContext(call_id, patient_id, self.triage_graph)
            self.active_calls[call_id] = ctx

            # Wire up STT transcript listener
            def on_transcript(text: str, is_final: bool):
                ctx.turn_detector.update_transcript(text)
                asyncio.create_task(
                    ctx.outbound_queue.put({
                        "type": "transcript",
                        "text": text,
                        "is_final": is_final,
                        "speaker": "PATIENT",
                    })
                )
                if is_final or ctx.turn_detector.is_turn_complete():
                    asyncio.create_task(self.trigger_agent_turn(ctx, text))

            asyncio.create_task(ctx.stt.start_streaming(on_transcript))
        return self.active_calls[call_id]

    async def handle_audio_frame(self, call_id: str, pcm: bytes, seq: int) -> None:
        ctx = self.active_calls.get(call_id)
        if ctx:
            await ctx.stt.push_audio(pcm)

    async def handle_vad_event(self, call_id: str, is_start: bool, conf: float) -> None:
        ctx = self.active_calls.get(call_id)
        if not ctx:
            return

        now_ms = time.time() * 1000
        if is_start:
            ctx.turn_detector.on_vad_speech_start()
        else:
            ctx.turn_detector.on_vad_speech_end(now_ms)
            if ctx.turn_detector.is_turn_complete(now_ms):
                pass # Turn trigger handled on silence threshold check

    async def handle_interrupt(self, call_id: str, turn_id: str, played_ms: int) -> None:
        ctx = self.active_calls.get(call_id)
        if not ctx:
            return

        reconciled_text = await ctx.canceller.handle_interrupt(call_id, turn_id, played_ms)
        if reconciled_text and ctx.clinical_state["messages"]:
            # Reconcile last assistant message in conversation memory
            ctx.clinical_state["messages"][-1]["content"] = reconciled_text

    async def trigger_agent_turn(self, ctx: CallPipelineContext, user_utterance: str) -> None:
        """Executes the LangGraph clinical triage node, splits clauses, and streams TTS audio."""
        if ctx.is_processing_turn:
            return
        ctx.is_processing_turn = True

        turn_id = f"turn-{uuid.uuid4().hex[:8]}"
        ctx.active_turn_id = turn_id
        ctx.turn_detector.reset()

        logger.info("voice_turn_started turn_id=%s", turn_id)
        start_time = time.time()

        # Update patient conversation state
        ctx.clinical_state["messages"].append({"role": "user", "content": user_utterance})

        # 1. Execute LangGraph step
        turn_task = asyncio.current_task()
        ctx.canceller.register_task(turn_id, turn_task)

        new_state = await ctx.triage_graph.step(ctx.clinical_state)
        ctx.clinical_state = new_state

        assistant_msg = new_state["messages"][-1]["content"]
        ctx.canceller.record_turn_text(turn_id, assistant_msg)

        # Telemetry: TTFT
        ttft_ms = int((time.time() - start_time) * 1000)
        await ctx.outbound_queue.put({
            "type": "state_update",
            "current_node": new_state.get("current_node", "UNKNOWN"),
            "ttft_ms": ttft_ms,
        })

        # 2. Stream tokens -> Clause-level TTS synthesis
        clause_splitter = ClauseSplitter(min_word_count=5)
        async for token in ctx.triage_graph.stream_tokens(assistant_msg):
            clauses = clause_splitter.feed_token(token)
            for clause in clauses:
                async for pcm_frame in ctx.tts.synthesize_clause_stream(clause, turn_id):
                    await ctx.outbound_queue.put({
                        "type": "tts_audio",
                        "pcm": pcm_frame,
                        "turn_id": turn_id,
                    })

        # Flush any trailing words
        trailing = clause_splitter.flush()
        if trailing:
            async for pcm_frame in ctx.tts.synthesize_clause_stream(trailing, turn_id):
                await ctx.outbound_queue.put({
                    "type": "tts_audio",
                    "pcm": pcm_frame,
                    "turn_id": turn_id,
                })

        ctx.is_processing_turn = False
        logger.info(f"[Turn] Completed Turn {turn_id} synthesis (TTFT={ttft_ms}ms)")


async def run_server():
    port = os.getenv("PORT", "50051")
    service = PulseVoiceService()

    logger.info("==================================================")
    logger.info(" PulseMux Python AI Worker (pulse-brain)")
    logger.info(f" gRPC Server running on port :{port}")
    logger.info(" Speculative Turn Detector + LangGraph Active")
    logger.info("==================================================")

    # In production with compiled proto:
    # server = grpc.aio.server()
    # voice_stream_pb2_grpc.add_VoiceOrchestratorServicer_to_server(service, server)
    # server.add_insecure_port(f"[::]:{port}")
    # await server.start()
    # await server.wait_for_termination()

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        logger.info("Worker stopped cleanly.")
