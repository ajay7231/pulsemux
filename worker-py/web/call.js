'use strict';

// Energy VAD after browser noise suppression. This rejects steady room noise and
// short clicks; it is not a neural speech/noise classifier.
class TurnDetector {
  constructor() { this.reset(); }
  reset() {
    this.pauseFrames = this.pauseFrames || 40;
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
      if (this.silence >= this.pauseFrames || this.duration >= 1000) {
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
export function createCallSimulator(root = document, options = {}) {
const $ = id => root === document ? document.getElementById(id) : root.querySelector(`[data-call="${id}"]`);
let disposed = false, generation = 0;
let ws = null, stream = null, context = null, capture = null;
let calling = false, starting = false, muted = false, endingCall = false, turnId = null;
let hangupTimer = null;
let callAcknowledged = false;
let detector = new TurnDetector(), sequence = 0, streamSid = null, callSid = null;
let startedAt = 0, timer = null, playbackEpoch = 0, playbackChain = Promise.resolve();
let sources = new Set(), assistantMessage = null, responseText = '', receivedAudio = false;
let fallbackSpeech = false, generating = false, frames = 0, ttsWarning = '';
let semanticTurns = false, pendingSpeech = false;
let recognizing = false, reconnectAvailable = false, noiseStatus = '', connectionStage = '';
let cancelConnect = null;
let measurement = null, measurements = [];
const monotonic = () => globalThis.performance?.now() ?? Date.now();
function recordBoundary(name) {
  if (measurement && measurement[name] === undefined) measurement[name] = monotonic();
}
function recordPlayback(row, provider) {
  if (!row || row.playback_at !== undefined) return;
  row.playback_at = monotonic(); row.playback_provider = provider;
  const speech = $('hud-speech-playback'), commit = $('hud-commit-playback');
  if (speech && row.speech_end_at !== undefined) speech.textContent = `${Math.round(row.playback_at - row.speech_end_at)} ms`;
  if (commit && row.commit_notice_at !== undefined) commit.textContent = `${Math.round(row.playback_at - row.commit_notice_at)} ms`;
}
function getMeasurements() {
  return {schema_version: 1, clock: 'browser monotonic',
    definitions: {speech_end_to_playback_ms: 'Last locally voiced frame to AudioBufferSource.start or browser speech onstart; includes VAD wait and decode.',
      commit_notice_to_playback_ms: 'Commit reference to local playback start; see per-row commit_origin. Server notices exclude notification transit time.',
      speech_end_to_first_text_ms: 'Last locally voiced frame to first response content received.'},
    limitations: ['Playback API start is not a measurement of acoustic speaker output or carrier delivery.',
      'No microphone audio, transcript, patient data, provider keys or agent configuration is exported.',
      'Continue/interrupted/empty/error turns are retained; missing measurements remain null.'],
    settings: {semantic_turns: semanticTurns, stt_engine: $('select-stt').value, voice_id: $('select-voice').value},
    rows: measurements.map(row => {
      const elapsed = (end, start) => row[end] !== undefined && row[start] !== undefined ? Math.round((row[end] - row[start]) * 10) / 10 : null;
      return {turn_id: row.turn_id, kind: row.kind, outcome: row.outcome,
        commit_origin: row.commit_origin || null,
        playback_provider: row.playback_provider || null,
        speech_end_to_commit_notice_ms: elapsed('commit_notice_at', 'speech_end_at'),
        speech_end_to_first_text_ms: elapsed('text_at', 'speech_end_at'),
        speech_end_to_playback_ms: elapsed('playback_at', 'speech_end_at'),
        commit_notice_to_playback_ms: elapsed('playback_at', 'commit_notice_at')};
    })};
}
function downloadMeasurements() {
  const url = URL.createObjectURL(new Blob([JSON.stringify(getMeasurements(), null, 2)], {type: 'application/json'}));
  const link = document.createElement('a'); link.href = url; link.download = 'pulsemux-call-timings.json';
  link.click(); setTimeout(() => URL.revokeObjectURL(url), 0);
}
const newId = () => crypto.randomUUID();
const send = msg => { if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg)); };
function notice(text) { $('call-notice').textContent = text; }
function status(title, description) {
  if ($('status-title').textContent !== title) $('status-title').textContent = title;
  if (description && $('status-desc').textContent !== description) $('status-desc').textContent = description;
}
function showInterim(text = '') {
  const preview = $('interim-container'), body = $('interim-text');
  if (!preview || !body) return;
  body.textContent = text;
  preview.hidden = !text;
}
function renderState() {
  const speaking = sources.size > 0 || globalThis.speechSynthesis?.speaking;
  $('orb-core').className = 'orb' + (speaking ? ' orb-state-speaking' : calling && detector.speaking ? ' orb-state-listening' : '');
  if (starting && !calling) {
    status(connectionStage === 'microphone' ? 'Checking microphone…' : reconnectAvailable ? 'Reconnecting…' : 'Connecting…',
      connectionStage === 'microphone' ? 'Allow microphone access to start your test.' : 'Starting a new test call.');
    return;
  }
  if (!calling) return;
  if (endingCall) status('Ending call…', 'The call will disconnect after the goodbye.');
  else if (!callAcknowledged) status(reconnectAvailable ? 'Reconnecting…' : 'Connecting to agent…', 'Waiting for the call server.');
  else if (muted) status('Microphone muted', 'Unmute whenever you are ready to speak.');
  else if (detector.calibration > 0) status('Adjusting to your room…', 'Keep quiet for a moment while we measure background noise.');
  else if (detector.speaking) status('Listening to you', 'Pause naturally when you finish.');
  else if (speaking) status('Assistant speaking', 'You can interrupt by speaking at any time.');
  else if (recognizing) status('Transcribing…', 'Finishing speech recognition. Your microphone stays open.');
  else if (generating) status('Assistant is thinking…', 'Your microphone stays open.');
  else status('Listening', 'Speak naturally. Pauses send your turn automatically.');
}
function stopPlayback() {
  playbackEpoch++;
  for (const source of sources) { try { source.stop(); } catch {} }
  sources.clear(); globalThis.speechSynthesis?.cancel();
  playbackChain = Promise.resolve();
  assistantMessage = null; generating = false; recognizing = false;
}
function beginTurn() {
  if (measurement?.outcome === 'pending') measurement.outcome = pendingSpeech ? 'continued' : 'interrupted';
  stopPlayback(); turnId = newId(); responseText = ''; receivedAudio = false;
  measurement = {turn_id: turnId, kind: 'speech', outcome: 'pending'};
  measurements.push(measurement); if (measurements.length > 1000) measurements.shift();
  if ($('btn-export')) $('btn-export').disabled = false;
  fallbackSpeech = false; pendingSpeech = false;
  showInterim();
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
  const row = measurement;
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
      source.start(); recordPlayback(row, 'selected_tts');
    });
  }).catch(() => { notice('Audio playback failed. The response is available in the transcript.'); });
}
function markCallEnding() {
  endingCall = true;
  generating = false;
  recognizing = false; pendingSpeech = false; showInterim();
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
  const row = measurement;
  return new Promise(resolve => {
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.onstart = () => { recordPlayback(row, 'browser_fallback'); renderState(); };
    utterance.onend = utterance.onerror = () => { resolve(); renderState(); };
    try { speechSynthesis.speak(utterance); } catch { resolve(); }
  });
}
function handleMessage(msg) {
  if (msg.type === 'connected') return;
  if (!calling) return;
  if (msg.turn_id && msg.turn_id !== turnId) return;
  switch (msg.type) {
    case 'call_started':
      callAcknowledged = true;
      reconnectAvailable = false; generating = true;
      $('connection-status').textContent = 'CALL CONNECTED';
      $('connection-status').style.color = 'var(--emerald)';
      semanticTurns = msg.turn_detection?.semantic === true;
      if (msg.settings) detector.pauseFrames = Math.ceil((msg.turn_detection?.candidate_pause_ms || msg.settings.end_pause_ms) / 20);
      break;
    case 'turn_committed':
      if (measurement) measurement.commit_origin = 'server_notice';
      recordBoundary('commit_notice_at');
      pendingSpeech = false; recognizing = true; generating = false;
      if (msg.forced) { detector.speaking = false; detector.attack = 0; }
      break;
    case 'call_ended':
      endCall({connectionLost: msg.reason === 'recognition_failure'}); if (msg.message) notice(msg.message); return;
    case 'transcript_interim':
      if (!muted && !endingCall) showInterim(msg.text);
      break;
    case 'transcript': showInterim(); recognizing = false; pendingSpeech = false; notice(''); appendMessage('You', msg.text); generating = true; break;
    case 'token':
      recordBoundary('text_at');
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
      if (measurement) measurement.outcome = 'generation_completed';
      let browserPlayback = Promise.resolve();
      generating = false; recognizing = false; assistantMessage = null;
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
    case 'stt_empty': case 'error':
      if (measurement) measurement.outcome = msg.type;
      generating = false; recognizing = false; pendingSpeech = false; showInterim();
      if (msg.type === 'error' && !callAcknowledged) endCall();
      notice(msg.message); break;
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
    cancelConnect = () => { clearTimeout(timeout); reject(new Error('Call cancelled.')); };
    socket.onopen = () => { clearTimeout(timeout); resolve(); };
    socket.onerror = () => { clearTimeout(timeout); reject(new Error('Cannot connect to the voice server.')); };
    socket.onclose = (event) => {
      clearTimeout(timeout); reject(new Error('Voice connection closed.'));
      if (ws !== socket) return;
      if (calling) { endCall({connectionLost: ![4401, 4403].includes(event.code)}); notice([4401, 4403].includes(event.code) ? 'Sign in to your workspace and open the agent test again.' : 'Connection lost. Reconnect to start a new test call.'); }
    };
    socket.onmessage = e => { if (ws === socket && !disposed) handleMessage(JSON.parse(e.data)); };
  });
  cancelConnect = null;
}
function updateConfig() {
  const voice = $('select-voice').value;
  ttsWarning = '';
  $('hud-tts-label').textContent = voice.startsWith('aura-2-') ? 'Deepgram TTS' : 'Kokoro TTS';
  send({type: 'config', stt_engine: $('select-stt').value, voice_id: voice});
}
async function toggleCall() {
  if (!options.agent?.id) { notice('Open an agent from the dashboard to test it.'); return; }
  if (starting || disposed) return;
  if (calling) { endCall(); return; }
  const attempt = ++generation;
  starting = true; connectionStage = 'microphone'; $('btn-record').disabled = true; notice(''); showInterim(); renderState();
  try {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('Microphone access requires localhost or HTTPS.');
    const audioContext = new AudioContext(); context = audioContext; await audioContext.resume();
    if (disposed || attempt !== generation) return;
    const microphone = await navigator.mediaDevices.getUserMedia({audio: {
      channelCount: 1, echoCancellation: true,
      noiseSuppression: $('noise-suppression').checked, autoGainControl: true
    }});
    if (disposed || attempt !== generation) {
      microphone.getTracks().forEach(track => track.stop());
      await audioContext.close().catch(() => {});
      return;
    }
    stream = microphone;
    const track = stream.getAudioTracks()[0];
    track.onended = () => { if (calling) { endCall(); notice('Microphone disconnected.'); } };
    const settings = track.getSettings();
    noiseStatus = settings.noiseSuppression === true ? 'Noise suppression active' : settings.noiseSuppression === false ? 'Noise suppression off · adaptive gate active' : 'Adaptive noise gate active';
    $('noise-status').textContent = noiseStatus;
    await context.audioWorklet.addModule('/static/mic-worklet.js');
    if (disposed || attempt !== generation) return;
    connectionStage = 'socket'; renderState();
    await connect();
    if (disposed || attempt !== generation) return;
    calling = true; muted = false; endingCall = false; callAcknowledged = false; frames = 0; sequence = 1;
    semanticTurns = false; pendingSpeech = false; detector.pauseFrames = 40;
    measurements = []; measurement = null;
    detector.reset(); beginTurn(); measurement.kind = 'greeting';
    streamSid = 'MZ' + newId().replaceAll('-', ''); callSid = 'CA' + newId().replaceAll('-', '');
    $('messages-container').replaceChildren();
    for (const id of ['hud-stt', 'hud-ttft', 'hud-tts', 'hud-total', 'hud-speech-playback', 'hud-commit-playback']) if ($(id)) $(id).textContent = '— ms';
    $('triage-badge').className = 'triage-indicator triage-routine';
    $('triage-label').textContent = 'CLINICAL TRIAGE STANDBY';
    updateConfig();
    send({event: 'connected', protocol: 'Call', version: '1.0.0'});
    send({event: 'start', agent_id: options.agent.id, draft: options.draft !== false, sequenceNumber: String(sequence++), streamSid,
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
    $('connection-status').textContent = 'CALL CONNECTING';
    $('connection-status').style.color = 'var(--text-muted)';
    renderState();
  } catch (error) {
    if (disposed || attempt !== generation) return;
    endCall({connectionLost: connectionStage === 'socket'}); notice(error.name === 'NotAllowedError' ? 'Microphone permission was denied. Allow access and start the call again.' : error.message);
  } finally { starting = false; $('btn-record').disabled = false; }
}
function processFrame(frame) {
  if (!calling || !callAcknowledged || muted || endingCall) return;
  if (ws?.readyState !== WebSocket.OPEN || ws.bufferedAmount > 256000) {
    endCall({connectionLost: true}); notice('The audio connection is too slow. Reconnect to start a new test call.'); return;
  }
  const rms = Math.sqrt(frame.reduce((sum, value) => sum + value * value, 0) / frame.length);
  const event = detector.feed(rms);
  $('mic-level').style.width = `${Math.min(100, rms * 600)}%`;
  $('noise-level').textContent = `${Math.round(20 * Math.log10(Math.max(detector.noise, 0.00001)))} dB`;
  if (event === 'start') { beginTurn(); send({type: 'speech_start', turn_id: turnId}); }
  if (measurement && (detector.speaking || event === 'end') && detector.silence === 0) measurement.speech_end_at = monotonic();
  let binary = '';
  for (const value of frame) binary += String.fromCharCode(linearToMuLaw(value));
  send({event: 'media', sequenceNumber: String(sequence++), streamSid,
    media: {track: 'inbound', chunk: String(++frames), timestamp: String((frames - 1) * 20), payload: btoa(binary)}});
  if (event === 'end') {
    if (!semanticTurns) { recordBoundary('commit_notice_at'); if (measurement) measurement.commit_origin = 'local_fixed_boundary'; }
    pendingSpeech = semanticTurns; recognizing = !semanticTurns; generating = false;
    send({type: 'speech_end', turn_id: turnId, pause_ms: detector.silence * 20, force: detector.duration >= 1000});
  }
  renderState();
}
function updateClock() {
  const seconds = Math.floor((Date.now() - startedAt) / 1000);
  $('call-duration').textContent = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
}
function endCall({connectionLost = false} = {}) {
  if (measurement?.outcome === 'pending') measurement.outcome = connectionLost ? 'disconnected' : 'stopped';
  generation++;
  const wasCalling = calling; calling = false; endingCall = false; turnId = null;
  clearTimeout(hangupTimer); hangupTimer = null;
  stopPlayback(); clearInterval(timer);
  cancelConnect?.(); cancelConnect = null;
  recognizing = false; pendingSpeech = false; showInterim();
  reconnectAvailable = connectionLost;
  if (wasCalling) send({event: 'stop', streamSid, stop: {callSid}});
  if (ws) { ws.onclose = null; ws.onmessage = null; ws.onerror = null; ws.onopen = null; ws.close(); ws = null; }
  if (capture) { capture.port.onmessage = null; capture.disconnect(); capture = null; }
  if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
  if (context) { context.close().catch(() => {}); context = null; }
  $('btn-record').classList.remove('recording'); $('btn-record-text').textContent = connectionLost ? 'Reconnect' : 'Start call';
  $('btn-mute').disabled = true; $('user-text-input').disabled = true; $('btn-send').disabled = true;
  const managed = !!options.agent;
  $('select-stt').disabled = managed; $('select-voice').disabled = managed; $('noise-suppression').disabled = false;
  $('connection-status').textContent = 'CALL OFFLINE'; $('connection-status').style.color = 'var(--text-muted)';
  $('noise-status').textContent = 'Microphone off'; $('mic-level').style.width = '0%';
  $('orb-core').className = 'orb';
  status(connectionLost ? 'Disconnected' : wasCalling ? 'Call ended' : 'Ready when you are', connectionLost ? 'Reconnect to start a new test call.' : 'Start a call, then talk naturally. No need to press anything between turns.');
}
function toggleMute() {
  if (!calling || endingCall) return;
  muted = !muted;
  $('btn-mute').setAttribute('aria-pressed', String(muted));
  if (muted && (detector.speaking || pendingSpeech)) {
    send({type: 'speech_end', turn_id: turnId, pause_ms: 0, force: true});
    pendingSpeech = false; recognizing = true; generating = false;
  }
  showInterim();
  stream.getAudioTracks().forEach(t => { t.enabled = !muted; });
  detector.reset();
  $('btn-mute').textContent = muted ? 'Unmute mic' : 'Mute mic';
  $('btn-mute').setAttribute('aria-pressed', String(muted));
  $('mic-level').style.width = '0%'; renderState();
  $('noise-status').textContent = muted ? 'Microphone muted' : noiseStatus;
  $('noise-level').textContent = '— dB';
}
function sendTextMessage() {
  if (!calling || endingCall) return;
  const text = $('user-text-input').value.trim(); if (!text) return;
  beginTurn(); detector.reset(); generating = true;
  measurement.kind = 'typed'; recordBoundary('commit_notice_at');
  measurement.commit_origin = 'typed_submit';
  send({type: 'user_text', text, turn_id: turnId}); $('user-text-input').value = ''; renderState();
}
function handleKey(e) { if (e.key === 'Enter') sendTextMessage(); }
// Controller lifecycle: shared by the dashboard and the standalone simulator.
window.addEventListener('pagehide', endCall);
if (options.agent) {
  $('select-stt').value = options.agent.config.stt_engine;
  $('select-voice').value = options.agent.config.voice_id;
  $('select-stt').disabled = true; $('select-voice').disabled = true;
}
return {
  toggleCall, toggleMute, sendTextMessage, handleKey, getMeasurements, downloadMeasurements,
  destroy() {
    disposed = true;
    endCall();
    window.removeEventListener('pagehide', endCall);
  }
};
}
