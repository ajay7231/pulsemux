package ingress

import (
	"encoding/binary"
	"fmt"
	"math"
	"net/http"
	"sync"
)

// ConsoleServer provides the browser-based mic testing UI and simulation endpoints.
type ConsoleServer struct {
	mu           sync.RWMutex
	getSessions  func() []string
	simulateFunc func(callID string) error
}

func NewConsoleServer(getSessions func() []string, simulateFunc func(callID string) error) *ConsoleServer {
	return &ConsoleServer{
		getSessions:  getSessions,
		simulateFunc: simulateFunc,
	}
}

// Handler returns the HTTP handler for serving the browser test console.
func (cs *ConsoleServer) Handler() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = w.Write([]byte(consoleHTML))
	}
}

// SimulateAgentHandler handles POST /api/simulate-agent to push synthetic speech into active call.
func (cs *ConsoleServer) SimulateAgentHandler() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		callID := r.URL.Query().Get("call_id")
		if cs.simulateFunc == nil {
			http.Error(w, `{"error":"simulation not configured"}`, http.StatusInternalServerError)
			return
		}
		if err := cs.simulateFunc(callID); err != nil {
			http.Error(w, fmt.Sprintf(`{"error":"%v"}`, err), http.StatusBadRequest)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"status":"ok","message":"agent speech enqueued"}`))
	}
}

// GenerateSynthesizedVoicePCM creates synthetic voice-like multi-harmonic PCM frames (16kHz 16-bit mono).
func GenerateSynthesizedVoicePCM(durationMs int) [][]byte {
	numChunks := durationMs / 20 // 20ms per chunk
	chunks := make([][]byte, numChunks)
	baseFreq := 210.0 // Hz

	for i := 0; i < numChunks; i++ {
		chunk := make([]byte, 640) // 320 samples * 2 bytes = 640 bytes per 20ms at 16kHz
		freq := baseFreq + 35.0*math.Sin(float64(i)*0.15)

		for sIdx := 0; sIdx < 320; sIdx++ {
			t := float64(i*320+sIdx) / 16000.0
			// Multi-harmonic vocal tone
			val := 0.65*math.Sin(2*math.Pi*freq*t) +
				0.25*math.Sin(2*math.Pi*freq*2*t) +
				0.10*math.Sin(2*math.Pi*freq*3*t)

			// Fade in / out envelopes
			env := 1.0
			if i < 8 {
				env = float64(i) / 8.0
			} else if i > numChunks-8 {
				env = float64(numChunks-i) / 8.0
			}

			sample := int16(val * env * 14000.0)
			binary.LittleEndian.PutUint16(chunk[sIdx*2:], uint16(sample))
		}
		chunks[i] = chunk
	}
	return chunks
}

const consoleHTML = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>PulseMux — Voice Gateway Browser Test Console</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-dark: #070a12;
      --bg-card: #0f1629;
      --bg-card-hover: #162038;
      --border: #1e293b;
      --border-glow: rgba(59, 130, 246, 0.35);
      --primary: #3b82f6;
      --primary-hover: #2563eb;
      --cyan: #06b6d4;
      --emerald: #10b981;
      --rose: #ef4444;
      --amber: #f59e0b;
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      background-color: var(--bg-dark);
      color: var(--text-main);
      font-family: 'Plus Jakarta Sans', system-ui, -apple-system, sans-serif;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }

    header {
      background: rgba(15, 22, 41, 0.85);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--border);
      padding: 1rem 2rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      position: sticky;
      top: 0;
      z-index: 100;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 0.75rem;
    }

    .brand-icon {
      width: 34px;
      height: 34px;
      border-radius: 8px;
      background: linear-gradient(135deg, #06b6d4, #3b82f6);
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 800;
      font-size: 1.1rem;
      color: #fff;
      box-shadow: 0 0 20px rgba(6, 182, 212, 0.4);
    }

    .brand-title {
      font-weight: 700;
      font-size: 1.25rem;
      letter-spacing: -0.02em;
    }

    .brand-subtitle {
      font-size: 0.75rem;
      color: var(--cyan);
      font-family: 'JetBrains Mono', monospace;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }

    .header-badges {
      display: flex;
      gap: 0.75rem;
      align-items: center;
    }

    .badge {
      display: inline-flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.4rem 0.85rem;
      border-radius: 9999px;
      font-size: 0.8rem;
      font-weight: 600;
      font-family: 'JetBrains Mono', monospace;
      border: 1px solid var(--border);
      background: rgba(15, 23, 42, 0.6);
    }

    .badge-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--text-muted);
    }

    .badge-dot.active {
      background: var(--emerald);
      box-shadow: 0 0 10px var(--emerald);
    }

    .container {
      max-width: 1300px;
      margin: 0 auto;
      padding: 2rem;
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1.75rem;
      flex: 1;
    }

    .card {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 1.5rem;
      display: flex;
      flex-direction: column;
      gap: 1.25rem;
      position: relative;
      overflow: hidden;
    }

    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .card-title {
      font-size: 1.05rem;
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }

    /* Waveform canvas */
    .waveform-box {
      background: #090d1a;
      border: 1px solid var(--border);
      border-radius: 12px;
      height: 110px;
      position: relative;
      overflow: hidden;
    }

    canvas {
      width: 100%;
      height: 100%;
      display: block;
    }

    .level-bar-container {
      background: #090d1a;
      border: 1px solid var(--border);
      height: 10px;
      border-radius: 5px;
      overflow: hidden;
      position: relative;
    }

    .level-bar-fill {
      height: 100%;
      width: 0%;
      background: linear-gradient(90deg, #10b981, #f59e0b, #ef4444);
      transition: width 0.05s ease-out;
    }

    /* Controls */
    .btn-row {
      display: flex;
      gap: 0.75rem;
      flex-wrap: wrap;
    }

    button {
      padding: 0.75rem 1.25rem;
      font-size: 0.9rem;
      font-weight: 600;
      border-radius: 10px;
      border: none;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 0.5rem;
      transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
      font-family: inherit;
    }

    .btn-primary {
      background: linear-gradient(135deg, #2563eb, #06b6d4);
      color: #fff;
      box-shadow: 0 4px 15px rgba(37, 99, 235, 0.35);
    }
    .btn-primary:hover:not(:disabled) {
      transform: translateY(-1px);
      box-shadow: 0 6px 20px rgba(6, 182, 212, 0.45);
    }

    .btn-danger {
      background: linear-gradient(135deg, #ef4444, #b91c1c);
      color: #fff;
    }

    .btn-secondary {
      background: #1e293b;
      color: var(--text-main);
      border: 1px solid var(--border);
    }
    .btn-secondary:hover:not(:disabled) {
      background: #334155;
    }

    button:disabled {
      opacity: 0.5;
      cursor: not-allowed;
      transform: none !important;
      box-shadow: none !important;
    }

    /* Barge-in alert banner */
    .barge-in-banner {
      display: none;
      background: rgba(239, 68, 68, 0.15);
      border: 1px solid var(--rose);
      border-radius: 10px;
      padding: 0.85rem 1rem;
      color: #fca5a5;
      font-size: 0.9rem;
      font-weight: 600;
      align-items: center;
      gap: 0.6rem;
      animation: flash 0.3s ease;
    }

    @keyframes flash {
      0% { transform: scale(0.98); opacity: 0.5; }
      100% { transform: scale(1); opacity: 1; }
    }

    /* Metric Grids */
    .metric-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 0.75rem;
    }

    .metric-cell {
      background: #090d1a;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 0.85rem;
    }

    .metric-label {
      font-size: 0.75rem;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      font-family: 'JetBrains Mono', monospace;
    }

    .metric-val {
      font-size: 1.4rem;
      font-weight: 700;
      margin-top: 0.25rem;
      font-family: 'JetBrains Mono', monospace;
      color: var(--text-main);
    }

    /* Console logs */
    .terminal-box {
      background: #050811;
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1rem;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.78rem;
      height: 240px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 0.35rem;
      color: #94a3b8;
    }

    .log-line {
      display: flex;
      gap: 0.5rem;
      line-height: 1.4;
    }

    .log-time { color: #64748b; }
    .log-tag { font-weight: 700; }
    .tag-ws { color: var(--cyan); }
    .tag-vad { color: var(--amber); }
    .tag-barge { color: var(--rose); font-weight: 800; }
    .tag-agent { color: var(--emerald); }

    @media (max-width: 900px) {
      .container { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>

  <header>
    <div class="brand">
      <div class="brand-icon">P</div>
      <div>
        <div class="brand-title">PulseMux — Voice Gateway Console</div>
        <div class="brand-subtitle">Telephony & Web Audio Ingress Simulator</div>
      </div>
    </div>
    <div class="header-badges">
      <div class="badge">
        <span class="badge-dot" id="ws-status-dot"></span>
        <span id="ws-status-text">Disconnected</span>
      </div>
      <div class="badge" style="color: var(--cyan);">
        SLA Target: &lt;45ms
      </div>
    </div>
  </header>

  <main class="container">
    <!-- LEFT CARD: MICROPHONE & CALL CONTROLS -->
    <section class="card">
      <div class="card-header">
        <div class="card-title">🎙️ Patient Audio Ingress (Web Mic)</div>
        <span id="session-tag" class="badge" style="font-size:0.75rem;">Session: Idle</span>
      </div>

      <p style="font-size: 0.88rem; color: var(--text-muted); line-height: 1.5;">
        Connects your laptop microphone as a <b>8kHz G.711 &mu;-law 20ms frame streamer</b> directly into <code>/ws/twilio</code>. No Twilio number or phone bill required.
      </p>

      <!-- Live Waveform -->
      <div class="waveform-box">
        <canvas id="waveform-canvas"></canvas>
      </div>

      <!-- Mic Energy Level -->
      <div>
        <div style="display:flex; justify-content:space-between; font-size:0.75rem; color:var(--text-muted); margin-bottom:0.3rem;">
          <span>Mic Energy Level (RMS)</span>
          <span id="rms-label">0%</span>
        </div>
        <div class="level-bar-container">
          <div class="level-bar-fill" id="rms-fill"></div>
        </div>
      </div>

      <!-- Call Action Buttons -->
      <div class="btn-row">
        <button id="btn-call" class="btn-primary" onclick="toggleCall()">
          <span>📞</span> <span id="btn-call-text">Start Patient Call</span>
        </button>
        <button id="btn-agent-speak" class="btn-secondary" onclick="triggerAgentSpeak()" disabled>
          <span>🤖</span> <span>Trigger Agent Voice (TTS)</span>
        </button>
        <button id="btn-mock-speech" class="btn-secondary" onclick="sendMockSpeech()" disabled>
          <span>🗣️</span> <span>Inject Patient Burst</span>
        </button>
      </div>

      <!-- Barge-in Alert Banner -->
      <div id="barge-in-banner" class="barge-in-banner">
        <span style="font-size: 1.3rem;">⚡</span>
        <div>
          <div style="font-weight: 700; color: #fff;">BARGE-IN TRIGGERED (&lt;35ms)</div>
          <div style="font-size: 0.8rem;">Agent TTS audio instantly purged from jitter buffer upon speech detection.</div>
        </div>
      </div>
    </section>

    <!-- RIGHT CARD: REAL-TIME TELEMETRY & EVENTS -->
    <section class="card">
      <div class="card-header">
        <div class="card-title">📊 Real-Time Pipeline Telemetry</div>
        <span class="badge" id="vad-badge" style="background:#090d1a;">VAD: SILENCE</span>
      </div>

      <!-- Metric Grid -->
      <div class="metric-grid">
        <div class="metric-cell">
          <div class="metric-label">Frames Sent</div>
          <div class="metric-val" id="metric-sent">0</div>
        </div>
        <div class="metric-cell">
          <div class="metric-label">Frames Recv</div>
          <div class="metric-val" id="metric-recv">0</div>
        </div>
        <div class="metric-cell">
          <div class="metric-label">Barge-Ins</div>
          <div class="metric-val" id="metric-barge" style="color:var(--rose);">0</div>
        </div>
      </div>

      <!-- Live Event Terminal Feed -->
      <div>
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.4rem;">
          <span style="font-size:0.75rem; color:var(--text-muted); font-family:'JetBrains Mono', monospace; text-transform:uppercase;">Protocol Event Feed</span>
          <button style="padding:0.2rem 0.5rem; font-size:0.7rem; background:transparent; border:1px solid var(--border); color:var(--text-muted);" onclick="clearLogs()">Clear</button>
        </div>
        <div class="terminal-box" id="terminal-feed">
          <div class="log-line">
            <span class="log-time">[00:00:00]</span>
            <span class="log-tag tag-ws">[SYSTEM]</span>
            <span>Test console initialized. Click "Start Patient Call" to begin streaming.</span>
          </div>
        </div>
      </div>
    </section>
  </main>

  <script>
    // Audio & WebSocket State
    let isCalling = false;
    let ws = null;
    let audioCtx = null;
    let micStream = null;
    let processorNode = null;
    let streamSid = null;
    let callSid = null;
    let frameSequence = 0;
    let framesSent = 0;
    let framesRecv = 0;
    let bargeInCount = 0;

    // Audio Playback Queue for Agent Speech
    let nextPlayTime = 0;
    let activeAudioSources = [];

    // G.711 mu-law encoder / decoder
    const BIAS = 0x84;
    const CLIP = 32635;

    function linearToMuLaw(sample) {
      let sign = (sample >> 8) & 0x80;
      if (sign !== 0) sample = -sample;
      if (sample > CLIP) sample = CLIP;
      sample = sample + BIAS;
      let exponent = 7;
      for (let expMask = 0x4000; (sample & expMask) === 0 && exponent > 0; exponent--, expMask >>= 1) {}
      let mantissa = (sample >> (exponent + 3)) & 0x0F;
      return ~(sign | (exponent << 4) | mantissa) & 0xFF;
    }

    function muLawToLinear(muLawByte) {
      let u = ~muLawByte & 0xFF;
      let sign = u & 0x80;
      let exponent = (u >> 4) & 0x07;
      let mantissa = u & 0x0F;
      let sample = ((mantissa << 3) + 0x84) << exponent;
      sample -= 0x84;
      return sign === 0 ? -sample : sample;
    }

    function logEvent(tag, tagClass, text) {
      const feed = document.getElementById("terminal-feed");
      const line = document.createElement("div");
      line.className = "log-line";
      const now = new Date();
      const timeStr = now.toTimeString().split(' ')[0] + '.' + String(now.getMilliseconds()).padStart(3, '0');
      line.innerHTML = '<span class="log-time">[' + timeStr + ']</span><span class="log-tag ' + tagClass + '">[' + tag + ']</span><span>' + text + '</span>';
      feed.appendChild(line);
      feed.scrollTop = feed.scrollHeight;
    }

    function clearLogs() {
      document.getElementById("terminal-feed").innerHTML = "";
    }

    // Toggle Call Lifecycle
    async function toggleCall() {
      if (!isCalling) {
        await startCall();
      } else {
        stopCall();
      }
    }

    async function startCall() {
      try {
        logEvent("MIC", "tag-ws", "Requesting microphone permission (8kHz mono)...");
        micStream = await navigator.mediaDevices.getUserMedia({
          audio: {
            channelCount: 1,
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true
          }
        });

        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        logEvent("AUDIO", "tag-agent", "AudioContext started at " + audioCtx.sampleRate + "Hz native sample rate.");

        const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const wsUrl = wsProtocol + "//" + window.location.host + "/ws/twilio";

        logEvent("WS", "tag-ws", "Connecting to " + wsUrl);
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
          document.getElementById("ws-status-dot").classList.add("active");
          document.getElementById("ws-status-text").innerText = "Call Connected";
          document.getElementById("session-tag").innerText = "Session: Active";

          callSid = "CA" + Math.random().toString(36).substring(2, 12);
          streamSid = "MZ" + Math.random().toString(36).substring(2, 12);

          // 1. Send Twilio Handshake
          ws.send(JSON.stringify({ event: "connected", protocol: "Call", version: "1.0.0" }));
          ws.send(JSON.stringify({
            event: "start",
            sequenceNumber: "1",
            start: {
              streamSid: streamSid,
              accountSid: "AC_TEST_ACCOUNT",
              callSid: callSid,
              customParameters: { patient_id: "patient-browser-01" }
            }
          }));

          logEvent("TWILIO", "tag-ws", "Sent Twilio 'start' handshake. StreamSid=" + streamSid);
          setupMicProcessing();

          document.getElementById("btn-call-text").innerText = "End Call";
          document.getElementById("btn-call").classList.remove("btn-primary");
          document.getElementById("btn-call").classList.add("btn-danger");
          document.getElementById("btn-agent-speak").disabled = false;
          document.getElementById("btn-mock-speech").disabled = false;
          isCalling = true;
        };

        ws.onmessage = (event) => {
          handleIncomingWSMessage(event.data);
        };

        ws.onclose = () => {
          logEvent("WS", "tag-ws", "WebSocket connection closed.");
          stopCall();
        };

        ws.onerror = (err) => {
          logEvent("ERROR", "tag-barge", "WebSocket error: " + err);
        };

      } catch (err) {
        logEvent("ERROR", "tag-barge", "Failed to start call: " + err.message);
        alert("Microphone error: " + err.message);
      }
    }

    function stopCall() {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ event: "stop", stop: { callSid: callSid } }));
        ws.close();
      }
      if (micStream) {
        micStream.getTracks().forEach(track => track.stop());
        micStream = null;
      }
      if (processorNode) {
        processorNode.disconnect();
        processorNode = null;
      }
      stopAllAgentAudio();

      document.getElementById("ws-status-dot").classList.remove("active");
      document.getElementById("ws-status-text").innerText = "Disconnected";
      document.getElementById("session-tag").innerText = "Session: Idle";
      document.getElementById("btn-call-text").innerText = "Start Patient Call";
      document.getElementById("btn-call").classList.remove("btn-danger");
      document.getElementById("btn-call").classList.add("btn-primary");
      document.getElementById("btn-agent-speak").disabled = true;
      document.getElementById("btn-mock-speech").disabled = true;
      document.getElementById("vad-badge").innerText = "VAD: SILENCE";
      document.getElementById("vad-badge").style.color = "var(--text-muted)";
      isCalling = false;
    }

    // Process Microphone Input: Resample to 8kHz & Encode 20ms mu-law Frames
    function setupMicProcessing() {
      const source = audioCtx.createMediaStreamSource(micStream);
      const bufferSize = 2048;
      processorNode = audioCtx.createScriptProcessor(bufferSize, 1, 1);

      // Accumulator for 8kHz samples
      let resampleBuffer = [];
      const targetSampleRate = 8000;
      const step = audioCtx.sampleRate / targetSampleRate;

      processorNode.onaudioprocess = (e) => {
        if (!isCalling || !ws || ws.readyState !== WebSocket.OPEN) return;

        const inputData = e.inputBuffer.getChannelData(0);

        // Calculate RMS for visual feedback
        let sumSq = 0;
        for (let i = 0; i < inputData.length; i++) {
          sumSq += inputData[i] * inputData[i];
        }
        const rms = Math.sqrt(sumSq / inputData.length);
        updateRMSMeter(rms);

        // Downsample to 8000Hz via linear decimation
        let currIdx = 0;
        while (currIdx < inputData.length) {
          const sample = inputData[Math.floor(currIdx)];
          // Convert float [-1.0, 1.0] to int16
          const pcmSample = Math.max(-32768, Math.min(32767, Math.floor(sample * 32767)));
          resampleBuffer.push(pcmSample);
          currIdx += step;
        }

        // Send 160-sample (20ms) frames
        while (resampleBuffer.length >= 160) {
          const chunk160 = resampleBuffer.slice(0, 160);
          resampleBuffer = resampleBuffer.slice(160);

          const muLawBytes = new Uint8Array(160);
          for (let i = 0; i < 160; i++) {
            muLawBytes[i] = linearToMuLaw(chunk160[i]);
          }

          // Convert to base64
          let binary = '';
          for (let i = 0; i < muLawBytes.byteLength; i++) {
            binary += String.fromCharCode(muLawBytes[i]);
          }
          const b64Payload = btoa(binary);

          frameSequence++;
          framesSent++;
          document.getElementById("metric-sent").innerText = framesSent;

          ws.send(JSON.stringify({
            event: "media",
            streamSid: streamSid,
            media: {
              payload: b64Payload,
              timestamp: String(frameSequence * 20)
            }
          }));
        }
      };

      source.connect(processorNode);
      processorNode.connect(audioCtx.destination);
    }

    // Handle Inbound Gateway WebSocket Messages
    function handleIncomingWSMessage(data) {
      try {
        const msg = JSON.parse(data);

        if (msg.event === "media" && msg.media && msg.media.payload) {
          framesRecv++;
          document.getElementById("metric-recv").innerText = framesRecv;
          document.getElementById("vad-badge").innerText = "AGENT SPEAKING";
          document.getElementById("vad-badge").style.color = "var(--emerald)";

          // Decode base64 -> mu-law -> Linear PCM float32 -> play seamlessly
          playMuLawPayload(msg.media.payload);
        } else if (msg.event === "clear") {
          // Destructive barge-in interrupt signal from gateway!
          bargeInCount++;
          document.getElementById("metric-barge").innerText = bargeInCount;
          document.getElementById("vad-badge").innerText = "⚡ BARGE-IN CUT";
          document.getElementById("vad-badge").style.color = "var(--rose)";

          logEvent("BARGE-IN", "tag-barge", "CLEAR signal received! Instantly purged agent audio buffer.");
          showBargeInAlert();
          stopAllAgentAudio();
        }
      } catch (err) {
        console.error("Error parsing message", err);
      }
    }

    // Playback 8kHz mu-law audio through AudioContext
    function playMuLawPayload(b64) {
      if (!audioCtx) return;

      const rawBinary = atob(b64);
      const len = rawBinary.length;
      const audioBuffer = audioCtx.createBuffer(1, len, 8000);
      const channelData = audioBuffer.getChannelData(0);

      for (let i = 0; i < len; i++) {
        const muByte = rawBinary.charCodeAt(i);
        const pcm16 = muLawToLinear(muByte);
        channelData[i] = pcm16 / 32768.0;
      }

      const source = audioCtx.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(audioCtx.destination);

      const currentTime = audioCtx.currentTime;
      if (nextPlayTime < currentTime) {
        nextPlayTime = currentTime + 0.02; // small 20ms lead
      }

      source.start(nextPlayTime);
      nextPlayTime += audioBuffer.duration;

      activeAudioSources.push(source);
      source.onended = () => {
        const idx = activeAudioSources.indexOf(source);
        if (idx !== -1) activeAudioSources.splice(idx, 1);
        if (activeAudioSources.length === 0 && isCalling) {
          document.getElementById("vad-badge").innerText = "VAD: SILENCE";
          document.getElementById("vad-badge").style.color = "var(--text-muted)";
        }
      };
    }

    // Instant Barge-In Audio Flush
    function stopAllAgentAudio() {
      for (let s of activeAudioSources) {
        try { s.stop(0); } catch (e) {}
      }
      activeAudioSources = [];
      nextPlayTime = 0;
    }

    function showBargeInAlert() {
      const banner = document.getElementById("barge-in-banner");
      banner.style.display = "flex";
      setTimeout(() => {
        banner.style.display = "none";
      }, 3500);
    }

    // Trigger Agent Speech Simulation
    async function triggerAgentSpeak() {
      if (!callSid) return;
      logEvent("ACTION", "tag-agent", "Triggering Agent Speech (TTS turn)...");
      try {
        const res = await fetch("/api/simulate-agent?call_id=" + encodeURIComponent(callSid), { method: "POST" });
        const json = await res.json();
        logEvent("AGENT", "tag-agent", "Agent queued 3.0s synthesized speech: " + json.message);
      } catch (err) {
        logEvent("ERROR", "tag-barge", "Failed to trigger agent: " + err.message);
      }
    }

    // Inject 500ms Synthetic Patient Burst (No-Mic Test)
    function sendMockSpeech() {
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      logEvent("BURST", "tag-vad", "Injecting 500ms patient speech burst to trigger VAD...");
      for (let f = 0; f < 25; f++) {
        setTimeout(() => {
          if (!ws || ws.readyState !== WebSocket.OPEN) return;
          const chunk = new Uint8Array(160);
          for (let s = 0; s < 160; s++) {
            // Loud speech tone
            const val = Math.sin(2 * Math.PI * 440 * (s / 8000.0));
            const pcm = Math.floor(val * 24000);
            chunk[s] = linearToMuLaw(pcm);
          }
          let binary = '';
          for (let i = 0; i < 160; i++) binary += String.fromCharCode(chunk[i]);
          ws.send(JSON.stringify({
            event: "media",
            streamSid: streamSid,
            media: {
              payload: btoa(binary),
              timestamp: String(Date.now())
            }
          }));
        }, f * 20);
      }
    }

    function updateRMSMeter(rms) {
      const pct = Math.min(100, Math.round(rms * 400));
      document.getElementById("rms-fill").style.width = pct + "%";
      document.getElementById("rms-label").innerText = pct + "%";
    }

    // Oscilloscope canvas animation
    const canvas = document.getElementById("waveform-canvas");
    const ctx = canvas.getContext("2d");
    let animPhase = 0;

    function renderWaveform() {
      canvas.width = canvas.parentElement.clientWidth;
      canvas.height = canvas.parentElement.clientHeight;

      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.lineWidth = 2;
      ctx.strokeStyle = isCalling ? "#06b6d4" : "#334155";
      ctx.beginPath();

      const sliceWidth = canvas.width / 80;
      let x = 0;
      for (let i = 0; i < 80; i++) {
        let v = 0;
        if (isCalling) {
          v = Math.sin((i * 0.15) + animPhase) * (activeAudioSources.length > 0 ? 30 : 10);
        }
        const y = (canvas.height / 2) + v;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
        x += sliceWidth;
      }
      ctx.stroke();

      animPhase += 0.08;
      requestAnimationFrame(renderWaveform);
    }
    renderWaveform();
  </script>
</body>
</html>
`
