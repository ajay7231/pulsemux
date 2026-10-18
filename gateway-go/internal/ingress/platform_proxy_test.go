package ingress

import (
	"github.com/gorilla/websocket"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestPlatformProxyPreservesAuthAndWebSocketFrames(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Twilio-Signature") != "test-signature" {
			t.Error("signature header was lost")
		}
		if r.URL.Path == "/ws/telephony/test-call" {
			conn, err := (&websocket.Upgrader{CheckOrigin: func(r *http.Request) bool { return true }}).Upgrade(w, r, nil)
			if err != nil {
				t.Error(err)
				return
			}
			defer conn.Close()
			kind, payload, err := conn.ReadMessage()
			if err != nil {
				t.Error(err)
				return
			}
			if err := conn.WriteMessage(kind, payload); err != nil {
				t.Error(err)
			}
			return
		}
		if r.URL.Path != "/api/bootstrap" {
			t.Errorf("wrong path: %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		io.WriteString(w, `{"setup_required":true}`)
	}))
	defer upstream.Close()
	handler, err := PlatformProxy(upstream.URL)
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(handler)
	defer server.Close()
	request, _ := http.NewRequest("GET", server.URL+"/api/bootstrap", nil)
	request.Header.Set("X-Twilio-Signature", "test-signature")
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	payload, _ := io.ReadAll(response.Body)
	response.Body.Close()
	if string(payload) != `{"setup_required":true}` {
		t.Fatalf("unexpected response: %s", payload)
	}
	header := http.Header{"X-Twilio-Signature": []string{"test-signature"}}
	conn, _, err := websocket.DefaultDialer.Dial(strings.Replace(server.URL, "http://", "ws://", 1)+"/ws/telephony/test-call", header)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	frame := []byte(`{"event":"media","media":{"payload":"AAAA"}}`)
	if err := conn.WriteMessage(websocket.TextMessage, frame); err != nil {
		t.Fatal(err)
	}
	_, result, err := conn.ReadMessage()
	if err != nil {
		t.Fatal(err)
	}
	if string(result) != string(frame) {
		t.Fatalf("media envelope changed: %s", result)
	}
}
