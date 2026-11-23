import { useEffect, useState } from "react";
import { contactsApi } from "../../api/endpoints";
import { errorMessage } from "../../api/client";
import { loadContacts } from "../../store/actions";
import { toast } from "../../services/toast";
import { profileName } from "../../utils/messages";
import { Avatar, Modal, Spinner } from "../common/ui";
import { navigate } from "../../router";

/** /add/<public-id>: add a person from their share link or QR code. */
export default function AddFriendDialog({ publicId }) {
  const [state, setState] = useState({ loading: true, user: null, saved: null, error: "" });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    contactsApi.lookup(`@${publicId}`).then((data) => {
      if (!cancelled) setState({ loading: false, user: data.user, saved: data.saved_contact, isSelf: data.is_self, error: "" });
    }).catch((error) => {
      if (!cancelled) setState({ loading: false, user: null, saved: null, error: errorMessage(error, "This friend link is unavailable.") });
    });
    return () => { cancelled = true; };
  }, [publicId]);

  const close = () => navigate("/", { replace: true });
  async function add() {
    if (!state.user) return;
    setBusy(true);
    try {
      await contactsApi.createByPublicId(profileName(state.user) || "", state.user.public_id);
      await loadContacts();
      toast.success("Friend added to your contacts");
      close();
    } catch (error) { toast.error(errorMessage(error)); setBusy(false); }
  }

  return (
    <Modal
      title="Add friend"
      onClose={busy ? undefined : close}
      width={380}
      footer={state.user ? <>
        <button type="button" className="btn btn--ghost" onClick={close} disabled={busy}>Cancel</button>
        <button type="button" className="btn btn--primary" onClick={add} disabled={busy || Boolean(state.saved) || state.isSelf}>
          {busy ? <Spinner size={16} /> : state.isSelf ? "This is you" : state.saved ? "Already added" : "Add friend"}
        </button>
      </> : !state.loading ? <button type="button" className="btn btn--primary" onClick={close}>Close</button> : null}
    >
      {state.loading ? <div className="join-group__loading"><Spinner /></div> : state.user ? (
        <div className="join-group__preview">
          <Avatar src={state.user.profile?.profile_picture} name={profileName(state.user)} size={96} />
          <h2 className="join-group__name">{profileName(state.user) || `@${state.user.public_id}`}</h2>
          <p className="join-group__meta">SatoshiCore · @{state.user.public_id}</p>
          {state.isSelf ? <p className="join-group__members">This link opens your own account.</p> : null}
          {state.saved ? <p className="join-group__members">Already in your contacts as {state.saved.name || "this friend"}.</p> : null}
        </div>
      ) : <p className="modal__text">{state.error}</p>}
    </Modal>
  );
}
