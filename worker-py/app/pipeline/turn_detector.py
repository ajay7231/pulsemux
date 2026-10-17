import time
from typing import Optional


class TurnDetector:
    """
    Semantic End-of-Turn Classifier combining acoustic VAD boundaries from Go
    with syntactic and lexical cues from interim transcripts.
    """

    INCOMPLETE_CONNECTORS = {
        "and", "or", "but", "because", "so", "if", "when", "although", "while",
        "that", "which", "who", "whom", "whose", "my", "our", "the", "a", "an",
        "is", "was", "are", "were", "to", "at", "in", "for", "with", "about"
    }

    FILLER_WORDS = {"um", "uh", "er", "ah", "like", "hmm"}

    def __init__(
        self,
        complete_silence_threshold_ms: int = 250,
        incomplete_silence_threshold_ms: int = 1200,
    ):
        self.complete_silence_ms = complete_silence_threshold_ms
        self.incomplete_silence_ms = incomplete_silence_threshold_ms

        self._last_speech_end_ms: Optional[float] = None
        self._current_transcript: str = ""

    def on_vad_speech_end(self, timestamp_ms: float) -> None:
        """Invoked when Go emits VAD_SPEECH_END event."""
        self._last_speech_end_ms = timestamp_ms

    def on_vad_speech_start(self) -> None:
        """Invoked when Go emits VAD_SPEECH_START event (caller resumed speaking)."""
        self._last_speech_end_ms = None

    def update_transcript(self, text: str) -> None:
        """Updates the latest interim transcript received from STT."""
        self._current_transcript = text.strip()

    def is_turn_complete(self, now_ms: Optional[float] = None) -> bool:
        """
        Determines whether the patient has finished speaking their semantic turn.
        Returns True when elapsed silence exceeds the semantic pause threshold.
        """
        if self._last_speech_end_ms is None or not self._current_transcript:
            return False

        if now_ms is None:
            now_ms = time.time() * 1000

        silence_duration_ms = now_ms - self._last_speech_end_ms
        is_complete_thought = self._classify_semantic_completeness(self._current_transcript)

        required_silence = (
            self.complete_silence_ms
            if is_complete_thought
            else self.incomplete_silence_ms
        )

        return silence_duration_ms >= required_silence

    def _classify_semantic_completeness(self, transcript: str) -> bool:
        """
        Analyzes grammar, trailing words, and punctuation to classify whether
        the transcript represents a syntactically self-contained utterance.
        """
        if not transcript:
            return False

        # Punctuation terminal
        if transcript.endswith((".", "?", "!")):
            return True

        tokens = transcript.lower().split()
        if not tokens:
            return False

        last_word = tokens[-1].rstrip(".,?!")

        # Incomplete connectors or dangling prepositions/articles
        if last_word in self.INCOMPLETE_CONNECTORS or last_word in self.FILLER_WORDS:
            return False

        # Utterances under 3 words without terminal punctuation are given extra pause allowance
        if len(tokens) < 3:
            return False

        return True

    def reset(self) -> None:
        self._last_speech_end_ms = None
        self._current_transcript = ""
