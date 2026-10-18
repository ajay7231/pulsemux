'use strict';
const $ = id => document.getElementById(id);

// Energy VAD after browser noise suppression. This rejects steady room noise and
// short clicks; it is not a neural speech/noise classifier.
class TurnDetector {
  constructor() { this.reset(); }
  reset() {
    this.noise = 0.002; this.calibration = 25; this.attack = 0;
    this.speaking = false; this.silence = 0; this.duration = 0;
  }
  feed(rms) {
    if (this.calibration > 0) {
      this.noise = this.noise * 0.85 + rms * 0.15;
      this.calibration--;
      return 'calibrating';
    }
    const threshold = Math.max(0.009, this.noise * 2.8);
    const voiced = rms > threshold;
    if (!this.speaking) {
      if (!voiced) this.noise = this.noise * 0.98 + rms * 0.02;
      this.attack = voiced ? this.attack + 1 : Math.max(0, this.attack - 2);
      if (this.attack >= 6) {
        this.speaking = true; this.silence = 0; this.duration = 6;
        return 'start';
      }
    } else {
      this.duration++;
      this.silence = rms > threshold * 0.65 ? 0 : this.silence + 1;
      if (this.silence >= 40 || this.duration >= 1000) {
        this.speaking = false; this.attack = 0;
        return 'end';
      }
    }
    return this.speaking ? 'speech' : 'silence';
  }
}
function linearToMuLaw(value) {
  let pcm = Math.round(Math.max(-1, Math.min(1, value)) * 32767);
  const sign = pcm < 0 ? 0x80 : 0;
  pcm = Math.min(32635, Math.abs(pcm)) + 132;
  let exponent = 7;
  for (let mask = 0x4000; exponent > 0 && !(pcm & mask); mask >>= 1) exponent--;
  return (~(sign | (exponent << 4) | ((pcm >> (exponent + 3)) & 15))) & 255;
}
let ws = null, stream = null, context = null, capture = null;
let calling = false, starting = false, muted = false, endingCall = false, turnId = null;
let hangupTimer = null;
let detector = new TurnDetector(), sequence = 0, streamSid = null, callSid = null;
let startedAt = 0, timer = null, playbackEpoch = 0, playbackChain = Promise.resolve();
let sources = new Set(), assistantMessage = null, responseText = '', receivedAudio = false;
let fallbackSpeech = false, generating = false, frames = 0, ttsWarning = '';
const newId = () => crypto.randomUUID();
const send = msg => { if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg)); };
function notice(text) { $('call-notice').textContent = text; }
function status(title, description) {
  $('status-title').textContent = title;
  if (description) $('status-desc').textContent = description;
}
function renderState() {
  const speaking = sources.size > 0 || speechSynthesis.speaking;
  $('orb-core').className = 'orb' + (speaking ? ' orb-state-speaking' : calling && detector.speaking ? ' orb-state-listening' : '');
  if (!calling) return;
  if (endingCall) status('Ending call…', 'The call will disconnect after the goodbye.');
  else if (muted) status('Microphone muted', 'Unmute whenever you are ready to speak.');
  else if (detector.calibration > 0) status('Adjusting to your room…', 'Keep quiet for a moment while we measure background noise.');
  else if (detector.speaking) status('Listening to you', 'Pause naturally when you finish.');
  else if (speaking) status('Assistant speaking', 'You can interrupt by speaking at any time.');
  else if (generating) status('Assistant is thinking…', 'Your microphone stays open.');
  else status('Listening', 'Speak naturally. Pauses send your turn automatically.');
}
function stopPlayback() {
  playbackEpoch++;
  for (const source of sources) { try { source.stop(); } catch {} }
  sources.clear(); speechSynthesis.cancel();
  playbackChain = Promise.resolve();
  assistantMessage = null; generating = false;
}
function beginTurn() {
  stopPlayback(); turnId = newId(); responseText = ''; receivedAudio = false;
  fallbackSpeech = false;
}
function appendMessage(speaker, text) {
  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble ' + (speaker === 'You' ? 'msg-patient' : 'msg-ai');
  const author = document.createElement('div');
  author.className = 'msg-author ' + (speaker === 'You' ? 'author-patient' : 'author-ai');
  author.textContent = speaker;
  const body = document.createElement('div'); body.className = 'msg-body'; body.textContent = text;
  bubble.append(author, body); $('messages-container').append(bubble);
  $('messages-container').scrollTop = $('messages-container').scrollHeight;
  return body;
}
function queueAudio(base64) {
  receivedAudio = true;
  const epoch = playbackEpoch;
  playbackChain = playbackChain.then(async () => {
    if (!calling || epoch !== playbackEpoch) return;
    const bytes = Uint8Array.from(atob(base64), c => c.charCodeAt(0));
    const buffer = await context.decodeAudioData(bytes.buffer);
    if (!calling || epoch !== playbackEpoch) return;
    await new Promise(resolve => {
      const source = context.createBufferSource(); source.buffer = buffer;
      // Telephone bandwidth for the agent side too.
      const lowpass = context.createBiquadFilter(); lowpass.type = 'lowpass'; lowpass.frequency.value = 3400;
      source.connect(lowpass).connect(context.destination);
      sources.add(source); renderState();
      source.onended = () => { sources.delete(source); lowpass.disconnect(); resolve(); renderState(); };
      source.start();
    });
  }).catch(() => { notice('Audio playback failed. The response is available in the transcript.'); });
}
function markCallEnding() {
  endingCall = true;
  generating = false;
  notice('');
  // Ignore microphone noise/echo while draining the farewell audio.
  detector.reset();
  $('mic-level').style.width = '0%';
  $('user-text-input').disabled = true;
  $('btn-send').disabled = true;
  $('btn-mute').disabled = true;
  renderState();
  // A missing browser audio callback must not keep the microphone open forever.
  if (hangupTimer === null) hangupTimer = setTimeout(() => { if (endingCall) endCall(); }, 60000);
}
function finishCallAfterPlayback(completedTurn, browserPlayback = Promise.resolve()) {
  markCallEnding();
  Promise.all([playbackChain, browserPlayback]).finally(() => {
    if (calling && endingCall && turnId === completedTurn) endCall();
  });
}
function speakBrowserResponse(text) {
  return new Promise(resolve => {
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.onstart = renderState;
    utterance.onend = utterance.onerror = () => { resolve(); renderState(); };
    try { speechSynthesis.speak(utterance); } catch { resolve(); }
  });
}
function handleMessage(msg) {
  if (msg.type === 'connected') return;
  if (!calling) return;
  if (msg.turn_id && msg.turn_id !== turnId) return;
  switch (msg.type) {
    case 'transcript': appendMessage('You', msg.text); generating = true; break;
    case 'token':
      if (!assistantMessage) assistantMessage = appendMessage('PulseMux assistant', '');
      responseText += msg.delta; assistantMessage.textContent += msg.delta;
      $('messages-container').scrollTop = $('messages-container').scrollHeight; break;
    case 'audio_clause':
      if (msg.tts_ms) $('hud-tts').textContent = `${msg.tts_ms} ms`;
      queueAudio(msg.audio_b64); break;
    case 'tts_warning': ttsWarning = msg.message; notice(msg.message); $('hud-tts-label').textContent = 'Fallback TTS'; break;
    case 'audio_unavailable': fallbackSpeech = true; break;
    case 'call_ending': markCallEnding(); break;
    case 'turn_complete': {
      let browserPlayback = Promise.resolve();
      generating = false; assistantMessage = null;
      $('hud-total').textContent = `${msg.total_turn_ms} ms`;
      if (fallbackSpeech && !receivedAudio && responseText) {
        notice(ttsWarning || 'Selected TTS is unavailable. Using your browser voice for this call.');
        $('hud-tts-label').textContent = 'Browser TTS';
        browserPlayback = speakBrowserResponse(responseText);
      }
      if (msg.end_call) finishCallAfterPlayback(msg.turn_id, browserPlayback);
      break;
    }
    case 'triage_status':
      $('triage-badge').className = 'triage-indicator ' + (msg.is_emergency ? 'triage-emergency' : 'triage-routine');
      $('triage-label').textContent = msg.is_emergency ? 'CLINICAL TRIAGE: EMERGENCY' : 'CLINICAL TRIAGE: ROUTINE'; break;
    case 'telemetry_stt': $('hud-stt').textContent = `${msg.latency_ms} ms`; break;
    case 'telemetry_ttft': $('hud-ttft').textContent = `${msg.ttft_ms} ms`; break;
    case 'stt_empty': case 'error': generating = false; notice(msg.message); break;
    // An interrupt acknowledgement never sends another interrupt.
    case 'interrupted': break;
  }
  renderState();
}
async function connect() {
  const socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/voice`);
  ws = socket;
  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => { socket.close(); reject(new Error('The voice server did not respond.')); }, 8000);
    socket.onopen = () => { clearTimeout(timeout); resolve(); };
    socket.onerror = () => { clearTimeout(timeout); reject(new Error('Cannot connect to the voice server.')); };
    socket.onclose = () => {
      clearTimeout(timeout); reject(new Error('Voice connection closed.'));
      if (calling) { endCall(); notice('Connection lost. Start a new call to reconnect.'); }
    };
    socket.onmessage = e => handleMessage(JSON.parse(e.data));
  });
}
function updateConfig() {
  const voice = $('select-voice').value;
  ttsWarning = '';
  $('hud-tts-label').textContent = voice.startsWith('aura-2-') ? 'Deepgram TTS' : 'Kokoro TTS';
  send({type: 'config', stt_engine: $('select-stt').value, voice_id: voice});
}
async function toggleCall() {
  if (starting) return;
  if (calling) { endCall(); return; }
  starting = true; $('btn-record').disabled = true; notice('');
  try {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('Microphone access requires localhost or HTTPS.');
    context = new AudioContext(); await context.resume();
    stream = await navigator.mediaDevices.getUserMedia({audio: {
      channelCount: 1, echoCancellation: true,
      noiseSuppression: $('noise-suppression').checked, autoGainControl: true
    }});
    const track = stream.getAudioTracks()[0];
    track.onended = () => { if (calling) { endCall(); notice('Microphone disconnected.'); } };
    const settings = track.getSettings();
    $('noise-status').textContent = settings.noiseSuppression === true ? 'Noise suppression active' : settings.noiseSuppression === false ? 'Noise suppression off · adaptive gate active' : 'Adaptive noise gate active';
    await context.audioWorklet.addModule('/static/mic-worklet.js');
    await connect();
    calling = true; muted = false; endingCall = false; frames = 0; sequence = 1;
    detector.reset(); beginTurn();
    streamSid = 'MZ' + newId().replaceAll('-', ''); callSid = 'CA' + newId().replaceAll('-', '');
    $('messages-container').replaceChildren();
    for (const id of ['hud-stt', 'hud-ttft', 'hud-tts', 'hud-total']) $(id).textContent = '— ms';
    $('triage-badge').className = 'triage-indicator triage-routine';
    $('triage-label').textContent = 'CLINICAL TRIAGE STANDBY';
    updateConfig();
    send({event: 'connected', protocol: 'Call', version: '1.0.0'});
    send({event: 'start', sequenceNumber: String(sequence++), streamSid,
      turn_id: turnId, start: {streamSid, callSid, accountSid: 'AC_BROWSER_SIMULATOR', tracks: ['inbound'],
        mediaFormat: {encoding: 'audio/x-mulaw', sampleRate: 8000, channels: 1}}});
    const source = context.createMediaStreamSource(stream);
    const highpass = context.createBiquadFilter(); highpass.type = 'highpass'; highpass.frequency.value = 100;
    const lowpass = context.createBiquadFilter(); lowpass.type = 'lowpass'; lowpass.frequency.value = 3400; lowpass.Q.value = 0.707;
    capture = new AudioWorkletNode(context, 'call-microphone');
    const silence = context.createGain(); silence.gain.value = 0;
    source.connect(highpass).connect(lowpass).connect(capture).connect(silence).connect(context.destination);
    capture.port.onmessage = e => processFrame(e.data);
    startedAt = Date.now(); timer = setInterval(updateClock, 1000); updateClock();
    $('btn-record').classList.add('recording'); $('btn-record-text').textContent = 'End call';
    $('btn-mute').disabled = false; $('btn-mute').textContent = 'Mute mic'; $('btn-mute').setAttribute('aria-pressed', 'false');
    $('user-text-input').disabled = false; $('btn-send').disabled = false;
    $('select-stt').disabled = true; $('select-voice').disabled = true;
    $('noise-suppression').disabled = true;
    $('connection-status').textContent = 'CALL CONNECTED';
    $('connection-status').style.color = 'var(--emerald)';
    renderState();
  } catch (error) {
    endCall(); notice(error.name === 'NotAllowedError' ? 'Microphone permission was denied. Allow access and start the call again.' : error.message);
  } finally { starting = false; $('btn-record').disabled = false; }
}
function processFrame(frame) {
  if (!calling || muted || endingCall) return;
  if (ws?.readyState !== WebSocket.OPEN || ws.bufferedAmount > 256000) {
    endCall(); notice('The audio connection is too slow. Start a new call.'); return;
  }
  const rms = Math.sqrt(frame.reduce((sum, value) => sum + value * value, 0) / frame.length);
  const event = detector.feed(rms);
  $('mic-level').style.width = `${Math.min(100, rms * 600)}%`;
  $('noise-level').textContent = `${Math.round(20 * Math.log10(Math.max(detector.noise, 0.00001)))} dB`;
  if (event === 'start') { beginTurn(); send({type: 'speech_start', turn_id: turnId}); }
  let binary = '';
  for (const value of frame) binary += String.fromCharCode(linearToMuLaw(value));
  send({event: 'media', sequenceNumber: String(sequence++), streamSid,
    media: {track: 'inbound', chunk: String(++frames), timestamp: String((frames - 1) * 20), payload: btoa(binary)}});
  if (event === 'end') {
    generating = true; send({type: 'speech_end', turn_id: turnId});
  }
  renderState();
}
function updateClock() {
  const seconds = Math.floor((Date.now() - startedAt) / 1000);
  $('call-duration').textContent = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
}
function endCall() {
  const wasCalling = calling; calling = false; endingCall = false; turnId = null;
  clearTimeout(hangupTimer); hangupTimer = null;
  stopPlayback(); clearInterval(timer);
  if (wasCalling) send({event: 'stop', streamSid, stop: {callSid}});
  if (ws) { ws.onclose = null; ws.close(); ws = null; }
  if (capture) { capture.port.onmessage = null; capture.disconnect(); capture = null; }
  if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
  if (context) { context.close().catch(() => {}); context = null; }
  $('btn-record').classList.remove('recording'); $('btn-record-text').textContent = 'Start call';
  $('btn-mute').disabled = true; $('user-text-input').disabled = true; $('btn-send').disabled = true;
  $('select-stt').disabled = false; $('select-voice').disabled = false; $('noise-suppression').disabled = false;
  $('connection-status').textContent = 'CALL OFFLINE'; $('connection-status').style.color = 'var(--text-muted)';
  $('noise-status').textContent = 'Microphone off'; $('mic-level').style.width = '0%';
  $('orb-core').className = 'orb';
  status(wasCalling ? 'Call ended' : 'Ready when you are', 'Start a call, then talk naturally. No need to press anything between turns.');
}
function toggleMute() {
  if (!calling || endingCall) return;
  muted = !muted;
  $('btn-mute').setAttribute('aria-pressed', String(muted));
  if (muted && detector.speaking) { send({type: 'speech_end', turn_id: turnId}); generating = true; }
  stream.getAudioTracks().forEach(t => { t.enabled = !muted; });
  detector.reset();
  $('btn-mute').textContent = muted ? 'Unmute mic' : 'Mute mic';
  $('btn-mute').setAttribute('aria-pressed', String(muted));
  $('mic-level').style.width = '0%'; renderState();
}
function sendTextMessage() {
  if (!calling || endingCall) return;
  const text = $('user-text-input').value.trim(); if (!text) return;
  beginTurn(); detector.reset(); generating = true;
  send({type: 'user_text', text, turn_id: turnId}); $('user-text-input').value = ''; renderState();
}
function handleKey(e) { if (e.key === 'Enter') sendTextMessage(); }
window.addEventListener('pagehide', endCall);
