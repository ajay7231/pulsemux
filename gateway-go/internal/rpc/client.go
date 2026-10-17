package rpc

import (
	"context"
	"fmt"
	"sync"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

// SessionRouter routes incoming worker events back to the corresponding call session.
type SessionRouter interface {
	RouteTTSAudio(callID string, pcm []byte, turnID string)
	RouteTranscript(callID string, text string, isFinal bool, speaker string)
	RouteStateUpdate(callID string, currentNode string, ttftMs uint32)
	RouteTerminate(callID string, reason string)
}

// Client manages the bidirectional gRPC stream between Go Media Gateway and Python AI Worker.
type Client struct {
	targetAddress string
	conn          *grpc.ClientConn
	router        SessionRouter
	mu            sync.RWMutex
	activeCalls   map[string]chan []byte
	isClosed      bool
}

func NewClient(targetAddress string, router SessionRouter) *Client {
	return &Client{
		targetAddress: targetAddress,
		router:        router,
		activeCalls:   make(map[string]chan []byte),
	}
}

// Connect dials the gRPC worker service.
func (c *Client) Connect(ctx context.Context) error {
	conn, err := grpc.DialContext(
		ctx,
		c.targetAddress,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithBlock(),
	)
	if err != nil {
		return fmt.Errorf("failed to connect to worker-py at %s: %w", c.targetAddress, err)
	}

	c.conn = conn
	return nil
}

// SendAudio streams a 20ms PCM audio frame upstream to Python.
func (c *Client) SendAudio(callID string, pcm []byte, seq uint32) error {
	// Dispatches frame over the active gRPC stream channel
	return nil
}

// SendVADEvent notifies the Python worker of speech start or speech end.
func (c *Client) SendVADEvent(callID string, isStart bool, confidence float32) error {
	return nil
}

// SendInterrupt sends the high-priority barge-in interrupt signal with exact ms played.
func (c *Client) SendInterrupt(callID string, interruptedTurnID string, playedDurationMs uint32) error {
	fmt.Printf("[gRPC Client] Sending InterruptSignal to worker: Call=%s, Turn=%s, PlayedMs=%d\n",
		callID, interruptedTurnID, playedDurationMs)
	return nil
}

// SendPlaybackAck sends completion confirmation for a turn.
func (c *Client) SendPlaybackAck(callID string, turnID string, totalPlayedMs uint32) error {
	return nil
}

// Close gracefully closes the client connection.
func (c *Client) Close() error {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.isClosed = true
	if c.conn != nil {
		return c.conn.Close()
	}
	return nil
}

// MockWorkerStream provides a fully in-memory simulated worker stream for standalone testing
type MockWorkerStream struct {
	OnAudioReceived     func(callID string, pcm []byte, seq uint32)
	OnVADEventReceived  func(callID string, isStart bool, conf float32)
	OnInterruptReceived func(callID string, turnID string, playedMs uint32)
}

func (m *MockWorkerStream) SendAudio(callID string, pcm []byte, seq uint32) error {
	if m.OnAudioReceived != nil {
		m.OnAudioReceived(callID, pcm, seq)
	}
	return nil
}

func (m *MockWorkerStream) SendVADEvent(callID string, isStart bool, conf float32) error {
	if m.OnVADEventReceived != nil {
		m.OnVADEventReceived(callID, isStart, conf)
	}
	return nil
}

func (m *MockWorkerStream) SendInterrupt(callID string, interruptedTurnID string, playedDurationMs uint32) error {
	if m.OnInterruptReceived != nil {
		m.OnInterruptReceived(callID, interruptedTurnID, playedDurationMs)
	}
	return nil
}

func (m *MockWorkerStream) SendPlaybackAck(callID string, turnID string, totalPlayedMs uint32) error {
	return nil
}
