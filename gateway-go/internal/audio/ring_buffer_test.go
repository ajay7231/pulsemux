package audio

import (
	"sync"
	"testing"
)

func TestRingBuffer_PushPop(t *testing.T) {
	rb := NewRingBuffer(10)
	sample := make([]byte, FrameSize16kHz20ms)
	sample[0] = 0x42

	rb.Push(sample, "turn-1")
	if rb.Len() != 1 {
		t.Fatalf("expected len 1, got %d", rb.Len())
	}

	data, turnID, ok := rb.Pop()
	if !ok || turnID != "turn-1" || len(data) != FrameSize16kHz20ms || data[0] != 0x42 {
		t.Fatalf("unexpected pop result: ok=%v, turnID=%s", ok, turnID)
	}

	if rb.PlayedMs() != 20 {
		t.Fatalf("expected 20ms played, got %d", rb.PlayedMs())
	}
}

func TestRingBuffer_Purge(t *testing.T) {
	rb := NewRingBuffer(10)
	sample := make([]byte, FrameSize16kHz20ms)

	for i := 0; i < 5; i++ {
		rb.Push(sample, "turn-2")
	}

	discarded := rb.Purge()
	if discarded != 100 { // 5 frames * 20ms = 100ms
		t.Fatalf("expected 100ms discarded, got %d", discarded)
	}

	if rb.Len() != 0 {
		t.Fatalf("expected empty buffer after purge, got %d", rb.Len())
	}
}

func TestRingBuffer_ConcurrentRaceCondition(t *testing.T) {
	rb := NewRingBuffer(50)
	var wg sync.WaitGroup
	chunk := make([]byte, FrameSize16kHz20ms)

	// Writer goroutine
	wg.Add(1)
	go func() {
		defer wg.Done()
		for i := 0; i < 500; i++ {
			rb.Push(chunk, "turn-test")
		}
	}()

	// Reader goroutine
	wg.Add(1)
	go func() {
		defer wg.Done()
		for i := 0; i < 500; i++ {
			rb.Pop()
		}
	}()

	// Purger goroutine (simulating barge-in)
	wg.Add(1)
	go func() {
		defer wg.Done()
		for i := 0; i < 50; i++ {
			rb.Purge()
		}
	}()

	wg.Wait()
}
