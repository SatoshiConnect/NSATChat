import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowDown, Camera, Gift, Heart, Mic, MicOff, Radio, Send, Share2, Sparkles, UserPlus, Video, VideoOff, Volume2, VolumeX, WalletCards, X } from "lucide-react";
import { API_BASE, errorMessage, tokens } from "../../api/client";
import { callApi, marketplaceApi, socialApi } from "../../api/endpoints";
import { walletApi } from "../../features/wallet/api";
import { toast } from "../../services/toast";
import { Avatar, Spinner } from "../common/ui";
import { useApp } from "../layout/AppContext";
import "../../styles/social-live.css";

const STICKERS = [
  ["sparkles", "✨", "Sparkles"], ["heart", "❤️", "Heart"], ["laugh", "😂", "Laugh"],
  ["clap", "👏", "Clap"], ["fire", "🔥", "Fire"], ["thumbs-up", "👍", "Thumbs up"],
  ["hug", "🤗", "Hug"], ["party", "🎉", "Party"],
];
const REACTIONS = ["❤️", "👍", "😂", "😮", "🔥", "👏"];

function socketUrl(streamId) {
  const base = new URL(API_BASE, window.location.href);
  const url = new URL(`/ws/social/live/${streamId}/`, base.origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

export default function LiveRoom({ mode, stream: initialStream = null, me, onClose }) {
  const app = useApp();
  const [stream, setStream] = useState(initialStream);
  const [localStream, setLocalStream] = useState(null);
  const [remoteStream, setRemoteStream] = useState(null);
  const [cameraReady, setCameraReady] = useState(false);
  const [cameraOff, setCameraOff] = useState(false);
  const [muted, setMuted] = useState(false);
  const [audioEnabled, setAudioEnabled] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [viewerCount, setViewerCount] = useState(initialStream?.viewer_count || 0);
  const [events, setEvents] = useState(initialStream?.events || []);
  const [draft, setDraft] = useState("");
  const [showGifts, setShowGifts] = useState(false);
  const [ownedStickers, setOwnedStickers] = useState([]);
  const [giftLoading, setGiftLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [following, setFollowing] = useState(false);
  const [followBusy, setFollowBusy] = useState(false);
  const [floating, setFloating] = useState([]);
  const [warning, setWarning] = useState("");
  const videoRef = useRef(null);
  const socketRef = useRef(null);
  const streamRef = useRef(null);
  const peersRef = useRef(new Map());
  const pendingIceRef = useRef(new Map());
  const iceServersRef = useRef([{ urls: ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"] }]);
  const endingRef = useRef(false);
  const ownedStickersLoadedRef = useRef(false);
  const hostMode = mode === "host";

  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.srcObject = hostMode ? localStream : remoteStream;
      if (videoRef.current.srcObject) videoRef.current.play().catch(() => {});
    }
  }, [hostMode, localStream, remoteStream]);
  useEffect(() => {
    if (!showGifts || ownedStickersLoadedRef.current) return;
    ownedStickersLoadedRef.current = true;
    setGiftLoading(true);
    marketplaceApi.stickerPacks()
      .then((packs) => {
        const stickers = packs.flatMap((pack) => (pack.stickers || []).map((sticker) => ({ ...sticker, pack_title: pack.title })));
        setOwnedStickers(stickers);
      })
      .catch((error) => { ownedStickersLoadedRef.current = false; toast.error(errorMessage(error, "Your free stickers are ready, but Marketplace stickers could not be loaded.")); })
      .finally(() => setGiftLoading(false));
  }, [showGifts]);

  const closePeers = useCallback(() => {
    peersRef.current.forEach((peer) => peer.close());
    peersRef.current.clear();
    pendingIceRef.current.clear();
  }, []);

  const closeMedia = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setLocalStream(null);
    setRemoteStream(null);
  }, []);
  useEffect(() => () => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    peersRef.current.forEach((peer) => peer.close());
    socketRef.current?.close();
  }, []);

  const sendWs = useCallback((payload) => {
    const socket = socketRef.current;
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(payload));
  }, []);

  const connectPeer = useCallback((peerId, publish = hostMode) => {
    const key = Number(peerId);
    const existing = peersRef.current.get(key);
    if (existing && existing.connectionState !== "closed") return existing;
    const peer = new RTCPeerConnection({ iceServers: iceServersRef.current });
    peersRef.current.set(key, peer);
    if (publish && streamRef.current) streamRef.current.getTracks().forEach((track) => {
      const sender = peer.addTrack(track, streamRef.current);
      if (track.kind === "video" && sender.setParameters) {
        const parameters = sender.getParameters();
        parameters.encodings = parameters.encodings?.length ? parameters.encodings : [{}];
        parameters.encodings[0].maxBitrate = 500_000;
        sender.setParameters(parameters).catch(() => {});
      }
    });
    peer.ontrack = (event) => {
      const incoming = event.streams?.[0] || new MediaStream([event.track]);
      setRemoteStream(incoming);
    };
    peer.onicecandidate = (event) => {
      if (event.candidate) sendWs({ type: "signal", target_id: key, signal: { type: "ice", candidate: event.candidate } });
    };
    peer.onconnectionstatechange = () => {
      if (["failed", "disconnected"].includes(peer.connectionState)) {
        setWarning("Video connection is unstable. This network may need a TURN relay.");
      } else if (peer.connectionState === "connected") setWarning("");
    };
    return peer;
  }, [hostMode, sendWs]);

  const handleSignal = useCallback(async (from, signal) => {
    try {
      const peer = connectPeer(from, hostMode);
      if (signal.type === "offer" && !hostMode) {
        await peer.setRemoteDescription(signal.description);
        const answer = await peer.createAnswer();
        await peer.setLocalDescription(answer);
        sendWs({ type: "signal", target_id: Number(from), signal: { type: "answer", description: peer.localDescription } });
        const queued = pendingIceRef.current.get(Number(from)) || [];
        for (const candidate of queued) await peer.addIceCandidate(candidate).catch(() => {});
        pendingIceRef.current.delete(Number(from));
      } else if (signal.type === "answer" && hostMode) {
        await peer.setRemoteDescription(signal.description);
        const queued = pendingIceRef.current.get(Number(from)) || [];
        for (const candidate of queued) await peer.addIceCandidate(candidate).catch(() => {});
        pendingIceRef.current.delete(Number(from));
      } else if (signal.type === "ice") {
        if (peer.remoteDescription) await peer.addIceCandidate(signal.candidate).catch(() => {});
        else pendingIceRef.current.set(Number(from), [...(pendingIceRef.current.get(Number(from)) || []), signal.candidate]);
      }
    } catch {
      setWarning("Could not establish the live video connection. Try again on another network.");
    }
  }, [connectPeer, hostMode, sendWs]);

  const offerViewer = useCallback(async (userId) => {
    try {
      const peer = connectPeer(userId, true);
      if (peer.signalingState !== "stable") return;
      const offer = await peer.createOffer();
      await peer.setLocalDescription(offer);
      sendWs({ type: "signal", target_id: Number(userId), signal: { type: "offer", description: peer.localDescription } });
    } catch { setWarning("Could not start the video connection for a viewer."); }
  }, [connectPeer, sendWs]);

  const appendEvent = useCallback((event) => {
    if (!event?.id) return;
    setEvents((current) => current.some((item) => item.id === event.id) ? current : [...current.slice(-49), event]);
    if (event.kind === "REACTION" || event.kind === "STICKER") {
      const id = `${event.id}-${Date.now()}`;
      setFloating((items) => [...items.slice(-5), { id, icon: event.kind === "REACTION" ? event.text : (STICKERS.find(([code]) => code === event.sticker_code)?.[1] || "✨") }]);
      window.setTimeout(() => setFloating((items) => items.filter((item) => item.id !== id)), 2600);
    }
  }, []);

  useEffect(() => {
    if (!stream?.id) return undefined;
    let alive = true;
    const open = async () => {
      setConnecting(true);
      try {
        const [details, ice] = await Promise.all([
          hostMode ? Promise.resolve(null) : socialApi.liveStream(stream.id),
          callApi.iceServers().catch(() => null),
        ]);
        if (!alive) return;
        if (details) { setStream(details); setEvents(details.events || []); setViewerCount(details.viewer_count || 0); }
        if (Array.isArray(ice?.ice_servers) && ice.ice_servers.length) iceServersRef.current = ice.ice_servers;
        const socket = new WebSocket(socketUrl(stream.id), tokens.access ? ["nsat.jwt", tokens.access] : undefined);
        socketRef.current = socket;
        socket.onopen = () => { setConnecting(false); if (hostMode) socket.send(JSON.stringify({ type: "heartbeat" })); };
        socket.onmessage = async (message) => {
          let data;
          try { data = JSON.parse(message.data); } catch { return; }
          if (data.type === "ready") {
            setViewerCount(Number(data.payload?.viewer_count) || 0);
            if (!hostMode) sendWs({ type: "viewer_ready" });
          } else if (data.type === "viewer_joined") {
            if (data.payload?.viewer_count != null) setViewerCount(Number(data.payload.viewer_count) || 0);
            if (hostMode && Number(data.payload?.user_id) !== Number(me?.id)) await offerViewer(data.payload.user_id);
          } else if (data.type === "viewer_left") {
            if (data.payload?.viewer_count != null) setViewerCount(Number(data.payload.viewer_count) || 0);
            peersRef.current.get(Number(data.payload?.user_id))?.close();
            peersRef.current.delete(Number(data.payload?.user_id));
          } else if (data.type === "signal") {
            await handleSignal(data.payload?.from, data.payload?.signal || {});
          } else if (data.type === "live_event") appendEvent(data.payload);
          else if (data.type === "host_ready" && !hostMode) sendWs({ type: "viewer_ready" });
          else if (data.type === "stream_ended") { setWarning("This live has ended."); window.setTimeout(onClose, 1200); }
        };
        socket.onerror = () => setWarning("Live connection interrupted. Check your network.");
        socket.onclose = () => {
          if (alive && hostMode && !endingRef.current) void socialApi.endLiveStream(stream.id).catch(() => {});
          if (alive && !endingRef.current) setWarning("Live connection closed.");
        };
        const heartbeat = window.setInterval(() => sendWs({ type: "heartbeat" }), 30_000);
        socket.addEventListener("close", () => window.clearInterval(heartbeat), { once: true });
      } catch (error) {
        setConnecting(false);
        setWarning(errorMessage(error, "Could not join this live."));
      }
    };
    void open();
    return () => {
      alive = false;
      socketRef.current?.close();
      socketRef.current = null;
      closePeers();
      closeMedia();
    };
  }, [stream?.id, hostMode, me?.id, appendEvent, closeMedia, closePeers, handleSignal, offerViewer, onClose, sendWs]);

  const enableCamera = async () => {
    setBusy(true);
    setWarning("");
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error("Camera is not available in this browser.");
      const media = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 540 }, height: { ideal: 960 }, frameRate: { ideal: 24, max: 24 } },
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      streamRef.current = media;
      setLocalStream(media);
      setCameraReady(true);
    } catch (error) {
      setWarning(error?.name === "NotAllowedError" ? "Allow camera and microphone access to start a live." : errorMessage(error, "Could not open camera and microphone."));
    } finally { setBusy(false); }
  };

  const startLive = async () => {
    if (!streamRef.current || busy) return;
    setBusy(true);
    try { const created = await socialApi.createLiveStream(stream?.title || ""); setStream(created); setViewerCount(0); }
    catch (error) { setWarning(errorMessage(error, "Could not start your live.")); }
    finally { setBusy(false); }
  };

  const submitEvent = async (kind, payload = {}) => {
    if (!stream?.id || busy) return;
    const text = kind === "COMMENT" ? draft.trim() : payload.text || "";
    if (kind === "COMMENT" && !text) return;
    setBusy(true);
    try {
      const event = await socialApi.liveEvent(stream.id, { kind, text, ...(payload.sticker_code ? { sticker_code: payload.sticker_code } : {}), ...(payload.sticker_asset_id ? { sticker_asset_id: payload.sticker_asset_id } : {}) });
      appendEvent(event);
      if (kind === "COMMENT") setDraft("");
    } catch (error) { toast.error(errorMessage(error, "Could not send that live interaction.")); }
    finally { setBusy(false); }
  };

  const followHost = async () => {
    if (!stream?.host?.id || following || followBusy) return;
    setFollowBusy(true);
    try { const result = await socialApi.follow(stream.host.id); setFollowing(Boolean(result.following || result.request_pending)); toast.success(result.request_pending ? "Follow request sent." : "Following this creator."); }
    catch (error) { toast.error(errorMessage(error, "Could not follow this creator.")); }
    finally { setFollowBusy(false); }
  };

  const tipHost = async () => {
    try {
      const recipient = await walletApi.socialLiveRecipient(stream.host.id);
      app.openWallet({ view: "send", to: recipient.address, amount: "10" });
    } catch (error) {
      toast.error(error?.response?.data?.code === "recipient_wallet_not_connected" ? "This creator has not connected a verified NSAT wallet." : errorMessage(error, "Could not prepare creator support."));
    }
  };

  const endLive = async () => {
    if (!hostMode) { endingRef.current = true; onClose(); return; }
    if (!window.confirm("End this live stream? Viewers will be disconnected.")) return;
    endingRef.current = true;
    setBusy(true);
    try { if (stream?.id) await socialApi.endLiveStream(stream.id); }
    catch (error) { toast.error(errorMessage(error, "Could not end the live cleanly.")); }
    finally { socketRef.current?.close(); closePeers(); closeMedia(); setBusy(false); onClose(); }
  };

  const toggleCamera = () => {
    const next = !cameraOff;
    streamRef.current?.getVideoTracks().forEach((track) => { track.enabled = !next; });
    setCameraOff(next);
  };
  const toggleMuted = () => {
    const next = !muted;
    streamRef.current?.getAudioTracks().forEach((track) => { track.enabled = !next; });
    setMuted(next);
  };

  return (
    <section className={`social-live-room${hostMode ? " is-host" : " is-viewer"}`} role="dialog" aria-modal="true" aria-label={hostMode ? "Start a live video" : "Watch live video"}>
      <video ref={videoRef} className="social-live-room__video" autoPlay playsInline muted={hostMode || !audioEnabled} aria-label={hostMode ? "Camera preview" : "Live video"} onClick={() => { if (!hostMode) { setAudioEnabled(true); videoRef.current?.play().catch(() => {}); } }} />
      {!hostMode && !remoteStream ? <div className="social-live-room__waiting"><Radio size={38} /><strong>{connecting ? "Connecting to live…" : "Waiting for the creator’s video…"}</strong><span>Keep this screen open while the connection is made.</span></div> : null}
      {hostMode && !cameraReady ? <div className="social-live-room__preflight"><div className="social-live-room__preflight-card"><span className="social-live-room__eyebrow"><Radio size={15} /> VERTICAL LIVE</span><h2>Go live with your community</h2><p>Camera video streams directly between devices. In this initial version, a live supports up to 6 viewers.</p><label>Live title<input value={stream?.title || ""} onChange={(event) => setStream((current) => ({ ...(current || {}), title: event.target.value.slice(0, 100) }))} maxLength={100} placeholder="What are you sharing?" /></label><button type="button" className="social-live-room__primary" onClick={enableCamera} disabled={busy}>{busy ? <Spinner size={17} /> : <Camera size={17} />} Turn on camera</button><small>Only start after you allow camera and microphone access.</small></div></div> : null}
      <header className="social-live-room__top">
        <button type="button" aria-label="Close live" onClick={endLive}><X size={22} /></button>
        {stream ? <div className="social-live-room__host"><Avatar src={stream.host?.profile_picture || stream.host?.profile?.profile_picture} name={stream.host?.display_name || stream.host?.profile?.display_name} size={38} /><span><strong>{stream.host?.display_name || stream.host?.profile?.display_name || "Creator"}</strong><small>{stream.title || "Live now"}</small></span>{!hostMode ? <button type="button" onClick={followHost} disabled={following}><UserPlus size={15} /> Follow</button> : null}</div> : <span className="social-live-room__draft-title">Preview</span>}
        {stream ? <span className="social-live-room__live-badge"><i /> LIVE</span> : null}
        {stream ? <span className="social-live-room__viewers"><span>{viewerCount}</span> watching</span> : null}
      </header>
      {stream ? <div className="social-live-room__rail" aria-label="Live reactions">{floating.map((item) => <span key={item.id} className="social-live-room__float">{item.icon}</span>)}</div> : null}
      {warning ? <div className="social-live-room__warning" role="status">{warning}</div> : null}
      {stream && !hostMode ? <div className="social-live-room__actions"><button type="button" aria-label={following ? "Following creator" : "Follow creator"} aria-pressed={following} onClick={followHost} disabled={following || followBusy}><UserPlus size={18} /></button><button type="button" aria-label="Like live" onClick={() => void submitEvent("REACTION", { text: "❤️" })}><Heart size={18} /></button><button type="button" aria-label="Send NSAT support" onClick={tipHost}><WalletCards size={18} /> Support</button><button type="button" aria-label="Share live link" onClick={async () => { try { await navigator.clipboard?.writeText(`${location.origin}/?live=${stream.id}`); toast.success("Live link copied."); } catch { toast.error("Could not copy the live link."); } }}><Share2 size={18} /></button><button type="button" aria-label={audioEnabled ? "Mute live audio" : "Enable live audio"} aria-pressed={audioEnabled} onClick={() => { const next = !audioEnabled; setAudioEnabled(next); if (next) videoRef.current?.play().catch(() => {}); }}><span aria-hidden="true">{audioEnabled ? <Volume2 size={18} /> : <VolumeX size={18} />}</span></button></div> : null}
      {stream ? <div className="social-live-room__chat" aria-label="Live comments">
        <div className="social-live-room__events">{events.slice(-10).map((event) => <div key={event.id} className={`social-live-room__event is-${event.kind.toLowerCase()}`}>
          {event.kind === "COMMENT" ? <><strong>{event.actor?.display_name || "Viewer"}</strong><span>{event.text}</span></> : event.kind === "REACTION" ? <><strong>{event.actor?.display_name || "Viewer"}</strong><span>{event.text}</span></> : <><strong>{event.actor?.display_name || "Viewer"}</strong><span>sent {event.sticker?.pack_title || STICKERS.find(([code]) => code === event.sticker_code)?.[2] || "a sticker"} {event.sticker ? <img className="social-live-room__event-sticker" src={event.sticker.file} alt={`${event.sticker.pack_title} sticker`} /> : STICKERS.find(([code]) => code === event.sticker_code)?.[1] || "✨"}</span></>}
        </div>)}</div>
        <form className="social-live-room__composer" onSubmit={(event) => { event.preventDefault(); void submitEvent("COMMENT"); }}>
          <input value={draft} onChange={(event) => setDraft(event.target.value)} maxLength={240} placeholder="Say something…" aria-label="Live comment" />
          <button type="submit" aria-label="Send comment" disabled={!draft.trim() || busy}><Send size={17} /></button>
        </form>
        <div className="social-live-room__quick-actions">{REACTIONS.map((reaction) => <button key={reaction} type="button" aria-label={`React ${reaction}`} onClick={() => void submitEvent("REACTION", { text: reaction })}>{reaction}</button>)}<button type="button" aria-label="Open free gifts" onClick={() => setShowGifts((value) => !value)}><Gift size={17} /></button><button type="button" aria-label="More live actions" onClick={() => setWarning("Live reports and moderation are coming soon.")}><ArrowDown size={17} /></button></div>
      </div> : null}
      {showGifts && stream ? <div className="social-live-room__gifts" role="dialog" aria-label="Live gifts"><span className="social-live-room__gift-heading">Free gifts</span>{STICKERS.map(([code, emoji, label]) => <button type="button" key={`free-${code}`} disabled={busy} onClick={() => { setShowGifts(false); void submitEvent("STICKER", { sticker_code: code }); }}><span>{emoji}</span><small>{label}</small></button>)}{ownedStickers.length ? <span className="social-live-room__gift-heading">My Marketplace stickers</span> : null}{ownedStickers.map((sticker) => <button type="button" key={`owned-${sticker.id}`} disabled={busy} onClick={() => { setShowGifts(false); void submitEvent("STICKER", { sticker_asset_id: sticker.id }); }}><img src={sticker.file} alt="" /><small>{sticker.pack_title}</small></button>)}{giftLoading ? <span className="social-live-room__gift-loading">Loading your sticker library…</span> : null}</div> : null}
      {hostMode && cameraReady && !stream ? <div className="social-live-room__start"><button type="button" onClick={startLive} disabled={busy}>{busy ? <Spinner size={18} /> : <Radio size={18} />} Start live video</button><button type="button" className="social-live-room__camera-toggle" onClick={toggleCamera} aria-label={cameraOff ? "Turn camera on" : "Turn camera off"}>{cameraOff ? <VideoOff size={18} /> : <Video size={18} />}</button><button type="button" className="social-live-room__camera-toggle" onClick={toggleMuted} aria-label={muted ? "Unmute microphone" : "Mute microphone"}>{muted ? <MicOff size={18} /> : <Mic size={18} />}</button></div> : null}
      {hostMode && cameraReady && stream ? <div className="social-live-room__host-controls"><button type="button" className="social-live-room__camera-toggle" onClick={toggleCamera} aria-label={cameraOff ? "Turn camera on" : "Turn camera off"}>{cameraOff ? <VideoOff size={18} /> : <Video size={18} />}</button><button type="button" className="social-live-room__camera-toggle" onClick={toggleMuted} aria-label={muted ? "Unmute microphone" : "Mute microphone"}>{muted ? <MicOff size={18} /> : <Mic size={18} />}</button><button type="button" onClick={endLive}>End live</button></div> : null}
      {!hostMode && connecting ? <span className="social-live-room__connecting"><Spinner size={15} /> Connecting</span> : null}
      <span className="social-live-room__security"><Sparkles size={13} /> No payment is sent by tapping a reaction or sticker. Wallet support always requires review and signing.</span>
    </section>
  );
}
