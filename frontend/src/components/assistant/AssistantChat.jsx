import { Fragment, useEffect, useLayoutEffect, useRef, useState } from "react";
import { ArrowLeft, Camera, ClipboardPaste, Image as ImageIcon, Mic, Send, Smile, Sparkles, Square, X } from "lucide-react";
import { toast } from "../../services/toast";
import { readClipboardFiles, shrinkImage } from "../../utils/clipboard";
import CameraCapture from "../media/CameraCapture";
import RichInput from "../conversation/RichInput";
import EmojiPicker from "../conversation/EmojiPicker";
import { useMediaQuery } from "../../hooks";
import { clockTime } from "../../utils/format";
import { IconButton } from "../common/ui";
import { useApp } from "../layout/AppContext";
import { askAssistant, loadAssistantStatus, useAssistant } from "./assistantStore";
import { ForwardDialog } from "../conversation/dialogs";
import { sendFile } from "../../store/actions";

/** Tiny safe formatter: **bold**, `code`, and "- " bullet lines. */
function Formatted({ text }) {
  const lines = String(text || "").split("\n");
  const inline = (line, keyBase) =>
    line.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, index) => {
      if (/^\*\*[^*]+\*\*$/.test(part)) return <strong key={`${keyBase}-${index}`}>{part.slice(2, -2)}</strong>;
      if (/^`[^`]+`$/.test(part)) return <code key={`${keyBase}-${index}`}>{part.slice(1, -1)}</code>;
      return <Fragment key={`${keyBase}-${index}`}>{part}</Fragment>;
    });
  return lines.map((line, index) => {
    const bullet = line.match(/^\s*(?:[-*•]|\d+[.)])\s+(.*)$/);
    if (bullet) {
      return (
        <div key={index} className="ai-bullet">
          <span aria-hidden="true">•</span>
          <span>{inline(bullet[1], index)}</span>
        </div>
      );
    }
    return line.trim() ? <div key={index}>{inline(line, index)}</div> : <div key={index} className="ai-gap" />;
  });
}

/** The SatoshiCore AI conversation in the main pane. */
export default function AssistantChat() {
  const app = useApp();
  const compact = useMediaQuery("(max-width: 900px)");
  const { messages, sending, status } = useAssistant();
  const [text, setText] = useState("");
  const [emojiOpen, setEmojiOpen] = useState(false);
  const [listening, setListening] = useState(false);
  const [photo, setPhoto] = useState(null); // { mime_type, data, thumb }
  const [camera, setCamera] = useState(false);
  const [mode, setMode] = useState("chat");
  const [toolMenu, setToolMenu] = useState(false);
  const [shareImage, setShareImage] = useState(null);
  const galleryRef = useRef(null);
  const scrollRef = useRef(null);
  const inputRef = useRef(null);
  const emojiBtnRef = useRef(null);
  const speechRef = useRef(null);

  useEffect(() => {
    loadAssistantStatus();
  }, []);

  useLayoutEffect(() => {
    const node = scrollRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages.length, sending]);

  const disabled = status ? !status.enabled : false;

  function insertText(value) {
    const node = inputRef.current;
    const start = node?.selectionStart ?? text.length;
    const end = node?.selectionEnd ?? text.length;
    setText(text.slice(0, start) + value + text.slice(end));
    window.requestAnimationFrame(() => {
      node?.focus();
      node?.setSelectionRange(start + value.length, start + value.length);
    });
  }

  async function attachPhoto(file) {
    if (!file?.type?.startsWith("image/")) {
      toast("SatoshiCore AI can look at photos. Pick a picture.");
      return;
    }
    try {
      setPhoto(await shrinkImage(file));
      inputRef.current?.focus();
    } catch (error) {
      toast.error(error.message);
    }
  }

  async function paste() {
    const result = await readClipboardFiles();
    const image = result.files.find((file) => file.type.startsWith("image/"));
    if (image) attachPhoto(image);
    else if (result.text) insertText(result.text);
    else toast(result.error || "Clipboard is empty.");
  }

  /** Voice typing (browser speech recognition), like the mic on the WhatsApp AI chat. */
  function toggleDictation() {
    if (listening) {
      speechRef.current?.stop();
      return;
    }
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) {
      toast("Voice typing isn't supported in this browser. Use the keyboard mic instead.");
      return;
    }
    const recognition = new Recognition();
    recognition.lang = navigator.language || "en-US";
    recognition.interimResults = false;
    recognition.onresult = (event) => {
      const said = [...event.results].map((result) => result[0].transcript).join(" ").trim();
      if (said) setText((current) => (current ? `${current} ${said}` : said));
    };
    recognition.onerror = () => toast("Couldn't hear you. Check microphone permission.");
    recognition.onend = () => setListening(false);
    speechRef.current = recognition;
    setListening(true);
    recognition.start();
  }

  function submit(event) {
    event?.preventDefault();
    const value = text.trim();
    if ((!value && !photo) || sending || disabled) return;
    if (mode === "analyze" && !photo) {
      toast("Attach a photo to analyze.");
      return;
    }
    setText("");
    const selectedPhoto = photo;
    setPhoto(null);
    askAssistant(value, selectedPhoto, mode);
  }

  const tools = [
    ["chat", "Chat"],
    ["generate_image", "Create image"],
    ["analyze", "Analyze image"],
    ["translate", "Translate"],
    ["summarize", "Summarize"],
  ];

  async function shareGeneratedImage(image, roomIds) {
    const bytes = Uint8Array.from(atob(image.data), (char) => char.charCodeAt(0));
    const ext = image.mime_type === "image/jpeg" ? "jpg" : image.mime_type.split("/")[1] || "png";
    const file = new File([bytes], `satoshicore-ai-${Date.now()}.${ext}`, { type: image.mime_type });
    await Promise.all(roomIds.map((roomId) => sendFile(roomId, file, { caption: "Created with SatoshiCore AI" })));
  }

  return (
    <section className="conversation assistant-chat">
      <header className="conv-header">
        {compact ? <IconButton icon={ArrowLeft} label="Back to chats" onClick={() => app.setSection("chats")} /> : null}
        <div className="conv-header__who">
          <span className="assistant-avatar"><Sparkles size={20} /></span>
          <span className="conv-header__text">
            <span className="conv-header__title">SatoshiCore AI</span>
            <span className={`conv-header__subtitle ${sending ? "is-typing" : ""}`}>{sending ? "typing…" : disabled ? "not set up" : `AI assistant${status?.provider_label ? ` · ${status.provider_label}` : ""}`}</span>
          </span>
        </div>
      </header>

      <div className="conversation__body">
        <div className="messages" ref={scrollRef}>
          <div className="messages__inner">
            <div className="system-pill system-pill--info">
              <Sparkles size={13} /> Replies are generated by AI and may be inaccurate. Don't share passwords or private details.
            </div>
            {!messages.length ? (
              <div className="assistant-empty">
                <span className="assistant-avatar assistant-avatar--lg"><Sparkles size={30} /></span>
                <p>{disabled ? "SatoshiCore AI isn't set up on this server yet." : "Ask me anything — I can explain, write, translate and brainstorm."}</p>
              </div>
            ) : null}
            {messages.map((message) => (
              <div key={message.id} className={`msg-row ${message.role === "user" ? "msg-row--out" : "msg-row--in"}`}>
                <div className="msg-row__inner">
                  <div className={`bubble bubble--${message.role === "user" ? "out" : "in"} ${message.error ? "bubble--ai-error" : ""}`} style={{ "--meta-w": "58px" }}>
                    {message.thumb ? <img className="ai-photo" src={message.thumb} alt="Photo sent to SatoshiCore AI" /> : null}
                    {message.content ? (
                      <span className="bubble__text ai-text">
                        <Formatted text={message.content} />
                      </span>
                    ) : null}
                    {message.image ? (
                      <div className="ai-generated-image">
                        <img src={`data:${message.image.mime_type};base64,${message.image.data}`} alt="Image generated by SatoshiCore AI" />
                        <div className="ai-generated-image__actions">
                          <a className="btn btn--ghost" href={`data:${message.image.mime_type};base64,${message.image.data}`} download={`satoshicore-ai-${message.id}.png`}>Download image</a>
                          <button type="button" className="btn btn--ghost" onClick={() => setShareImage(message.image)}>Share to chat</button>
                        </div>
                      </div>
                    ) : null}
                    {message.error ? <button className="btn btn--text" type="button" onClick={() => toast("Please resend your request.")}>Retry</button> : null}
                    <span className="bubble__meta"><span>{clockTime(message.at)}</span></span>
                  </div>
                </div>
              </div>
            ))}
            {sending ? (
              <div className="msg-row msg-row--in">
                <div className="msg-row__inner">
                  <div className="bubble bubble--in ai-typing" aria-label="SatoshiCore AI is typing">
                    <span /><span /><span />
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </div>

      <form className="composer assistant-composer" onSubmit={submit}>
        {emojiOpen ? (
          <EmojiPicker className="emoji-picker--composer" onPick={insertText} onClose={() => setEmojiOpen(false)} ignoreRefs={[emojiBtnRef]} />
        ) : null}
        {photo ? (
          <div className="ai-attach">
            <img src={photo.thumb} alt="Photo to send" />
            <span>Photo · ask about it or just send</span>
            <button type="button" className="icon-btn" aria-label="Remove photo" onClick={() => setPhoto(null)}><X size={18} /></button>
          </div>
        ) : null}
        <div className="ai-tool-row">
          <button type="button" className="btn btn--ghost ai-tool-trigger" aria-expanded={toolMenu} onClick={() => setToolMenu((value) => !value)}>
            {tools.find(([id]) => id === mode)?.[1] || "Chat"} ▾
          </button>
          {toolMenu ? <div className="ai-tool-menu" role="menu">{tools.filter(([id]) => id !== "analyze" || status?.image_generation_enabled !== undefined).map(([id, label]) => (
            <button type="button" role="menuitem" key={id} className={mode === id ? "is-active" : ""} onClick={() => { setMode(id); setToolMenu(false); }}>{label}</button>
          ))}</div> : null}
          <span className="ai-privacy-note">Selected content is sent to Google Gemini only when you submit.</span>
        </div>
        <div className="composer__row">
          <div className="composer__pill">
            <button
              ref={emojiBtnRef}
              type="button"
              className={`icon-btn ${emojiOpen ? "is-active" : ""}`}
              aria-label="Emoji"
              onClick={() => setEmojiOpen((value) => !value)}
              disabled={disabled}
            >
              <Smile size={23} />
            </button>
            <RichInput
              ref={inputRef}
              className="composer__input"
              value={text}
              onChange={(event) => setText(event.target.value)}
              onFiles={(files) => attachPhoto(files.find((item) => item.type.startsWith("image/")) || files[0])}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) submit(event);
              }}
              placeholder={disabled ? "SatoshiCore AI isn't set up yet" : listening ? "Listening…" : mode === "generate_image" ? "Describe the image to create" : mode === "translate" ? "Text to translate · add a target language if needed" : mode === "summarize" ? "Text to summarize" : mode === "analyze" ? "Ask about the attached image" : "Ask SatoshiCore AI"}
              aria-label="Ask SatoshiCore AI"
              disabled={disabled}
              maxLength={4000}
            />
            <button type="button" className="icon-btn" aria-label="Paste from clipboard" onClick={paste} disabled={disabled}>
              <ClipboardPaste size={21} />
            </button>
            {!text.trim() ? (
              <>
                <button type="button" className="icon-btn" aria-label="Photo from gallery" onClick={() => galleryRef.current?.click()} disabled={disabled}>
                  <ImageIcon size={21} />
                </button>
                <button type="button" className="icon-btn" aria-label="Camera" onClick={() => setCamera(true)} disabled={disabled}>
                  <Camera size={21} />
                </button>
              </>
            ) : null}
          </div>
          <input
            ref={galleryRef}
            type="file"
            accept="image/*"
            hidden
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (file) attachPhoto(file);
            }}
          />
          {text.trim() || photo ? (
            <button type="submit" className="send-btn composer__action" aria-label="Send to SatoshiCore AI" disabled={sending || disabled}>
              <Send size={22} />
            </button>
          ) : (
            <button
              type="button"
              className={`send-btn composer__action ${listening ? "is-listening" : ""}`}
              aria-label={listening ? "Stop voice typing" : "Voice typing"}
              onClick={toggleDictation}
              disabled={disabled}
            >
              {listening ? <Square size={18} /> : <Mic size={23} />}
            </button>
          )}
        </div>
      </form>
      {camera ? (
        <div className="camera-modal">
          <CameraCapture
            onClose={() => setCamera(false)}
            onGallery={() => {
              setCamera(false);
              galleryRef.current?.click();
            }}
            onCapture={(file) => {
              setCamera(false);
              attachPhoto(file);
            }}
          />
        </div>
      ) : null}
      {shareImage ? <ForwardDialog title="Share AI image to chat" onClose={() => setShareImage(null)} onSend={(roomIds) => shareGeneratedImage(shareImage, roomIds)} /> : null}
    </section>
  );
}
