import { useState } from "react";
import { Check, Users } from "lucide-react";
import { errorMessage } from "../../api/client";
import { chatApi } from "../../api/endpoints";
import { toast } from "../../services/toast";
import { PanelHeader, Spinner } from "../common/ui";
import { useApp } from "../layout/AppContext";

const CATEGORIES = [
  ["GENERAL", "General"], ["EDUCATION", "Education"], ["GAMING", "Gaming"], ["LOCAL", "Local and lifestyle"],
  ["TECH", "Technology"], ["BUSINESS", "Business"], ["ENTERTAINMENT", "Entertainment"], ["OTHER", "Other"],
];

export default function OpenCommunityCreatePanel() {
  const app = useApp();
  const [form, setForm] = useState({ name: "", description: "", category: "GENERAL", join_mode: "OPEN", join_code: "", display_name: "", guidelines: "", tags: "" });
  const [busy, setBusy] = useState(false);
  const update = (field) => (event) => setForm((current) => ({ ...current, [field]: event.target.value }));

  async function create(event) {
    event.preventDefault();
    if (form.join_mode === "CODE" && form.join_code.trim().length < 4) {
      toast.error("Choose a community-only access code with at least 4 characters.");
      return;
    }
    setBusy(true);
    try {
      await chatApi.createOpenCommunity({ ...form, tags: form.tags.split(",").map((tag) => tag.trim()).filter(Boolean) });
      window.dispatchEvent(new Event("mhtalk:openchat-updated"));
      toast.success("Community submitted for review. It will appear in discovery after approval.");
      app.popPanel();
    } catch (error) {
      toast.error(errorMessage(error, "Couldn't create the community."));
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <PanelHeader title="Create OpenChat" onBack={app.popPanel} variant="sub" />
      <form className="panel__scroll openchat-create" onSubmit={create}>
        <div className="openchat-create__intro"><Users size={21} /><span>Create a community around a topic. Your account profile stays separate from the community name you choose.</span></div>
        <div className="field">
          <label htmlFor="openchat-name">Community name</label>
          <input id="openchat-name" required maxLength={80} value={form.name} onChange={update("name")} placeholder="e.g. Chiang Mai hikers" />
        </div>
        <div className="field">
          <label htmlFor="openchat-description">Description</label>
          <textarea id="openchat-description" required maxLength={255} rows={3} value={form.description} onChange={update("description")} placeholder="What will members talk about?" />
        </div>
        <div className="field">
          <label htmlFor="openchat-category">Category</label>
          <select id="openchat-category" value={form.category} onChange={update("category")}>{CATEGORIES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
        </div>
        <div className="field">
          <label htmlFor="openchat-guidelines">Community guidelines</label>
          <textarea id="openchat-guidelines" maxLength={3000} rows={4} value={form.guidelines} onChange={update("guidelines")} placeholder="Share a few clear rules for members." />
        </div>
        <div className="field">
          <label htmlFor="openchat-tags">Search tags</label>
          <input id="openchat-tags" value={form.tags} onChange={update("tags")} placeholder="Separate tags with commas" />
        </div>
        <div className="field">
          <label htmlFor="openchat-access">Who can join?</label>
          <select id="openchat-access" value={form.join_mode} onChange={update("join_mode")}>
            <option value="OPEN">Anyone can join</option>
            <option value="CODE">Join with a community code</option>
            <option value="APPROVAL">Ask an admin to approve</option>
          </select>
        </div>
        {form.join_mode === "CODE" ? <div className="field"><label htmlFor="openchat-code">Community access code</label><input id="openchat-code" required minLength={4} maxLength={32} value={form.join_code} onChange={update("join_code")} autoComplete="new-password" /></div> : null}
        <div className="field">
          <label htmlFor="openchat-profile-name">Your name in this community</label>
          <input id="openchat-profile-name" maxLength={50} value={form.display_name} onChange={update("display_name")} placeholder="Optional; your account name is not shown by default" />
        </div>
        <p className="field__hint">New communities are reviewed before they appear in public discovery. Existing private groups are not changed.</p>
        <button type="submit" className="btn btn--primary openchat-create__submit" disabled={busy || !form.name.trim() || !form.description.trim()}>
          {busy ? <Spinner size={18} /> : <Check size={18} />} Submit community
        </button>
      </form>
    </section>
  );
}
