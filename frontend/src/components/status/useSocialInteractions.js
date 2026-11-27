import { useEffect } from "react";
import { socialApi } from "../../api/endpoints";
import { realtime } from "../../services/realtime";

const WATCH_LIMIT = 60;

export default function useSocialInteractions(posts, setPosts) {
  // Track by ID, not by the array identity (each interaction update replaces the array).
  const watchKey = posts.map(({ id }) => id).slice(-WATCH_LIMIT).join(",");
  useEffect(() => {
    if (!watchKey) return undefined;
    const watchIds = watchKey.split(",").map(Number);
    const visible = new Set(watchIds);
    const pending = new Set();
    let active = true;
    let timer;
    let loading = false;

    const flush = async () => {
      timer = undefined;
      if (loading || !active || !pending.size) return;
      loading = true;
      const ids = [...pending];
      pending.clear();
      try {
        const changes = new Map((await socialApi.interactions(ids)).map((patch) => [Number(patch.id), patch]));
        if (active) setPosts((posts) => posts.map((post) => {
          const patch = changes.get(Number(post.id));
          return patch ? { ...post, ...patch } : post;
        }));
      } catch {
        // A temporary failure must not replace the currently readable feed with an error.
      } finally {
        loading = false;
        if (active && pending.size && !timer) timer = window.setTimeout(flush, 100);
      }
    };

    function onUpdate({ detail }) {
      if (!Array.isArray(detail)) return;
      for (const id of detail) if (visible.has(Number(id))) pending.add(Number(id));
      if (!loading && pending.size && !timer) timer = window.setTimeout(flush, 100);
    }

    window.addEventListener("mhtalk:social-interactions", onUpdate);
    realtime.watchSocialPosts(watchIds);
    return () => {
      active = false;
      window.clearTimeout(timer);
      window.removeEventListener("mhtalk:social-interactions", onUpdate);
      realtime.watchSocialPosts([]);
    };
  }, [watchKey, setPosts]);
}
