package ingress

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"sync"

	"github.com/gorilla/websocket"
	"github.com/ajay7231/pulsemux/gateway-go/internal/audio"
)

var upgrader = websocket.Upgrader{
	CheckOrigin: func(r *http.Request) bool { return true },
}

// TwilioMessage matches the JSON schema for Twilio Media Streams.
type TwilioMessage struct {
	Event     string          `json:"event"`
	SequenceNumber string     `json:"sequenceNumber,omitempty"`
	StreamSid string          `json:"streamSid,omitempty"`
	Media     *TwilioMedia    `json:"media,omitempty"`
	Start     *TwilioStart    `json:"start,omitempty"`
	Stop      *TwilioStop     `json:"stop,omitempty"`
}

type TwilioMedia struct {
	Payload   string `json:"payload"`
	Track     string `json:"track,omitempty"`
	Chunk     string `json:"chunk,omitempty"`
	Timestamp string `json:"timestamp,omitempty"`
}

type TwilioStart struct {
	StreamSid       string            `json:"streamSid"`
	AccountSid      string            `json:"accountSid"`
	CallSid         string            `json:"callSid"`
	CustomParameters map[string]string `json:"customParameters"`
}

type TwilioStop struct {
	AccountSid string `json:"accountSid"`
	CallSid    string `json:"callSid"`
}

// TwilioSessionSink implements session.IngressSink for Twilio WebSocket connections.
type TwilioSessionSink struct {
	conn      *websocket.Conn
	streamSid string
	mu        sync.Mutex
}

func NewTwilioSessionSink(conn *websocket.Conn, streamSid string) *TwilioSessionSink {
	return &TwilioSessionSink{
		conn:      conn,
		streamSid: streamSid,
	}
}

// SendAudioFrame downsamples 16kHz PCM to 8kHz mu-law and sends a Twilio media payload.
func (s *TwilioSessionSink) SendAudioFrame(pcm []byte) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	muLaw := audio.EncodePCM16kToMuLaw8k(pcm)
	if len(muLaw) == 0 {
		return nil
	}

	b64 := base64.StdEncoding.EncodeToString(muLaw)
	msg := TwilioMessage{
		Event:     "media",
		StreamSid: s.streamSid,
		Media: &TwilioMedia{
			Payload: b64,
		},
	}

	return s.conn.WriteJSON(msg)
}

// SendClearBufferSignal sends Twilio's "clear" event to wipe its outbound jitter buffer immediately.
func (s *TwilioSessionSink) SendClearBufferSignal() error {
	s.mu.Lock()
	defer s.mu.Unlock()

	msg := map[string]string{
		"event":     "clear",
		"streamSid": s.streamSid,
	}
	return s.conn.WriteJSON(msg)
}

func (s *TwilioSessionSink) Close() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.conn.Close()
}

// SessionHandler defines callback interface invoked by ingress handlers.
type SessionHandler interface {
	OnCallStarted(callID, patientID string, sink *TwilioSessionSink) (func(pcm []byte) error, func(), error)
}

// TwilioWebSocketHandler returns an HTTP handler for /ws/twilio.
func TwilioWebSocketHandler(handler SessionHandler) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			http.Error(w, fmt.Sprintf("failed to upgrade websocket: %v", err), http.StatusBadRequest)
			return
		}
		defer conn.Close()

		var streamSid, callSid, patientID string
		var sink *TwilioSessionSink
		var onPCMChunk func([]byte) error
		var cleanupSession func()

		// Buffer incoming mu-law bytes until we have a complete 20ms frame (160 bytes mu-law = 640 bytes 16kHz PCM)
		var muLawBuffer []byte
		const muLaw20msBytes = 160

		for {
			_, msgBytes, err := conn.ReadMessage()
			if err != nil {
				if cleanupSession != nil {
					cleanupSession()
				}
				break
			}

			var msg TwilioMessage
			if err := json.Unmarshal(msgBytes, &msg); err != nil {
				continue
			}

			switch msg.Event {
			case "connected":
				// Twilio handshake acknowledgement
				continue

			case "start":
				if msg.Start != nil {
					streamSid = msg.Start.StreamSid
					callSid = msg.Start.CallSid
					if val, ok := msg.Start.CustomParameters["patient_id"]; ok {
						patientID = val
					} else {
						patientID = "patient-anon"
					}
					sink = NewTwilioSessionSink(conn, streamSid)
					onPCMChunk, cleanupSession, _ = handler.OnCallStarted(callSid, patientID, sink)
				}

			case "media":
				if msg.Media != nil && onPCMChunk != nil {
					rawMuLaw, err := base64.StdEncoding.DecodeString(msg.Media.Payload)
					if err != nil {
						continue
					}

					muLawBuffer = append(muLawBuffer, rawMuLaw...)

					for len(muLawBuffer) >= muLaw20msBytes {
						chunk := muLawBuffer[:muLaw20msBytes]
						muLawBuffer = muLawBuffer[muLaw20msBytes:]

						pcmChunk := audio.DecodeMuLaw8kToPCM16k(chunk)
						_ = onPCMChunk(pcmChunk)
					}
				}

			case "stop":
				if cleanupSession != nil {
					cleanupSession()
				}
				return
			}
		}
	}
}
