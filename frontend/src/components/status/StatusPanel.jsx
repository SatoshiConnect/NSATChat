import { useEffect, useMemo, useRef, useState } from "react";
import { Image as ImageIcon, Lock, MoreVertical, Pencil, Play, Plus } from "lucide-react";
import { useStore } from "../../store/store";
import { toast } from "../../services/toast";
import { detailTime } from "../../utils/format";
import { contactsByUser, displayUserName } from "../../utils/messages";
import { Avatar, EmptyState, IconButton, Menu, MenuButton, PanelHeader, Spinner } from "../common/ui";
import PresenceAvatar from "../common/PresenceAvatar";
import { normalizeFiles, validateFiles } from "../../utils/files";
import { statusApi } from "../../api/endpoints";
import { mediaUrl } from "../../api/client";
import { useMediaQuery } from "../../hooks";
import StatusComposer from "./StatusComposer";
import StatusMain from "./StatusMain";
import StatusViewer from "./StatusViewer";
import { getStatusPrivacy, setStatusPrivacy } from "./statusPrefs";
import StatusPrivacyEditor from "./StatusPrivacyEditor";
import "../../styles/status-story-previews.css";

function PrivacyView({ onBack }) {
  const me = useStore((state) => state.me);
  const [value, setValue] = useState(() => getStatusPrivacy(me.id));
  const update = (next) => {
    setValue(next);
    setStatusPrivacy(me.id, next);
  };

  return (
    <section className="panel">
      <PanelHeader title="Status privacy" onBack={onBack} variant="sub" />
      <div className="panel__scroll">
        <StatusPrivacyEditor value={value} onChange={update} />
        <p className="info-muted info-pad">
          <Lock size={12} /> Changes to your privacy settings won't affect status updates that you've sent already.
        </p>
      </div>
    </section>
  );
}

export default function StatusPanel() {
  const compact = useMediaQuery("(max-width: 900px)");
  const me = useStore((state) => state.me);
  const feed = useStore((state) => state.statusFeed);
  const mine = useStore((state) => state.myStatuses);
  const loaded = useStore((state) => state.statusLoaded);
  const contacts = useStore((state) => state.contacts);
  const contactMap = useMemo(() => contactsByUser(contacts), [contacts]);
  const [view, setView] = useState("list");
  const [viewer, setViewer] = useState(null); // { groups, start }
  const [composer, setComposer] = useState(null); // { mode, file }
  const [addAnchor, setAddAnchor] = useState(null);
  const fileRef = useRef(null);
  const openingStatusId = useRef(null);

  useEffect(() => {
    const handler = (event) => {
      if (event.detail === "text") setComposer({ mode: "text" });
      else fileRef.current?.click();
    };
    window.addEventListener("mhtalk:new-status", handler);
    return () => window.removeEventListener("mhtalk:new-status", handler);
  }, []);

  useEffect(() => {
    const focusStatus = async (event) => {
      const detail = event?.detail || window.__mhtalkPendingStatus;
      if (!Number(detail?.status_id)) return;
      if (openingStatusId.current === Number(detail.status_id)) return;
      openingStatusId.current = Number(detail.status_id);
      try {
        const [visibleGroups, ownStatuses] = await Promise.all([statusApi.feed(), statusApi.mine()]);
        const groups = [...visibleGroups];
        if (ownStatuses.some((item) => Number(item.id) === Number(detail.status_id))) {
          groups.unshift({ user: me, statuses: ownStatuses, unseen_count: 0 });
        }
        groups.forEach((group) => group.statuses.sort((a, b) => new Date(a.created_at) - new Date(b.created_at)));
        const index = groups.findIndex((group) =>
          (!detail.author_id || Number(group.user?.id) === Number(detail.author_id))
          && group.statuses.some((item) => Number(item.id) === Number(detail.status_id)),
        );
        if (index < 0) {
          openingStatusId.current = null;
          toast.error("That status is no longer available.");
          return;
        }
        setViewer({ groups, start: index, startStatusId: Number(detail.status_id) });
      } catch (error) {
        openingStatusId.current = null;
        toast.error(error?.message || "Couldn't open that status.");
      } finally {
        if (window.__mhtalkPendingStatus?.status_id === Number(detail.status_id)) delete window.__mhtalkPendingStatus;
      }
    };
    window.addEventListener("mhtalk:focus-status", focusStatus);
    if (window.__mhtalkPendingStatus) focusStatus({ detail: window.__mhtalkPendingStatus });
    return () => window.removeEventListener("mhtalk:focus-status", focusStatus);
  }, [me]);

  const recent = feed.filter((group) => group.unseen_count > 0);
  const viewed = feed.filter((group) => !group.unseen_count);
  const sortByLatest = (a, b) => new Date(b.statuses[0]?.created_at || 0) - new Date(a.statuses[0]?.created_at || 0);
  recent.sort(sortByLatest);
  viewed.sort(sortByLatest);

  const myGroup = mine.length ? { user: me, statuses: [...mine].sort((a, b) => new Date(a.created_at) - new Date(b.created_at)).map((s) => ({ ...s, is_viewed: true })), unseen_count: 0 } : null;
  const storyMedia = (group) => group?.statuses?.find((item) => item.media && (item.status_type === "IMAGE" || item.status_type === "VIDEO"));

  const openGroup = (list, index) => {
    const groups = list.map((group) => ({ ...group, statuses: [...group.statuses].sort((a, b) => new Date(a.created_at) - new Date(b.created_at)) }));
    setViewer({ groups, start: index });
  };

  if (view === "privacy") return <PrivacyView onBack={() => setView("list")} />;

  const addItems = [
    { label: "Photos & videos", icon: ImageIcon, onClick: () => fileRef.current?.click() },
    { label: "Text", icon: Pencil, onClick: () => setComposer({ mode: "text" }) },
  ];
  const mobileStories = (
    <section className="status-stories status-stories--mobile" aria-label="Stories">
      <h2>Stories</h2>
      <div className="status-stories__rail">
        <button type="button" className={`status-story${storyMedia(myGroup) ? " status-story--has-media" : ""}`} onClick={() => (myGroup ? openGroup([myGroup], 0) : fileRef.current?.click())} aria-label={myGroup ? "View your status" : "Add a status update"}>
          {storyMedia(myGroup) ? <StoryCardMedia status={storyMedia(myGroup)} /> : null}
          <span className="status-story__avatar">
            <Avatar src={me.profile?.profile_picture} name={me.profile?.display_name} size={52} ring={myGroup ? "seen" : undefined} />
            {!myGroup ? <span className="status-row__plus"><Plus size={14} strokeWidth={3} /></span> : null}
          </span>
          <span className="status-story__name">{myGroup ? "My status" : "Create story"}</span>
          <span className="status-story__meta">{myGroup ? `${mine.length} updates` : "Share a moment"}</span>
        </button>
        {[...recent, ...viewed].map((group, index, groups) => (
          <button key={group.user.id} type="button" className={`status-story${storyMedia(group) ? " status-story--has-media" : ""}`} onClick={() => openGroup(groups, index)} aria-label={`View ${displayUserName(group.user, contactMap)}'s status`}>
            {storyMedia(group) ? <StoryCardMedia status={storyMedia(group)} /> : null}
            <span className="status-story__avatar">
              <PresenceAvatar user={group.user} src={group.user.profile?.profile_picture} name={displayUserName(group.user, contactMap)} size={52} ring={group.unseen_count > 0 ? "new" : "seen"} />
            </span>
            <span className="status-story__name">{displayUserName(group.user, contactMap)}</span>
            <span className="status-story__meta">{detailTime(group.statuses[0]?.created_at)}</span>
          </button>
        ))}
      </div>
      {!loaded && !feed.length ? <div className="status-stories__loading"><Spinner size={16} /> Loading stories</div> : null}
    </section>
  );

  return (
    <section className="panel status-panel">
      <PanelHeader
        title={compact ? "Social" : "Stories"}
        actions={(
          <>
            <IconButton icon={Plus} label="Add status" onClick={(event) => setAddAnchor(event.currentTarget)} />
            <MenuButton icon={MoreVertical} label="Menu" items={[{ label: "Status privacy", icon: Lock, onClick: () => setView("privacy") }]} />
          </>
        )}
      />
      <><div className="panel__scroll">
        {!compact ? (
        <>
        <div className="list-pad">
          <div className="row status-row">
            <button type="button" className="status-row__avatar" onClick={() => (myGroup ? openGroup([myGroup], 0) : fileRef.current?.click())} aria-label="My status">
              <Avatar src={me.profile?.profile_picture} name={me.profile?.display_name} size={46} ring={myGroup ? "seen" : undefined} />
              {!myGroup ? <span className="status-row__plus"><Plus size={14} strokeWidth={3} /></span> : null}
            </button>
            <button type="button" className="row__body status-row__body" onClick={() => (myGroup ? openGroup([myGroup], 0) : fileRef.current?.click())}>
              <span className="row__title">My status</span>
              <span className="row__subtitle">{myGroup ? `${mine.length} update${mine.length > 1 ? "s" : ""} · ${detailTime(myGroup.statuses.at(-1)?.created_at)}` : "Click to add status update"}</span>
            </button>
          </div>
        </div>

        {!loaded ? <div className="list-loading"><Spinner /></div> : null}

        {recent.length ? <div className="section-label section-label--plain">Recent</div> : null}
        <div className="list-pad">
          {recent.map((group, index) => (
            <button key={group.user.id} type="button" className="row status-row" onClick={() => openGroup(recent, index)}>
              <PresenceAvatar user={group.user} src={group.user.profile?.profile_picture} name={displayUserName(group.user, contactMap)} size={46} ring="new" />
              <span className="row__body">
                <span className="row__title">{displayUserName(group.user, contactMap)}</span>
                <span className="row__subtitle">{detailTime(group.statuses[0]?.created_at)}</span>
              </span>
            </button>
          ))}
        </div>

        {viewed.length ? <div className="section-label section-label--plain">Viewed</div> : null}
        <div className="list-pad">
          {viewed.map((group, index) => (
            <button key={group.user.id} type="button" className="row status-row" onClick={() => openGroup(viewed, index)}>
              <PresenceAvatar user={group.user} src={group.user.profile?.profile_picture} name={displayUserName(group.user, contactMap)} size={46} ring="seen" />
              <span className="row__body">
                <span className="row__title">{displayUserName(group.user, contactMap)}</span>
                <span className="row__subtitle">{detailTime(group.statuses[0]?.created_at)}</span>
              </span>
            </button>
          ))}
        </div>

        {loaded && !feed.length ? (
          <EmptyState text="No status updates from your contacts yet. Status updates disappear after 24 hours." />
        ) : null}
        <p className="info-muted info-pad status-foot"><Lock size={12} /> Status updates are only shown to the audience you choose.</p>
        </>
        ) : null}

        {/* Mobile Social follows the Facebook-style rhythm: composer, Stories,
            then the member post feed in one continuous scroll. */}
        {compact ? <div className="status-mobile-posts"><StatusMain storiesSlot={mobileStories} /></div> : null}
      </div>

      <input
        ref={fileRef}
        type="file"
        accept="image/*,video/*"
        multiple
        hidden
        onChange={async (event) => {
          const picked = [...(event.target.files || [])];
          event.target.value = "";
          const files = validateFiles(await normalizeFiles(picked), "media");
          if (!files.length) return;
          if (files.length > 10) {
            toast.error("Choose up to 10 items for one status update.");
            return;
          }
          if (files.some((file) => file.type.startsWith("video/")) && files.length > 1) {
            toast.error("Post videos individually. A multi-item status can contain up to 10 photos.");
            return;
          }
          if (files.some((file) => file.size > 50 * 1024 * 1024)) {
            toast.error("Each status media file must be 50 MB or smaller.");
            return;
          }
          setComposer({ mode: "media", files });
        }}
      />
      {addAnchor ? <Menu anchor={addAnchor} items={addItems} onClose={() => setAddAnchor(null)} /> : null}
      {composer ? <StatusComposer mode={composer.mode} initialFile={composer.file} initialFiles={composer.files} onClose={() => setComposer(null)} /> : null}
      {viewer ? <StatusViewer groups={viewer.groups} startGroup={viewer.start} startStatusId={viewer.startStatusId} onClose={() => { openingStatusId.current = null; setViewer(null); }} /> : null}
      </>
    </section>
  );
}

function StoryCardMedia({ status }) {
  const src = mediaUrl(status.media);
  return <>
    {status.status_type === "VIDEO"
      ? <video className="status-story__preview" src={src} muted playsInline preload="metadata" aria-hidden="true" tabIndex={-1} />
      : <img className="status-story__preview" src={src} alt="" loading="lazy" decoding="async" />}
    <span className="status-story__shade" aria-hidden="true" />
    {status.status_type === "VIDEO" ? <span className="status-story__video-indicator" aria-hidden="true"><Play size={18} fill="currentColor" /></span> : null}
  </>;
}
