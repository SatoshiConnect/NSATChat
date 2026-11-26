import { useEffect, useMemo, useState } from "react";
import { Volume2, Bell, ChevronRight, CircleHelp, Download, Database, Keyboard, KeyRound, Lock, LogOut, MessageSquareText, Palette, Search, Share, ShoppingBag, SquarePlus, UserX, RefreshCw, WalletCards } from "lucide-react";
import { useStore } from "../../store/store";
import { loadBlocked, setBlocked } from "../../store/actions";
import { getNotificationPrefs, requestDesktopPermission, setNotificationPrefs } from "../../services/notify";
import { toast } from "../../services/toast";
import { testSound } from "../../services/sounds";
import { getInstallState, promptInstall, subscribeInstall } from "../../services/pwa";
import { disableBackgroundPush, enableBackgroundPush, pushSupported, syncBackgroundPush } from "../../services/push";
import { THEME_OPTIONS, getThemePref, setThemePref } from "../../services/theme";
import { contactsByUser, displayUserName } from "../../utils/messages";
import { formatPhone } from "../../utils/phone";
import { Avatar, EmptyState, Modal, PanelHeader, SearchInput, Toggle } from "../common/ui";
import { confirmAction } from "../common/dialogs";
import { useApp } from "../layout/AppContext";
import { AccountView, PrivacyView } from "./PrivacySettings";
import AppUpdateView from "./AppUpdateView";
import { APP_VERSION, takeOpenUpdate, useAppUpdate } from "../../services/appUpdate";
import { clearOfflineData } from "../../services/offlineCache";

const WALLET_UI_ENABLED = import.meta.env.VITE_FEATURE_WALLET_UI !== "false";

const SHORTCUTS = [
  ["New chat", "Ctrl + Alt + N"],
  ["Send message", "Enter"],
  ["New line", "Shift + Enter"],
  ["Edit last message", "↑ (empty input)"],
  ["Close menu / cancel reply", "Esc"],
  ["Next / previous photo", "→ / ←"],
  ["Pause status", "Space"],
];

function SettingRow({ icon: Icon, title, subtitle, onClick, danger, dot }) {
  return (
    <button type="button" className={`settings-row ${danger ? "is-danger" : ""}`} onClick={onClick}>
      <span className="settings-row__icon">
        <Icon size={22} />
        {dot ? <span className="settings-row__dot" aria-label="New" /> : null}
      </span>
      <span className="settings-row__body">
        <span className="settings-row__title">{title}</span>
        {subtitle ? <span className="settings-row__subtitle">{subtitle}</span> : null}
      </span>
      {!danger ? <ChevronRight size={18} className="settings-row__chevron" /> : null}
    </button>
  );
}

function ToggleRow({ title, subtitle, checked, onChange, disabled }) {
  return (
    <div className={`settings-toggle ${disabled ? "is-disabled" : ""}`}>
      <span className="settings-row__body">
        <span className="settings-row__title">{title}</span>
        {subtitle ? <span className="settings-row__subtitle">{subtitle}</span> : null}
      </span>
      <Toggle checked={checked} onChange={disabled ? () => {} : onChange} label={title} />
    </div>
  );
}

function ThemeDialog({ onClose }) {
  const [value, setValue] = useState(getThemePref);
  return (
    <Modal
      title="Theme"
      onClose={onClose}
      width={400}
      footer={
        <>
          <button type="button" className="btn btn--ghost" onClick={onClose}>Cancel</button>
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => {
              setThemePref(value);
              onClose();
            }}
          >
            OK
          </button>
        </>
      }
    >
      <div className="radio-list" role="radiogroup" aria-label="Theme">
        {THEME_OPTIONS.map((option) => (
          <label key={option.value} className={`radio ${value === option.value ? "is-checked" : ""}`}>
            <input type="radio" name="theme" checked={value === option.value} onChange={() => setValue(option.value)} />
            <span className="radio__dot" />
            <span className="radio__text">
              <span>{option.label}</span>
            </span>
          </label>
        ))}
      </div>
    </Modal>
  );
}

function InstallDialog({ ios, onClose }) {
  return (
    <Modal title="Install SatoshiCore" onClose={onClose} width={420}>
      {ios ? (
        <ol className="install-steps">
          <li>
            Tap <Share size={18} aria-label="Share" /> <strong>Share</strong> in Safari&apos;s toolbar.
          </li>
          <li>
            Choose <SquarePlus size={18} aria-hidden="true" /> <strong>Add to Home Screen</strong>.
          </li>
          <li>Tap <strong>Add</strong>. SatoshiCore opens full screen from your home screen.</li>
        </ol>
      ) : (
        <ol className="install-steps">
          <li>Open your browser&apos;s menu (⋮ or the install icon in the address bar).</li>
          <li>
            Choose <strong>Install app</strong> or <strong>Add to Home screen</strong>.
          </li>
          <li>SatoshiCore then opens in its own window, like a native app.</li>
        </ol>
      )}
    </Modal>
  );
}

const THEME_LABELS = Object.fromEntries(THEME_OPTIONS.map((option) => [option.value, option.label]));

function BlockedView({ onBack }) {
  const blocked = useStore((state) => state.blocked);
  const rooms = useStore((state) => state.rooms);
  const contacts = useStore((state) => state.contacts);
  const contactMap = useMemo(() => contactsByUser(contacts), [contacts]);
  useEffect(() => {
    loadBlocked();
  }, []);
  const users = blocked.map((id) => Object.values(rooms).find((room) => Number(room.otherUser?.id) === id)?.otherUser || contactMap.get(id)?.contact_user || { id, phone_number: `User #${id}` });
  return (
    <section className="panel">
      <PanelHeader title="Blocked contacts" onBack={onBack} variant="sub" />
      <div className="panel__scroll">
        <p className="info-muted info-pad">Blocked contacts can no longer call you or send you messages.</p>
        {!users.length ? <EmptyState icon={UserX} text="No blocked contacts" /> : null}
        <div className="list-pad">
          {users.map((user) => (
            <div key={user.id} className="row row--static">
              <Avatar src={user.profile?.profile_picture} name={displayUserName(user, contactMap)} size={44} />
              <span className="row__body">
                <span className="row__title">{displayUserName(user, contactMap)}</span>
                <span className="row__subtitle">{formatPhone(user.phone_number)}</span>
              </span>
              <button type="button" className="btn btn--ghost" onClick={() => setBlocked(user.id, false)}>Unblock</button>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/** Settings (WhatsApp Web style list). */
export default function SettingsPanel() {
  const app = useApp();
  const me = useStore((state) => state.me);
  const blockedCount = useStore((state) => state.blocked.length);
  // Opened from the "new version" toast → straight to App update.
  const [view, setView] = useState(() => (takeOpenUpdate() ? "update" : "main"));
  const appUpdate = useAppUpdate();
  useEffect(() => {
    const open = () => {
      takeOpenUpdate();
      setView("update");
    };
    window.addEventListener("mhtalk:open-update", open);
    return () => window.removeEventListener("mhtalk:open-update", open);
  }, []);
  const [prefs, setPrefs] = useState(getNotificationPrefs);
  const [query, setQuery] = useState("");
  const [modal, setModal] = useState(null);
  const [themePref, setThemePrefState] = useState(getThemePref);
  const [install, setInstall] = useState(getInstallState);
  const [pushBusy, setPushBusy] = useState(false);

  useEffect(() => subscribeInstall(setInstall), []);

  const update = (patch) => setPrefs(setNotificationPrefs(patch));

  const onInstall = async () => {
    if (install.installed) {
      toast("SatoshiCore is already installed on this device.");
      return;
    }
    if (install.canPrompt) {
      const outcome = await promptInstall();
      if (outcome === "accepted") toast.success("Installing SatoshiCore…");
      return;
    }
    setModal(install.ios ? "install-ios" : "install");
  };

  const onBackgroundPush = async (value) => {
    setPushBusy(true);
    try {
      if (value) {
        await enableBackgroundPush();
        toast.success("Background notifications are on.");
      } else {
        await disableBackgroundPush();
      }
      setPrefs(getNotificationPrefs());
    } catch (error) {
      toast.error(error.message);
      setPrefs(setNotificationPrefs({ backgroundPush: false }));
    } finally {
      setPushBusy(false);
    }
  };

  if (view === "blocked") return <BlockedView onBack={() => setView("privacy")} />;

  if (view === "privacy") {
    return (
      <PrivacyView
        onBack={() => setView("main")}
        blockedCount={blockedCount}
        onOpenBlocked={() => setView("blocked")}
        onOpenStatus={() => app.setSection("status")}
      />
    );
  }

  if (view === "account") return <AccountView onBack={() => setView("main")} />;

  if (view === "notifications") {
    return (
      <section className="panel">
        <PanelHeader title="Notifications" onBack={() => setView("main")} variant="sub" />
        <div className="panel__scroll">
          <ToggleRow title="Sounds" subtitle="Play a sound for incoming messages" checked={prefs.sound} onChange={(value) => update({ sound: value })} />
          <div className="settings-test-sound">
            <button
              type="button"
              className="btn btn--outline"
              onClick={async () => {
                const ok = await testSound();
                if (!ok) toast.error("This browser blocked the sound. Check that the tab / site isn't muted.");
              }}
            >
              <Volume2 size={18} /> Test sound
            </button>
            <span>No sound? Right-click the SatoshiCore tab → <b>Unmute site</b>, and in the address bar → site settings → <b>Sound: Allow</b>.</span>
          </div>
          <ToggleRow
            title="Desktop notifications"
            subtitle="Show notifications when SatoshiCore is in the background"
            checked={prefs.desktop}
            onChange={async (value) => {
              if (value) {
                const permission = await requestDesktopPermission();
                if (permission !== "granted") {
                  toast.error("Notifications are blocked by your browser for this site.");
                  return;
                }
              }
              update({ desktop: value });
            }}
          />
          <ToggleRow
            title="Background notifications"
            subtitle={pushSupported() ? "Get messages and calls even when SatoshiCore is closed" : "Not supported by this browser"}
            checked={Boolean(prefs.backgroundPush)}
            disabled={pushBusy || !pushSupported()}
            onChange={onBackgroundPush}
          />
          <ToggleRow
            title="Show previews"
            subtitle="Display message text in notifications"
            checked={prefs.preview}
            onChange={(value) => {
              update({ preview: value });
              syncBackgroundPush();
            }}
          />
        </div>
      </section>
    );
  }

  if (view === "update") {
    return <AppUpdateView onBack={() => setView("main")} />;
  }

  if (view === "chats") {
    return (
      <section className="panel">
        <PanelHeader title="Chats" onBack={() => setView("main")} variant="sub" />
        <div className="panel__scroll">
          <div className="section-label section-label--muted">Display</div>
          <SettingRow icon={Palette} title="Theme" subtitle={THEME_LABELS[themePref]} onClick={() => setModal("theme")} />
          <div className="section-label section-label--muted">Chat settings</div>
          <ToggleRow title="Enter is send" subtitle="Enter key will send your message (Shift+Enter for a new line)" checked={prefs.enterToSend} onChange={(value) => update({ enterToSend: value })} />
        </div>
        {modal === "theme" ? (
          <ThemeDialog
            onClose={() => {
              setModal(null);
              setThemePrefState(getThemePref());
            }}
          />
        ) : null}
      </section>
    );
  }

  const rows = [
    { key: "account", icon: KeyRound, title: "Account", subtitle: "Phone number, delete account", onClick: () => setView("account") },
    { key: "privacy", icon: Lock, title: "Privacy", subtitle: "Last seen, profile photo, read receipts, blocked contacts", onClick: () => setView("privacy") },
    { key: "chats", icon: MessageSquareText, title: "Chats", subtitle: "Theme, Enter is send", onClick: () => setView("chats") },
    ...(!app.compact ? [{ key: "wallet", icon: WalletCards, title: "Wallet", subtitle: "View NSAT balance and public transaction history", onClick: () => app.setSection("wallet") }] : []),
    { key: "offline", icon: Database, title: "Offline data", subtitle: "Saved chats and media on this device", onClick: () => setModal("offline") },
    { key: "notifications", icon: Bell, title: "Notifications", subtitle: "Message sounds, desktop alerts", onClick: () => setView("notifications") },
    !install.installed
      ? { key: "install", icon: Download, title: "Install app", subtitle: install.ios ? "Add SatoshiCore to your Home Screen" : "Use SatoshiCore like a native app", onClick: onInstall }
      : null,
    { key: "shortcuts", icon: Keyboard, title: "Keyboard shortcuts", subtitle: "Quick actions", onClick: () => setModal("shortcuts") },
    {
      key: "update",
      icon: RefreshCw,
      title: "App update",
      subtitle: appUpdate.available ? "New version available — see what's new" : `Version ${APP_VERSION} · up to date`,
      dot: appUpdate.available,
      onClick: () => setView("update"),
    },
    { key: "help", icon: CircleHelp, title: "Help", subtitle: "About SatoshiCore", onClick: () => setModal("help") },
  ].filter((row) => row && (!query || `${row.title} ${row.subtitle}`.toLowerCase().includes(query.toLowerCase())));

  return (
    <section className="panel settings-panel">
      <PanelHeader title="Settings" />
      <SearchInput value={query} onChange={setQuery} placeholder="Search settings" />
      <div className="panel__scroll">
        <button type="button" className="settings-profile" onClick={() => app.setSection("profile")}>
          <Avatar src={me.profile?.profile_picture} name={me.profile?.display_name} size={64} />
          <span className="settings-row__body">
            <span className="settings-profile__name">{me.profile?.display_name || formatPhone(me.phone_number)}</span>
            <span className="settings-row__subtitle">{me.public_id ? `@${me.public_id}` : me.profile?.about}</span>
          </span>
        </button>
        {app.compact ? <SettingRow icon={WalletCards} title="Wallet & Marketplace" subtitle="NSAT balance, activity and creator items" onClick={() => app.setSection(WALLET_UI_ENABLED ? "wallet" : "marketplace")} /> : null}
        {rows.map((row) => (
          <SettingRow key={row.key} icon={row.icon} title={row.title} subtitle={row.subtitle} dot={row.dot} onClick={row.onClick} />
        ))}
        {!app.compact ? <SettingRow icon={ShoppingBag} title="Creator marketplace" subtitle="Gifts, stickers and digital items" onClick={() => app.setSection("marketplace")} /> : null}
        {!rows.length ? <EmptyState icon={Search} text="No settings found" /> : null}
        <SettingRow
          icon={LogOut}
          title="Log out"
          danger
          onClick={() => confirmAction({ title: "Log out?", message: "You can log back in with your phone number and password.", confirmLabel: "Log out", danger: true, onConfirm: app.onLogout })}
        />
      </div>

      {modal === "shortcuts" ? (
        <Modal title="Keyboard shortcuts" onClose={() => setModal(null)} width={460}>
          <div className="shortcuts">
            {SHORTCUTS.map(([label, keys]) => (
              <div key={label} className="shortcuts__row">
                <span>{label}</span>
                <kbd>{keys}</kbd>
              </div>
            ))}
          </div>
        </Modal>
      ) : null}
      {modal === "install" || modal === "install-ios" ? <InstallDialog ios={modal === "install-ios"} onClose={() => setModal(null)} /> : null}
      {modal === "help" ? (
        <Modal title="SatoshiCore" onClose={() => setModal(null)} width={420}>
          <p className="modal__text">
            SatoshiCore is a real-time messaging app built with Django Channels and React. Messages, receipts, typing, presence,
            statuses and calls sync live across all of your open tabs.
          </p>
        </Modal>
      ) : null}
      {modal === "offline" ? (
        <Modal title="Offline data" onClose={() => setModal(null)} width={440}>
          <p className="modal__text">
            Recent chats, messages and small previews of chat photos and videos are saved on this device. To keep a full clip, open it and choose “Save video offline” while connected. You can keep up to 3 clips (20 MB each, 40 MB total). Sending new messages still needs internet. Your browser may remove saved data to free space. Logging out clears this device&apos;s saved chat data.
          </p>
          <button
            type="button"
            className="btn btn--outline"
            onClick={() => confirmAction({
              title: "Clear saved offline data?",
              message: "This clears local chat snapshots, cached photos and video previews from this device. It does not delete messages from your account.",
              confirmLabel: "Clear saved data",
              danger: true,
              onConfirm: async () => {
                await clearOfflineData(me.id);
                toast.success("Saved offline data cleared from this device.");
                setModal(null);
              },
            })}
          >
            Clear saved data
          </button>
        </Modal>
      ) : null}
    </section>
  );
}
