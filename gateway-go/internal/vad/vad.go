package vad

import (
	"sync"
	"time"

	"github.com/ajay7231/pulsemux/gateway-go/internal/audio"
)

// State defines the speech state machine states.
type State string

const (
	StateSilence       State = "SILENCE"
	StateUserSpeaking  State = "USER_SPEAKING"
	StateUserPaused    State = "USER_PAUSED"
	StateAgentSpeaking State = "AGENT_SPEAKING"
)

// VADEvent represents an edge trigger emitted by the speech state machine.
type VADEvent struct {
	Type       EventType
	Confidence float32
	Timestamp  time.Time
}

type EventType int

const (
	EventSpeechStart EventType = iota
	EventSpeechEnd
	EventBackchannelPause // Temporary pause before destructive interrupt
)

// Detector defines the interface for acoustic voice activity detection.
type Detector interface {
	// ProcessChunk processes a 20ms 16kHz PCM chunk and returns speech probability [0.0, 1.0].
	ProcessChunk(pcm []byte) (float32, error)
	Reset()
}

// Config configures the VAD state machine parameters.
type Config struct {
	SpeechThreshold      float32       // Probability threshold to trigger speech (default 0.5)
	SilenceThreshold     float32       // Probability below which is considered silence (default 0.35)
	DebounceDuration     time.Duration // Duration speech must persist before firing destructive barge-in (e.g. 150-180ms)
	SpeechEndSilenceWait time.Duration // Continuous silence duration before emitting SPEECH_END (e.g. 250ms)
}

func DefaultConfig() Config {
	return Config{
		SpeechThreshold:      0.5,
		SilenceThreshold:     0.35,
		DebounceDuration:     160 * time.Millisecond,
		SpeechEndSilenceWait: 250 * time.Millisecond,
	}
}

// StateMachine manages the per-call voice state machine and two-stage barge-in debounce.
type StateMachine struct {
	mu           sync.Mutex
	cfg          Config
	detector     Detector
	currentState State

	speechStartTime    time.Time
	silenceStartTime   time.Time
	isDebouncedSpeech  bool
	agentSpeakingActive bool
}

// NewStateMachine creates a new speech state machine with the provided detector.
func NewStateMachine(detector Detector, cfg Config) *StateMachine {
	return &StateMachine{
		cfg:          cfg,
		detector:     detector,
		currentState: StateSilence,
	}
}

// SetAgentSpeaking informs the state machine whether the agent is currently playing TTS audio.
func (sm *StateMachine) SetAgentSpeaking(speaking bool) {
	sm.mu.Lock()
	defer sm.mu.Unlock()
	sm.agentSpeakingActive = speaking
	if speaking && sm.currentState == StateSilence {
		sm.currentState = StateAgentSpeaking
	} else if !speaking && sm.currentState == StateAgentSpeaking {
		sm.currentState = StateSilence
	}
}

// ProcessFrame processes a 20ms frame of 16kHz PCM audio.
// Returns optional VADEvent (e.g., SpeechStart, SpeechEnd) and current state.
func (sm *StateMachine) ProcessFrame(pcm []byte) (*VADEvent, State) {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	prob, err := sm.detector.ProcessChunk(pcm)
	if err != nil {
		prob = 0.0
	}

	now := time.Now()
	var emittedEvent *VADEvent

	isSpeech := prob >= sm.cfg.SpeechThreshold
	isSilence := prob < sm.cfg.SilenceThreshold

	if isSpeech {
		sm.silenceStartTime = time.Time{}

		if sm.speechStartTime.IsZero() {
			sm.speechStartTime = now
		}

		durationSpeaking := now.Sub(sm.speechStartTime)

		// Two-stage interrupt logic:
		// Stage 1: Initial speech trigger (0ms - DebounceDuration)
		// If Agent is speaking, emit BackchannelPause so gateway pauses outbound audio.
		if sm.agentSpeakingActive && !sm.isDebouncedSpeech && durationSpeaking < sm.cfg.DebounceDuration {
			emittedEvent = &VADEvent{
				Type:       EventBackchannelPause,
				Confidence: prob,
				Timestamp:  now,
			}
		}

		// Stage 2: Speech sustained beyond debounce threshold (e.g., 160ms) -> Confirmed SpeechStart
		if durationSpeaking >= sm.cfg.DebounceDuration && !sm.isDebouncedSpeech {
			sm.isDebouncedSpeech = true
			sm.currentState = StateUserSpeaking
			emittedEvent = &VADEvent{
				Type:       EventSpeechStart,
				Confidence: prob,
				Timestamp:  now,
			}
		}
	} else if isSilence {
		sm.speechStartTime = time.Time{}

		if sm.isDebouncedSpeech {
			if sm.silenceStartTime.IsZero() {
				sm.silenceStartTime = now
				sm.currentState = StateUserPaused
			} else if now.Sub(sm.silenceStartTime) >= sm.cfg.SpeechEndSilenceWait {
				// User finished speaking
				sm.isDebouncedSpeech = false
				sm.silenceStartTime = time.Time{}
				sm.currentState = StateSilence
				emittedEvent = &VADEvent{
					Type:       EventSpeechEnd,
					Confidence: 1.0 - prob,
					Timestamp:  now,
				}
			}
		}
	}

	return emittedEvent, sm.currentState
}

// Reset clears state machine memory.
func (sm *StateMachine) Reset() {
	sm.mu.Lock()
	defer sm.mu.Unlock()
	sm.currentState = StateSilence
	sm.speechStartTime = time.Time{}
	sm.silenceStartTime = time.Time{}
	sm.isDebouncedSpeech = false
	sm.detector.Reset()
}

// EnergyVADDetector provides a robust fallback detector using root-mean-square energy
// and adaptive noise floor estimation when Silero ONNX runtime is uninitialized.
type EnergyVADDetector struct {
	noiseFloorRMS float64
	initialized   bool
}

func NewEnergyVADDetector() *EnergyVADDetector {
	return &EnergyVADDetector{
		noiseFloorRMS: 200.0, // baseline ambient noise floor for 16-bit PCM
	}
}

func (e *EnergyVADDetector) ProcessChunk(pcm []byte) (float32, error) {
	rms := audio.CalculateRMS(pcm)

	if !e.initialized {
		e.noiseFloorRMS = rms
		e.initialized = true
	} else {
		// Slowly adapt background noise floor
		if rms < e.noiseFloorRMS*1.5 {
			e.noiseFloorRMS = e.noiseFloorRMS*0.95 + rms*0.05
		}
	}

	// Ratio against background noise
	snr := rms / (e.noiseFloorRMS + 1.0)
	if snr > 3.0 && rms > 300.0 {
		return 0.85, nil
	} else if snr > 2.0 && rms > 200.0 {
		return 0.55, nil
	}
	return 0.1, nil
}

func (e *EnergyVADDetector) Reset() {
	e.initialized = false
}
