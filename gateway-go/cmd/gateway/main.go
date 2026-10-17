package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"

	"github.com/ajay7231/pulsemux/gateway-go/internal/ingress"
	"github.com/ajay7231/pulsemux/gateway-go/internal/rpc"
	"github.com/ajay7231/pulsemux/gateway-go/internal/session"
)

type GatewayServer struct {
	mu          sync.RWMutex
	sessions    map[string]*session.CallSession
	mockWorker  *rpc.MockWorkerStream
	grpcClient  *rpc.Client
}

func NewGatewayServer() *GatewayServer {
	gw := &GatewayServer{
		sessions: make(map[string]*session.CallSession),
	}

	// Setup local mock worker stream for immediate testing and verification
	gw.mockWorker = &rpc.MockWorkerStream{
		OnAudioReceived: func(callID string, pcm []byte, seq uint32) {
			// Telemetry/debug: frame received
		},
		OnVADEventReceived: func(callID string, isStart bool, conf float32) {
			event := "SPEECH_END"
			if isStart {
				event = "SPEECH_START"
			}
			log.Printf("[VAD] Call=%s Event=%s Confidence=%.2f", callID, event, conf)
		},
		OnInterruptReceived: func(callID string, turnID string, playedMs uint32) {
			log.Printf("[INTERRUPT] Call=%s Turn=%s Played=%dms", callID, turnID, playedMs)
		},
	}

	return gw
}

func (s *GatewayServer) OnCallStarted(callID, patientID string, sink *ingress.TwilioSessionSink) (func([]byte) error, func(), error) {
	s.mu.Lock()
	defer s.mu.Unlock()

	ctx := context.Background()
	callSession := session.NewCallSession(ctx, callID, patientID, sink, s.mockWorker)
	s.sessions[callID] = callSession
	callSession.Start()

	log.Printf("[Session] Active call started: CallID=%s, PatientID=%s", callID, patientID)

	onPCMChunk := func(pcm []byte) error {
		return callSession.HandleIncomingPCMFrame(pcm)
	}

	cleanup := func() {
		s.mu.Lock()
		delete(s.sessions, callID)
		s.mu.Unlock()
		callSession.Close()
		log.Printf("[Session] Call completed and cleaned up: CallID=%s", callID)
	}

	return onPCMChunk, cleanup, nil
}

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	workerAddr := os.Getenv("WORKER_ADDR")
	if workerAddr == "" {
		workerAddr = "localhost:50051"
	}

	server := NewGatewayServer()
	webrtcHandler := ingress.NewWebRTCHandler()

	mux := http.NewServeMux()

	// Ingress endpoints
	mux.HandleFunc("/ws/twilio", ingress.TwilioWebSocketHandler(server))
	mux.HandleFunc("/webrtc/sdp", webrtcHandler.HTTPHandler())

	// Health and metrics
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"status":"ok","service":"pulse-gateway"}`))
	})

	httpServer := &http.Server{
		Addr:         ":" + port,
		Handler:      mux,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 15 * time.Second,
	}

	// Graceful shutdown listener
	stopChan := make(chan os.Signal, 1)
	signal.Notify(stopChan, os.Interrupt, syscall.SIGTERM)

	go func() {
		log.Printf("==================================================")
		log.Printf(" PulseMux Go Media Gateway (pulse-gateway)")
		log.Printf(" Listening on port :%s", port)
		log.Printf(" Telephony WS:   http://localhost:%s/ws/twilio", port)
		log.Printf(" WebRTC SDP:     http://localhost:%s/webrtc/sdp", port)
		log.Printf(" Health Check:   http://localhost:%s/healthz", port)
		log.Printf("==================================================")
		if err := httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("Gateway server failed: %v", err)
		}
	}()

	<-stopChan
	log.Println("[Gateway] Shutting down gracefully...")

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := httpServer.Shutdown(shutdownCtx); err != nil {
		log.Printf("Server shutdown error: %v", err)
	}
	log.Println("[Gateway] Shutdown complete.")
}
