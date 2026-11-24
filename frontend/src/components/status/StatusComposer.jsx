import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AtSign, ChevronRight, CircleDashed, Crop, Palette, Send, Smile, Type, X } from "lucide-react";
import { errorMessage } from "../../api/client";
import { statusApi } from "../../api/endpoints";
import { useObjectUrl } from "../../hooks";
import { loadStatus } from "../../store/actions";
import { useStore } from "../../store/store";
import { toast } from "../../services/toast";
import { IconButton, Modal, Spinner } from "../common/ui";
import EmojiPicker from "../conversation/EmojiPicker";
import ImageEditor from "../media/ImageEditor";
import { getStatusPrivacy, setStatusPrivacy, STATUS_COLORS } from "./statusPrefs";
import StatusPrivacyEditor from "./StatusPrivacyEditor";
import VideoTrimmer from "../media/VideoTrimmer";
import { useTrimLoop } from "../media/useTrimLoop";

const FONTS = ["inherit", "Georgia, serif", "'Courier New', monospace", "'Trebuchet MS', sans-serif"];
const LABELS = { CONTACTS: "My contacts", CONTACTS_EXCEPT: "My contacts except…", ONLY_SHARE_WITH: "Only share with…", EVERYONE: "Everyone" };

/** Create a text, photo or video status (24h). */
export default function StatusComposer({ initialFile, initialFiles = [], mode = "text", onClose }) {
  const me = useStore((state) => state.me);
  const [files, setFiles] = useState(() => initialFiles.length ? initialFiles : initialFile ? [initialFile] : []);
  const [fileIndex, setFileIndex] = useState(0);
  const file = files[fileIndex] || null;
  const [editing, setEditing] = useState(false);
  const [captionEmoji, setCaptionEmoji] = useState(false);
  const captionEmojiRef = useRef(null);
  const [text, setText] = useState("");
  const [caption, setCaption] = useState("");
  const [color, setColor] = useState(STATUS_COLORS[0]);
  const [font, setFont] = useState(0);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [emojiOpen, setEmojiOpen] = useState(false);
  const emojiRef = useRef(null);
  const url = useObjectUrl(file);
  const previewUrls = useMemo(() => files.map((item) => URL.createObjectURL(item)), [files]);
  useEffect(() => () => previewUrls.forEach((previewUrl) => URL.revokeObjectURL(previewUrl)), [previewUrls]);
  const [privacy, setPrivacy] = useState(() => getStatusPrivacy(me.id));
  const [privacyOpen, setPrivacyOpen] = useState(false);
  const [mentionPeople, setMentionPeople] = useState([]);
  const [mentionPickerOpen, setMentionPickerOpen] = useState(false);
  const [mentions, setMentions] = useState([]);
  const isText = mode === "text" && files.length === 0;
  const isVideo = file?.type.startsWith("video/");
  // Video: pick the part to post (WhatsApp keeps status videos to 60 s).
  const videoRef = useRef(null);
  const [duration, setDuration] = useState(0);
  const [trim, setTrim] = useState(null);
  const loopTrim = useMemo(() => (trim ? { start: trim.start, end: trim.end } : null), [trim]);
  useTrimLoop(videoRef, loopTrim);
  const trimmed = Boolean(trim && duration && (trim.start > 0.05 || trim.end < duration - 0.05));

  const audienceLabel =
    privacy.visibility === "ONLY_SHARE_WITH"
      ? `${privacy.users.length} included`
      : privacy.visibility === "CONTACTS_EXCEPT"
        ? `${privacy.users.length} excluded`
        : LABELS[privacy.visibility];

  useEffect(() => {
    let active = true;
    statusApi.contacts().then((rows) => {
      if (active) setMentionPeople(rows.map((row) => row.user).filter(Boolean));
    }).catch(() => { if (active) setMentionPeople([]); });
    return () => { active = false; };
  }, []);

  function addMention(person) {
    const id = Number(person.id);
    if (!id || mentions.includes(id)) {
      setMentionPickerOpen(false);
      return;
    }
    const name = (person.profile?.display_name || person.username || person.public_id || "Contact").trim();
    setMentions((items) => [...items, id]);
    const token = `@${name}`;
    if (isText) setText((value) => `${value}${value && !value.endsWith(" ") ? " " : ""}${token} `);
    else setCaption((value) => `${value}${value && !value.endsWith(" ") ? " " : ""}${token} `);
    setMentionPickerOpen(false);
  }

  const mentionControls = mentionPickerOpen ? (
    <div className="status-mention-picker" role="group" aria-label="Mention a contact">
      {mentionPeople.filter((person) => !mentions.includes(Number(person.id))).map((person) => (
        <button key={person.id} type="button" onClick={() => addMention(person)}>
          {person.profile?.display_name || person.username || person.public_id || "Contact"}
        </button>
      ))}
      {!mentionPeople.length ? <span>Save a contact or start a chat before mentioning them.</span> : null}
    </div>
  ) : null;
  const mentionChips = mentions.length ? (
    <div className="status-mention-chips" aria-label="Mentioned contacts">
      {mentions.map((id) => {
        const person = mentionPeople.find((entry) => Number(entry.id) === id);
        return <button key={id} type="button" onClick={() => setMentions((items) => items.filter((item) => item !== id))} aria-label={`Remove mention ${person?.profile?.display_name || "contact"}`}>
          @{person?.profile?.display_name || person?.username || person?.public_id || "Contact"} <span aria-hidden="true">×</span>
        </button>;
      })}
    </div>
  ) : null;

  async function publish() {
    if (isText && !text.trim()) {
      toast.error("Type a status first.");
      return;
    }
    if (privacy.visibility === "ONLY_SHARE_WITH" && !privacy.users.length) {
      toast.error("Status privacy is set to “Only share with…” but no contacts are selected.");
      return;
    }
    setBusy(true);
    setProgress(0);
    let completed = 0;
    try {
      const users = ["CONTACTS_EXCEPT", "ONLY_SHARE_WITH"].includes(privacy.visibility) ? privacy.users : undefined;
      if (isText) {
        await statusApi.upload({ status_type: "TEXT", content: text.trim(), background_color: color, text_color: "#FFFFFF", visibility: privacy.visibility, users, mentions });
      } else {
        const totalBytes = files.reduce((sum, item) => sum + item.size, 0);
        for (let index = 0; index < files.length; index += 1) {
          const item = files[index];
          const itemVideo = item.type.startsWith("video/");
          await statusApi.upload({
            status_type: itemVideo ? "VIDEO" : "IMAGE",
            content: caption.trim(),
            media: item,
            background_color: color,
            text_color: "#FFFFFF",
            visibility: privacy.visibility,
            trim_start: itemVideo && index === fileIndex && trimmed ? trim.start.toFixed(2) : undefined,
            trim_end: itemVideo && index === fileIndex && trimmed ? trim.end.toFixed(2) : undefined,
            users,
            mentions,
          }, (event) => {
            if (event.total) {
              const loaded = files.slice(0, index).reduce((sum, previous) => sum + previous.size, 0) + Math.min(item.size, event.loaded);
              setProgress(Math.round((loaded / totalBytes) * 100));
            }
          });
          completed += 1;
        }
      }
      await loadStatus();
      toast.success(files.length > 1 ? `${files.length} status updates posted` : "Status posted");
      onClose();
    } catch (error) {
      if (files.length && completed === files.length) {
        toast.success("Status posted. Reopen Updates if it doesn't appear yet.");
        onClose();
        return;
      }
      toast.error(errorMessage(error, "Couldn't post the status."));
      if (completed) {
        setFiles((items) => items.slice(completed));
        setFileIndex(0);
        setDuration(0);
        setTrim(null);
      }
      setBusy(false);
    }
  }

  if (editing && file && !isVideo) {
    return createPortal(
      <div className="status-composer status-composer--editing" role="dialog" aria-label="Edit photo">
        <ImageEditor
          file={file}
          url={url}
          onCancel={() => setEditing(false)}
          onApply={(edited) => {
            setFiles((items) => items.map((item, index) => index === fileIndex ? edited : item));
            setEditing(false);
          }}
        />
      </div>,
      document.body,
    );
  }

  return createPortal(
    <div className={`status-composer ${isText ? "" : "status-composer--media"}`} style={isText ? { background: color } : undefined} role="dialog" aria-label="New status">
      <div className="status-composer__top">
        <IconButton icon={X} label="Close" onClick={onClose} />
        {isText ? (
          <div className="status-composer__tools">
            <span ref={emojiRef}><IconButton icon={Smile} label="Emoji" onClick={() => setEmojiOpen((value) => !value)} /></span>
            <IconButton icon={AtSign} label="Mention a contact" onClick={() => setMentionPickerOpen((value) => !value)} />
            <IconButton icon={Type} label="Change font" onClick={() => setFont((value) => (value + 1) % FONTS.length)} />
            <IconButton icon={Palette} label="Change color" onClick={() => setColor(STATUS_COLORS[(STATUS_COLORS.indexOf(color) + 1) % STATUS_COLORS.length])} />
          </div>
        ) : file && !isVideo ? (
          <div className="status-composer__tools">
            <IconButton icon={Crop} label="Crop, rotate and draw" onClick={() => setEditing(true)} />
          </div>
        ) : null}
      </div>
      {isVideo && duration ? (
        <VideoTrimmer url={url} duration={duration} value={trim} onChange={setTrim} maxLength={60} sizeBytes={file.size} />
      ) : null}
      <div className="status-composer__stage">
        {isText ? (
          <textarea
            className="status-composer__text"
            style={{ fontFamily: FONTS[font] }}
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="Type a status"
            maxLength={700}
            autoFocus
          />
        ) : file ? (
          isVideo ? (
            <video
              ref={videoRef}
              src={url}
              controls
              playsInline
              autoPlay
              onLoadedMetadata={(event) => {
                const total = event.currentTarget.duration;
                if (!Number.isFinite(total)) return;
                setDuration(total);
                setTrim({ start: 0, end: Math.min(total, 60) });
              }}
            />
          ) : (
            <img src={url} alt="Status preview" />
          )
        ) : null}
        {emojiOpen ? <EmojiPicker className="emoji-picker--status" ignoreRefs={[emojiRef]} onClose={() => setEmojiOpen(false)} onPick={(emoji) => setText((value) => value + emoji)} /> : null}
      </div>
      <div className="status-composer__bottom">
        {files.length > 1 ? <div className="status-composer__queue" aria-label="Story items">
            {files.map((item, index) => <div key={`${item.name}-${index}`} className={index === fileIndex ? "is-active" : ""}>
            <button type="button" onClick={() => { setFileIndex(index); setDuration(0); setTrim(null); }} aria-label={`Select story item ${index + 1}`} aria-pressed={index === fileIndex}>
              {item.type.startsWith("video/") ? <span>Video</span> : <img src={previewUrls[index]} alt="" />}
            </button>
            {files.length > 1 ? <button type="button" aria-label={`Remove story item ${index + 1}`} onClick={() => { setFiles((current) => current.filter((_, itemIndex) => itemIndex !== index)); setFileIndex((current) => current > index ? current - 1 : Math.min(current, files.length - 2)); setDuration(0); setTrim(null); }}>×</button> : null}
          </div>)}
        </div> : null}
        {!isText ? (
          <div className="status-composer__caption">
            <span ref={captionEmojiRef}>
              <IconButton icon={Smile} label="Emoji" onClick={() => setCaptionEmoji((value) => !value)} />
            </span>
            <IconButton icon={AtSign} label="Mention a contact" onClick={() => setMentionPickerOpen((value) => !value)} />
            <input
              value={caption}
              onChange={(event) => setCaption(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && !busy && publish()}
              placeholder="Add a caption"
              maxLength={700}
              autoFocus
            />
            {captionEmoji ? (
              <EmojiPicker
                className="emoji-picker--caption"
                ignoreRefs={[captionEmojiRef]}
                onClose={() => setCaptionEmoji(false)}
                onPick={(emoji) => setCaption((value) => value + emoji)}
              />
            ) : null}
          </div>
        ) : (
          <span className="status-composer__count">{700 - text.length}</span>
        )}
        {mentionChips}
        {mentionControls}
        <div className="status-composer__send-row">
          <button type="button" className="status-composer__audience" onClick={() => setPrivacyOpen(true)} title="Choose who can see this status">
            <CircleDashed size={16} />
            <span>Status ({audienceLabel})</span>
            <ChevronRight size={15} />
          </button>
          <button type="button" className="fab status-composer__send" onClick={publish} disabled={busy || (!isText && !files.length)} aria-label="Post status">
            {busy ? <span className="fab__progress">{progress ? `${progress}%` : <Spinner size={18} className="spinner--dark" />}</span> : <Send size={22} />}
          </button>
        </div>
      </div>
      {privacyOpen ? (
        <Modal
          title="Choose audience"
          className="status-privacy-modal"
          onClose={() => setPrivacyOpen(false)}
          footer={<button type="button" className="btn btn--primary" onClick={() => setPrivacyOpen(false)}>Done</button>}
        >
          <StatusPrivacyEditor
            value={privacy}
            onChange={(next) => {
              // Like WhatsApp: the choice also becomes the default for next time.
              setPrivacy(next);
              setStatusPrivacy(me.id, next);
            }}
          />
        </Modal>
      ) : null}
    </div>,
    document.body,
  );
}
