import { useEffect, useState } from "react";
import { ArrowUpRight } from "lucide-react";
import { socialApi } from "../../api/endpoints";
import { mediaUrl, errorMessage } from "../../api/client";
import { Spinner } from "../common/ui";

export default function SocialPostCard({ postId, onOpen }) {
  const [state, setState] = useState({ loading: true, post: null, error: "" });

  useEffect(() => {
    let active = true;
    socialApi.post(postId).then((post) => {
      if (active) setState({ loading: false, post, error: "" });
    }).catch((error) => {
      if (active) setState({ loading: false, post: null, error: errorMessage(error, "This post is unavailable.") });
    });
    return () => { active = false; };
  }, [postId]);

  if (state.loading) return <div className="chat-shared-post chat-shared-post--loading"><Spinner size={16} /> Loading shared post…</div>;
  if (!state.post) return <div className="chat-shared-post chat-shared-post--unavailable">This post is no longer available to you.</div>;

  const post = state.post;
  const author = post.author?.profile?.display_name || post.author?.public_id || "SatoshiCore member";
  const attachment = post.attachments?.[0];
  return (
    <article className="chat-shared-post">
      <strong>{author} · SatoshiCore post</strong>
      {post.text ? <p>{post.text}</p> : null}
      {post.image ? <img src={mediaUrl(post.image)} alt="Shared post attachment" loading="lazy" decoding="async" /> : attachment?.kind === "VIDEO" ? <video src={mediaUrl(attachment.url)} controls playsInline preload="none" /> : attachment ? <img src={mediaUrl(attachment.url)} alt="Shared post attachment" loading="lazy" decoding="async" /> : null}
      <button type="button" onClick={onOpen}>Open in Updates <ArrowUpRight size={15} /></button>
    </article>
  );
}
