// Realtime voice client: mic (16kHz PCM) -> /ws -> Gemini Live -> speaker (24kHz PCM).
// Usage: const vs = new VoiceSocket({onReady, onTranscript, onTurnComplete, onInterrupt, onError, onClose});
//        await vs.start(); vs.sendText("hi"); vs.stop();
(function () {
  const IN_RATE = 16000, OUT_RATE = 24000;

  const WORKLET = `
    class Tap extends AudioWorkletProcessor {
      process(inputs) { const c = inputs[0][0]; if (c) this.port.postMessage(c.slice(0)); return true; }
    }
    registerProcessor("tap", Tap);`;

  const b64encode = (bytes) => {
    let s = "";
    for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(s);
  };
  const b64decode = (str) => Uint8Array.from(atob(str), (c) => c.charCodeAt(0));

  function downsampleToInt16(f32, inRate) {
    const ratio = inRate / IN_RATE, n = Math.floor(f32.length / ratio), out = new Int16Array(n);
    for (let i = 0; i < n; i++) {
      const pos = i * ratio, i0 = Math.floor(pos), i1 = Math.min(i0 + 1, f32.length - 1), f = pos - i0;
      const v = Math.max(-1, Math.min(1, f32[i0] * (1 - f) + f32[i1] * f));
      out[i] = v < 0 ? v * 0x8000 : v * 0x7fff;
    }
    return out;
  }

  class VoiceSocket {
    constructor(handlers = {}, voice) {
      this.h = handlers;
      this.voice = voice;
      this.ws = null;
      this.ctx = null;
      this.stream = null;
      this.node = null;
      this.playTime = 0;
      this.sources = new Set();
      this.micOn = false;
    }

    static supported() {
      return !!(window.WebSocket && navigator.mediaDevices?.getUserMedia && window.AudioContext && window.AudioWorklet);
    }

    // Opens the socket and (unless micOff) the microphone. Resolves once Gemini is ready.
    async start({ mic = true } = {}) {
      this.ctx = new AudioContext();
      await this.ctx.resume();
      if (mic) {
        this.stream = await navigator.mediaDevices.getUserMedia({
          audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        });
      }
      const proto = location.protocol === "https:" ? "wss" : "ws";
      this.ws = new WebSocket(`${proto}://${location.host}/ws`);
      await new Promise((resolve, reject) => {
        this.ws.onopen = () => this.ws.send(JSON.stringify({ type: "config", voice: this.voice }));
        this.ws.onerror = () => reject(new Error("connection failed"));
        this.ws.onclose = () => reject(new Error("closed before ready"));
        this.ws.onmessage = (e) => {
          const m = JSON.parse(e.data);
          if (m.type === "ready") resolve();
          else if (m.type === "error") reject(new Error(m.message));
        };
      });
      this.ws.onerror = () => this.h.onError?.("Connection problem.");
      this.ws.onclose = () => { this._teardown(); this.h.onClose?.(); };
      this.ws.onmessage = (e) => this._onMessage(JSON.parse(e.data));
      if (this.stream) await this._startMic();
      this.h.onReady?.();
    }

    async _startMic() {
      const url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
      await this.ctx.audioWorklet.addModule(url);
      URL.revokeObjectURL(url);
      const src = this.ctx.createMediaStreamSource(this.stream);
      this.node = new AudioWorkletNode(this.ctx, "tap");
      this.node.port.onmessage = (e) => {
        if (!this.micOn || this.ws?.readyState !== WebSocket.OPEN) return;
        const pcm = downsampleToInt16(e.data, this.ctx.sampleRate);
        this.ws.send(JSON.stringify({ type: "audio", data: b64encode(new Uint8Array(pcm.buffer)) }));
      };
      src.connect(this.node); // not connected to destination, so no echo
      this.micOn = true;
    }

    setMic(on) { this.micOn = on; }

    sendText(text) {
      if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ type: "text", data: text }));
    }

    _onMessage(m) {
      if (m.type === "audio") this._play(m.data);
      else if (m.type === "transcript") this.h.onTranscript?.(m.role, m.text);
      else if (m.type === "turn_complete") this.h.onTurnComplete?.();
      else if (m.type === "interruption") { this.stopPlayback(); this.h.onInterrupt?.(); }
      else if (m.type === "error") this.h.onError?.(m.message);
    }

    _play(b64) {
      const bytes = b64decode(b64), pcm = new Int16Array(bytes.buffer, bytes.byteOffset, bytes.byteLength >> 1);
      const buf = this.ctx.createBuffer(1, pcm.length, OUT_RATE), ch = buf.getChannelData(0);
      for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 0x8000;
      const src = this.ctx.createBufferSource();
      src.buffer = buf;
      src.connect(this.ctx.destination);
      this.playTime = Math.max(this.playTime, this.ctx.currentTime + 0.03);
      src.start(this.playTime);
      this.playTime += buf.duration;
      this.sources.add(src);
      src.onended = () => { this.sources.delete(src); if (!this.sources.size) this.h.onPlaybackEnd?.(); };
      this.h.onPlaybackStart?.();
    }

    // Drops every queued/playing audio chunk (called on a Gemini "interruption" event).
    stopPlayback() {
      this.sources.forEach((s) => { s.onended = null; try { s.stop(); s.disconnect(); } catch (_) {} });
      this.sources.clear();
      this.playTime = 0;
    }

    isPlaying() { return this.sources.size > 0; }

    _teardown() {
      this.micOn = false;
      this.stopPlayback();
      this.node?.disconnect();
      this.stream?.getTracks().forEach((t) => t.stop());
      this.ctx?.close().catch(() => {});
      this.node = this.stream = this.ctx = null;
    }

    stop() {
      const ws = this.ws;
      this.ws = null;
      if (ws) { ws.onclose = null; ws.close(); }
      this._teardown();
    }
  }

  window.VoiceSocket = VoiceSocket;
})();
