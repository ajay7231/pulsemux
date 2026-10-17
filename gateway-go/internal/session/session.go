package session

import (
	"context"
	"fmt"
	"sync"
	"sync/atomic"
	"time"

	"github.com/ajay7231/pulsemux/gateway-go/internal/audio"
	"github.com/ajay7231/pulsemux/gateway-go/internal/vad"
)

// IngressSink represents an active caller channel capable of receiving outbound audio
// and control signals (e.g. Twilio media stream or WebRTC track).
type IngressSink interface {
	SendAudioFrame(pcm []byte) error
	SendClearBufferSignal() error
	Close() error
}

// WorkerStream defines the communication interface to the Python intelligence worker.
type WorkerStream interface {
	SendAudio(callID string, pcm []byte, seq uint32) error
	SendVADEvent(callID string, isStart bool, confidence float32) error
	SendInterrupt(callID string, interruptedTurnID string, playedDurationMs uint32) error
	SendPlaybackAck(callID string, turnID string, totalPlayedMs uint32) error
}

// CallSession manages the real-time Goroutine lifecycle and sub-50ms barge-in
// interrupt engine for a single active patient call.
type CallSession struct {
	CallID    string
	PatientID string
	ctx       context.Context
	cancel    context.CancelFunc

	sink         IngressSink
	workerStream WorkerStream
	ringBuffer   *audio.RingBuffer
	vadMachine   *vad.StateMachine

	mu                  sync.RWMutex
	currentTurnID       string
	interruptedTurnIDs  map[string]bool
	sequenceNum         atomic.Uint32
	isAgentSpeaking     atomic.Bool
	playbackPaused      atomic.Bool
	totalAudioPlayedMs  atomic.Uint64
}

// NewCallSession initializes a new per-call lifecycle controller.
func NewCallSession(
	parentCtx context.Context,
	callID, patientID string,
	sink IngressSink,
	workerStream WorkerStream,
) *CallSession {
	ctx, cancel := context.WithCancel(parentCtx)

	vDetector := vad.NewEnergyVADDetector()
	vMachine := vad.NewStateMachine(vDetector, vad.DefaultConfig())

	return &CallSession{
		CallID:             callID,
		PatientID:          patientID,
		ctx:                ctx,
		cancel:             cancel,
		sink:               sink,
		workerStream:       workerStream,
		ringBuffer:         audio.NewRingBuffer(500), // 10 seconds of 20ms buffer
		vadMachine:         vMachine,
		interruptedTurnIDs: make(map[string]bool),
	}
}

// Start begins the parallel ingestion, VAD, and paced 20ms playback loops.
func (cs *CallSession) Start() {
	go cs.playbackLoop()
}

// Close terminates the session, canceling all Goroutines and closing the sink.
func (cs *CallSession) Close() {
	cs.cancel()
	if cs.sink != nil {
		_ = cs.sink.Close()
	}
}

// HandleIncomingPCMFrame processes a 20ms 16kHz PCM frame from the telephony/WebRTC ingress.
func (cs *CallSession) HandleIncomingPCMFrame(pcm []byte) error {
	select {
	case <-cs.ctx.Done():
		return cs.ctx.Err()
	default:
	}

	seq := cs.sequenceNum.Add(1)

	// 1. Process VAD and evaluate speech state machine
	event, state := cs.vadMachine.ProcessFrame(pcm)

	if event != nil {
		switch event.Type {
		case vad.EventBackchannelPause:
			// Stage 1: Temporary backchannel pause (150ms window)
			cs.playbackPaused.Store(true)

		case vad.EventSpeechStart:
			// Stage 2: Confirmed speech -> Hardware-speed barge-in interruption!
			cs.playbackPaused.Store(false)
			if cs.isAgentSpeaking.Load() {
				cs.TriggerBargeIn(event.Confidence)
			}
			if cs.workerStream != nil {
				_ = cs.workerStream.SendVADEvent(cs.CallID, true, event.Confidence)
			}

		case vad.EventSpeechEnd:
			cs.playbackPaused.Store(false)
			if cs.workerStream != nil {
				_ = cs.workerStream.SendVADEvent(cs.CallID, false, event.Confidence)
			}
		}
	}

	if state == vad.StateSilence {
		cs.playbackPaused.Store(false)
	}

	// 2. Stream audio upstream to Python worker
	if cs.workerStream != nil {
		return cs.workerStream.SendAudio(cs.CallID, pcm, seq)
	}
	return nil
}

// EnqueueTTSAudio appends synthesized TTS audio from Python worker into the outbound ring buffer.
func (cs *CallSession) EnqueueTTSAudio(pcm []byte, turnID string) {
	cs.mu.RLock()
	isInterrupted := cs.interruptedTurnIDs[turnID]
	cs.mu.RUnlock()

	// Edge Case 3: Silently drop audio packets belonging to already interrupted turns
	if isInterrupted {
		return
	}

	cs.mu.Lock()
	if cs.currentTurnID != turnID {
		cs.currentTurnID = turnID
		cs.isAgentSpeaking.Store(true)
		cs.vadMachine.SetAgentSpeaking(true)
	}
	cs.mu.Unlock()

	cs.ringBuffer.Push(pcm, turnID)
}

// TriggerBargeIn executes sub-50ms deterministic barge-in cancellation.
func (cs *CallSession) TriggerBargeIn(confidence float32) {
	cs.mu.Lock()
	interruptedTurn := cs.currentTurnID
	if interruptedTurn != "" {
		cs.interruptedTurnIDs[interruptedTurn] = true
	}
	cs.isAgentSpeaking.Store(false)
	cs.vadMachine.SetAgentSpeaking(false)
	cs.mu.Unlock()

	// 1. Immediately purge unplayed audio in ring buffer (<1ms)
	discardedMs := cs.ringBuffer.Purge()
	playedMs := cs.ringBuffer.PlayedMs()

	// 2. Send CLEAR_BUFFER frame to telephony / WebRTC client
	if cs.sink != nil {
		_ = cs.sink.SendClearBufferSignal()
	}

	// 3. Emit high-priority InterruptSignal to Python worker with exact ms heard
	if cs.workerStream != nil && interruptedTurn != "" {
		_ = cs.workerStream.SendInterrupt(cs.CallID, interruptedTurn, playedMs)
	}

	fmt.Printf("[BargeIn] Call %s interrupted turn %s. Played %dms, purged %dms\n",
		cs.CallID, interruptedTurn, playedMs, discardedMs)
}

// playbackLoop paces outbound audio to the caller at exact 20ms intervals.
func (cs *CallSession) playbackLoop() {
	ticker := time.NewTicker(20 * time.Millisecond)
	defer ticker.Stop()

	for {
		select {
		case <-cs.ctx.Done():
			return

		case <-ticker.C:
			// Pause audio during tentative backchannel debounce window
			if cs.playbackPaused.Load() {
				continue
			}

			pcm, turnID, ok := cs.ringBuffer.Pop()
			if !ok {
				// Buffer empty -> agent finished speaking
				if cs.isAgentSpeaking.Load() {
					cs.isAgentSpeaking.Store(false)
					cs.vadMachine.SetAgentSpeaking(false)

					cs.mu.RLock()
					activeTurn := cs.currentTurnID
					cs.mu.RUnlock()

					if activeTurn != "" && cs.workerStream != nil {
						_ = cs.workerStream.SendPlaybackAck(cs.CallID, activeTurn, cs.ringBuffer.PlayedMs())
					}
				}
				continue
			}

			// Validate chunk does not belong to an interrupted turn
			cs.mu.RLock()
			isInterrupted := cs.interruptedTurnIDs[turnID]
			cs.mu.RUnlock()

			if isInterrupted {
				continue
			}

			// Send audio frame to caller
			if cs.sink != nil {
				_ = cs.sink.SendAudioFrame(pcm)
				cs.totalAudioPlayedMs.Add(20)
			}
		}
	}
}
