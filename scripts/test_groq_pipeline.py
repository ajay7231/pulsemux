#!/usr/bin/env python3
"""
PulseMux - Real-World Clinical Voice AI Benchmark & Test Suite
Evaluates complete bi-directional Voice AI stack:
  1. STT: Deepgram Nova-3 (WebSocket/REST) & Groq Whisper Turbo
  2. LLM: Groq LPU (qwen/qwen3.8-27b) Clinical Triage with Sub-200ms TTFT
  3. TTS: Local Kokoro-82M ONNX (Apache-2.0, 82M open-weights) 16kHz PCM streaming
"""

import argparse
import asyncio
import io
import json
import os
import subprocess
import sys
import time
import wave
from pathlib import Path
from typing import List, Optional

# Ensure execution inside worker-py virtual environment
PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = PROJECT_ROOT / "worker-py" / ".venv" / "bin" / "python"
if VENV_PYTHON.exists() and sys.executable != str(VENV_PYTHON):
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON)] + sys.argv)

sys.path.insert(0, str(PROJECT_ROOT / "worker-py"))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

import httpx

# ANSI Color Codes
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
MAGENTA = "\033[95m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def print_banner():
    print(f"\n{CYAN}{BOLD}========================================================================{RESET}")
    print(f"{CYAN}{BOLD}   PulseMux Ultra-Low Latency Voice AI — Full Stack Benchmark           {RESET}")
    print(f"{CYAN}{BOLD}   STT: Deepgram Nova-3 | LLM: Groq LPU | TTS: Kokoro-82M Local ONNX    {RESET}")
    print(f"{CYAN}{BOLD}========================================================================{RESET}\n")


def get_keys():
    groq_key = os.getenv("GROQ_API_KEY")
    deepgram_key = os.getenv("DEEPGRAM_API_KEY")
    return groq_key, deepgram_key


def generate_test_audio(text: str, wav_path: Path):
    """Generates synthetic spoken audio for STT testing."""
    try:
        aiff_path = wav_path.with_suffix(".aiff")
        subprocess.run(["say", "-o", str(aiff_path), text], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(
            ["afconvert", str(aiff_path), str(wav_path), "-d", "LEI16@16000", "-c", "1", "-f", "WAVE"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        if aiff_path.exists():
            aiff_path.unlink()
        return True
    except Exception:
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b"\x00" * 32000)
        return False


def test_deepgram_stt(deepgram_key: Optional[str], audio_path: Path):
    """Tests Deepgram Nova-3 Speech-to-Text."""
    print(f"{BOLD}[1/4] Testing STT: Deepgram Nova-3 API...{RESET}")
    if not deepgram_key:
        print(f"  {YELLOW}⚠ DEEPGRAM_API_KEY not set in .env. Skipping Deepgram test.{RESET}\n")
        return None

    headers = {"Authorization": f"Token {deepgram_key}", "Content-Type": "audio/wav"}
    try:
        t0 = time.time()
        with open(audio_path, "rb") as f:
            r = httpx.post(
                "https://api.deepgram.com/v1/listen?model=nova-3&smart_format=true",
                headers=headers,
                content=f.read(),
                timeout=10.0,
            )
        dt = (time.time() - t0) * 1000
        if r.status_code == 200:
            res = r.json()
            transcript = res["results"]["channels"][0]["alternatives"][0]["transcript"]
            print(f"  {GREEN}✓ Deepgram Nova-3 transcribed in {dt:.1f}ms{RESET}")
            print(f"  {CYAN}Recognized Text:{RESET} \"{transcript}\"\n")
            return transcript
        else:
            print(f"  {RED}✗ Deepgram API returned {r.status_code}: {r.text}{RESET}\n")
            return None
    except Exception as e:
        print(f"  {RED}✗ Deepgram request failed: {e}{RESET}\n")
        return None


def test_groq_whisper(groq_key: Optional[str], audio_path: Path):
    """Tests Groq Whisper-Large-v3-Turbo Speech-to-Text."""
    print(f"{BOLD}[2/4] Testing STT: Groq Whisper-Large-v3-Turbo...{RESET}")
    if not groq_key:
        print(f"  {YELLOW}⚠ GROQ_API_KEY not set in .env. Skipping Groq Whisper test.{RESET}\n")
        return None

    headers = {"Authorization": f"Bearer {groq_key}"}
    try:
        t0 = time.time()
        with open(audio_path, "rb") as f:
            files = {"file": ("audio.wav", f, "audio/wav")}
            data = {"model": "whisper-large-v3-turbo"}
            r = httpx.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers=headers,
                files=files,
                data=data,
                timeout=10.0,
            )
        dt = (time.time() - t0) * 1000
        if r.status_code == 200:
            transcript = r.json().get("text", "").strip()
            print(f"  {GREEN}✓ Groq Whisper transcribed in {dt:.1f}ms{RESET}")
            print(f"  {CYAN}Recognized Text:{RESET} \"{transcript}\"\n")
            return transcript
        else:
            print(f"  {RED}✗ Groq Whisper error {r.status_code}: {r.text}{RESET}\n")
            return None
    except Exception as e:
        print(f"  {RED}✗ Groq Whisper failed: {e}{RESET}\n")
        return None


def test_kokoro_tts(test_phrase: str = "Please remain calm while I immediately connect you to emergency medical services."):
    """Tests local Kokoro-82M ONNX Speech Synthesis."""
    print(f"{BOLD}[3/4] Testing Local TTS: Kokoro-82M ONNX Model...{RESET}")
    from app.pipeline.tts_stream import KokoroEngine

    t0 = time.time()
    kokoro = KokoroEngine.get_instance()
    load_time = (time.time() - t0) * 1000

    if not kokoro:
        print(f"  {RED}✗ Kokoro model could not be loaded from worker-py/models/{RESET}\n")
        return

    print(f"  {DIM}Loaded Kokoro-82M ONNX in {load_time:.1f}ms{RESET}")

    t1 = time.time()
    samples, sample_rate = kokoro.create(test_phrase, voice="af_bella", speed=1.0, lang="en-us")
    synth_time = (time.time() - t1) * 1000

    audio_duration = len(samples) / sample_rate
    rtf = (synth_time / 1000) / audio_duration

    print(f"  {GREEN}✓ Synthesized {audio_duration:.2f}s of high-fidelity voice in {synth_time:.1f}ms!{RESET}")
    print(f"  {CYAN}Model Performance:{RESET} Real-Time Factor (RTF) = {BOLD}{rtf:.2f}x{RESET} ({1/rtf:.1f}x faster than real-time)")
    print(f"  {DIM}Audio Specs: {len(samples)} samples @ {sample_rate}Hz (downsampled to 16kHz PCM for telephony){RESET}\n")


async def stream_full_turn(groq_key: str, user_text: str, model: str = "qwen/qwen3.8-27b"):
    """
    Simulates a live Voice AI turn:
    1. Groq LLM streams clinical tokens with sub-200ms TTFT.
    2. ClauseSplitter extracts punctuated spoken clauses.
    3. Local Kokoro-82M ONNX synthesizes each clause into 20ms 16kHz PCM frames.
    """
    from app.pipeline.tts_stream import ClauseSplitter, TTSStreamClient

    tts = TTSStreamClient(voice_id="af_bella", use_kokoro=True)
    clause_splitter = ClauseSplitter(min_word_count=5)

    headers = {
        "Authorization": f"Bearer {groq_key}",
        "Content-Type": "application/json",
    }
    system_prompt = (
        "You are PulseMux Clinical Emergency and Triage AI. "
        "Your responses will be spoken aloud to the patient over an ultra-low latency voice link. "
        "INSTRUCTIONS: "
        "- For emergencies (chest pain, stroke symptoms, acute breathing trouble, severe trauma): "
        "  Issue immediate, authoritative life-saving guidance (call 911/112, sit upright, do not drive). "
        "- For non-emergency symptoms: "
        "  Provide calm clinical guidance in 1-2 spoken sentences and offer an appointment. "
        "- Strict Rule: Max 2 spoken sentences. No markdown bullets or formatting."
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        "stream": True,
        "max_tokens": 120,
        "temperature": 0.2,
    }

    t0 = time.time()
    first_token_time = None
    all_tokens = []
    clauses = []
    total_audio_frames = 0

    print(f"  {BOLD}Patient Utterance:{RESET} \"{user_text}\"")
    sys.stdout.write(f"  {MAGENTA}AI Triage Stream:{RESET} ")
    sys.stdout.flush()

    async with httpx.AsyncClient(timeout=10.0) as client:
        async with client.stream(
            "POST", "https://api.groq.com/openai/v1/chat/completions",
            headers=headers, json=payload
        ) as response:
            if response.status_code != 200:
                print(f"{RED}Error {response.status_code}{RESET}")
                return

            async for line in response.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk["choices"][0]["delta"].get("content", "")
                    if delta:
                        if first_token_time is None:
                            first_token_time = time.time()
                        all_tokens.append(delta)
                        sys.stdout.write(delta)
                        sys.stdout.flush()

                        for c in clause_splitter.feed_token(delta):
                            clauses.append(c)
                except Exception:
                    continue

    trailing = clause_splitter.flush()
    if trailing:
        clauses.append(trailing)

    llm_total_ms = (time.time() - t0) * 1000
    ttft_ms = (first_token_time - t0) * 1000 if first_token_time else 0
    print("\n")

    # Synthesize clauses with Kokoro-82M ONNX
    t_tts_start = time.time()
    packet_summaries = []
    for i, clause in enumerate(clauses, 1):
        t_c = time.time()
        c_frames = 0
        async for frame in tts.synthesize_clause_stream(clause, f"turn-{i}"):
            c_frames += 1
            total_audio_frames += 1
        dt_c = (time.time() - t_c) * 1000
        packet_summaries.append((clause, c_frames, dt_c))

    tts_total_ms = (time.time() - t_tts_start) * 1000
    total_audio_duration_s = (total_audio_frames * 640) / 32000

    print(f"  {CYAN}── Full Turn Pipeline Latency Metrics ──{RESET}")
    print(f"  • {BOLD}LLM Time To First Token (TTFT):{RESET} {GREEN}{ttft_ms:.1f} ms{RESET} (Target <200ms)")
    print(f"  • {BOLD}LLM Generation Completed:{RESET}      {llm_total_ms:.1f} ms")
    print(f"  • {BOLD}Kokoro-82M TTS Synthesis:{RESET}      {tts_total_ms:.1f} ms for {total_audio_duration_s:.2f}s audio ({total_audio_frames} 20ms frames)")
    for i, (c, frames, dt) in enumerate(packet_summaries, 1):
        print(f"     {DIM}[Clause {i}]: \"{c}\" -> {frames} frames in {dt:.1f}ms{RESET}")
    print()


async def run_scenarios(groq_key: str):
    """Runs standard clinical emergency triage test cases."""
    print(f"{BOLD}[4/4] Running Clinical Emergency Triage Scenarios...{RESET}\n")

    scenarios = [
        ("Acute Cardiac Distress", "I have severe squeezing chest pain spreading to my left shoulder and jaw, and I feel nauseous."),
        ("Stroke FAST Protocol", "My mother suddenly cannot speak clearly and her right arm went completely numb."),
        ("Routine Clinic Scheduling", "I'd like to schedule a general health checkup consultation with Dr. Jenkins next Monday."),
    ]

    for title, text in scenarios:
        print(f"{CYAN}{BOLD}▶ Scenario: {title}{RESET}")
        await stream_full_turn(groq_key, text)


async def interactive_mode(groq_key: str):
    """Interactive console session."""
    print(f"{BOLD}Interactive Clinical Voice Session Active{RESET}")
    print(f"{DIM}Enter any patient symptom or medical query (or 'exit' to quit):{RESET}\n")

    while True:
        try:
            user_input = input(f"{BOLD}{GREEN}Patient Query > {RESET}").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "q"):
                print(f"{CYAN}Exiting PulseMux test suite.{RESET}")
                break
            print()
            await stream_full_turn(groq_key, user_input)
        except (KeyboardInterrupt, EOFError):
            print("\nSession ended.")
            break


async def main():
    parser = argparse.ArgumentParser(description="PulseMux Full Stack Voice AI Benchmark")
    parser.add_argument("--interactive", "-i", action="store_true", help="Launch interactive session")
    args = parser.parse_args()

    print_banner()
    groq_key, deepgram_key = get_keys()

    # Prepare sample audio
    tmp_wav = Path("/tmp/pulsemux_patient_test.wav")
    generate_test_audio("Doctor, I have had acute chest tightness and shortness of breath for the last thirty minutes.", tmp_wav)

    # 1. Deepgram STT
    test_deepgram_stt(deepgram_key, tmp_wav)

    # 2. Groq Whisper STT
    test_groq_whisper(groq_key, tmp_wav)

    # 3. Local Kokoro-82M ONNX TTS
    test_kokoro_tts()

    # 4. Clinical Triage End-to-End Turn
    if groq_key:
        await run_scenarios(groq_key)

    # 5. Interactive Mode
    if args.interactive:
        if groq_key:
            await interactive_mode(groq_key)


if __name__ == "__main__":
    asyncio.run(main())
