package audio

import (
	"sync"
	"sync/atomic"
)

// FrameSize16kHz20ms defines the byte size of a 20ms frame at 16kHz 16-bit mono PCM.
// 16,000 samples/sec * 2 bytes/sample * 0.020 sec = 640 bytes.
const FrameSize16kHz20ms = 640

// AudioChunk holds a discrete frame of PCM audio along with its associated turn ID.
type AudioChunk struct {
	Data   []byte
	TurnID string
}

// RingBuffer provides a high-throughput, thread-safe circular buffer specifically
// optimized for pacing outbound TTS audio chunks to callers at 20ms intervals.
// It supports instantaneous purging (<1ms) for barge-in interruption and tracks
// exact playback duration in milliseconds.
type RingBuffer struct {
	mu           sync.RWMutex
	capacity     int
	chunks       []AudioChunk
	head         int // Write index
	tail         int // Read index
	count        int
	playedMs     atomic.Uint64
	activeTurnID string
}

// NewRingBuffer allocates an audio ring buffer with the specified capacity of 20ms frames.
// For example, capacity=500 holds up to 10 seconds of pre-buffered TTS audio.
func NewRingBuffer(capacity int) *RingBuffer {
	if capacity <= 0 {
		capacity = 250 // default 5 seconds of 20ms frames
	}
	return &RingBuffer{
		capacity: capacity,
		chunks:   make([]AudioChunk, capacity),
	}
}

// Push appends a 20ms PCM audio frame tagged with turnID.
// If the buffer is full, the oldest unread frame is overwritten to avoid blocking.
func (rb *RingBuffer) Push(data []byte, turnID string) bool {
	rb.mu.Lock()
	defer rb.mu.Unlock()

	// Defensive copy to prevent caller mutation
	buf := make([]byte, len(data))
	copy(buf, data)

	chunk := AudioChunk{
		Data:   buf,
		TurnID: turnID,
	}

	rb.chunks[rb.head] = chunk
	rb.head = (rb.head + 1) % rb.capacity

	if rb.count < rb.capacity {
		rb.count++
	} else {
		// Overwriting oldest unread item
		rb.tail = (rb.tail + 1) % rb.capacity
	}

	rb.activeTurnID = turnID
	return true
}

// Pop extracts the next 20ms frame in FIFO order.
// Returns the audio chunk, turn ID, and true if available; otherwise returns empty and false.
func (rb *RingBuffer) Pop() ([]byte, string, bool) {
	rb.mu.Lock()
	defer rb.mu.Unlock()

	if rb.count == 0 {
		return nil, "", false
	}

	chunk := rb.chunks[rb.tail]
	// Clear reference to avoid memory retention
	rb.chunks[rb.tail] = AudioChunk{}
	rb.tail = (rb.tail + 1) % rb.capacity
	rb.count--

	// Record 20ms of playback
	rb.playedMs.Add(20)

	return chunk.Data, chunk.TurnID, true
}

// Purge instantaneously flushes all buffered unplayed audio frames.
// This is called during barge-in to stop playback immediately (<1ms).
// Returns the number of discarded milliseconds of audio.
func (rb *RingBuffer) Purge() uint32 {
	rb.mu.Lock()
	defer rb.mu.Unlock()

	discardedCount := rb.count
	// Reset indices
	for i := 0; i < rb.capacity; i++ {
		rb.chunks[i] = AudioChunk{}
	}
	rb.head = 0
	rb.tail = 0
	rb.count = 0

	return uint32(discardedCount * 20)
}

// PlayedMs returns the cumulative milliseconds of audio successfully popped for playback.
func (rb *RingBuffer) PlayedMs() uint32 {
	return uint32(rb.playedMs.Load())
}

// ResetPlayedMs resets the playback duration counter (e.g. at the start of a turn).
func (rb *RingBuffer) ResetPlayedMs() {
	rb.playedMs.Store(0)
}

// Len returns the current number of buffered frames.
func (rb *RingBuffer) Len() int {
	rb.mu.RLock()
	defer rb.mu.RUnlock()
	return rb.count
}

// ActiveTurnID returns the turn ID of the latest written chunks.
func (rb *RingBuffer) ActiveTurnID() string {
	rb.mu.RLock()
	defer rb.mu.RUnlock()
	return rb.activeTurnID
}
