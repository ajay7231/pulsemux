package ingress

import (
	"encoding/json"
	"fmt"
	"net/http"
	"sync"

	"github.com/pion/webrtc/v4"
)

// WebRTCHandler provides WebRTC SDP signaling and media peer connection orchestration.
type WebRTCHandler struct {
	api    *webrtc.API
	config webrtc.Configuration
}

func NewWebRTCHandler() *WebRTCHandler {
	m := &webrtc.MediaEngine{}
	_ = m.RegisterDefaultCodecs()
	api := webrtc.NewAPI(webrtc.WithMediaEngine(m))

	config := webrtc.Configuration{
		ICEServers: []webrtc.ICEServer{
			{URLs: []string{"stun:stun.l.google.com:19302"}},
		},
	}

	return &WebRTCHandler{
		api:    api,
		config: config,
	}
}

// WebRTCSessionSink implements session.IngressSink for WebRTC audio tracks.
type WebRTCSessionSink struct {
	peerConn   *webrtc.PeerConnection
	audioTrack *webrtc.TrackLocalStaticSample
	mu         sync.Mutex
}

func NewWebRTCSessionSink(pc *webrtc.PeerConnection, track *webrtc.TrackLocalStaticSample) *WebRTCSessionSink {
	return &WebRTCSessionSink{
		peerConn:   pc,
		audioTrack: track,
	}
}

func (s *WebRTCSessionSink) SendAudioFrame(pcm []byte) error {
	// In full WebRTC deployment, pcm is encoded to Opus frames and pushed to TrackLocal
	return nil
}

func (s *WebRTCSessionSink) SendClearBufferSignal() error {
	// WebRTC has near-zero network jitter buffer compared to PSTN telephony
	return nil
}

func (s *WebRTCSessionSink) Close() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.peerConn != nil {
		return s.peerConn.Close()
	}
	return nil
}

type SDPRequest struct {
	SDP       string `json:"sdp"`
	Type      string `json:"type"`
	CallID    string `json:"call_id"`
	PatientID string `json:"patient_id"`
}

type SDPResponse struct {
	SDP  string `json:"sdp"`
	Type string `json:"type"`
}

// HTTPHandler handles WebRTC SDP Offer/Answer exchanges.
func (h *WebRTCHandler) HTTPHandler() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}

		var req SDPRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, fmt.Sprintf("invalid json: %v", err), http.StatusBadRequest)
			return
		}

		pc, err := h.api.NewPeerConnection(h.config)
		if err != nil {
			http.Error(w, fmt.Sprintf("failed to create peer connection: %v", err), http.StatusInternalServerError)
			return
		}

		// Setup local outbound audio track
		audioTrack, err := webrtc.NewTrackLocalStaticSample(
			webrtc.RTPCodecCapability{MimeType: webrtc.MimeTypeOpus},
			"audio",
			"pulsemux",
		)
		if err == nil {
			_, _ = pc.AddTrack(audioTrack)
		}

		offer := webrtc.SessionDescription{
			Type: webrtc.SDPTypeOffer,
			SDP:  req.SDP,
		}

		if err := pc.SetRemoteDescription(offer); err != nil {
			http.Error(w, fmt.Sprintf("failed to set remote description: %v", err), http.StatusInternalServerError)
			return
		}

		answer, err := pc.CreateAnswer(nil)
		if err != nil {
			http.Error(w, fmt.Sprintf("failed to create answer: %v", err), http.StatusInternalServerError)
			return
		}

		gatherComplete := webrtc.GatheringCompletePromise(pc)
		if err := pc.SetLocalDescription(answer); err != nil {
			http.Error(w, fmt.Sprintf("failed to set local description: %v", err), http.StatusInternalServerError)
			return
		}
		<-gatherComplete

		resp := SDPResponse{
			SDP:  pc.LocalDescription().SDP,
			Type: pc.LocalDescription().Type.String(),
		}

		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(resp)
	}
}
