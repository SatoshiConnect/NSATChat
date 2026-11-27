import { useState } from "react";
import { createRoot } from "react-dom/client";
import { realtime } from "../../src/services/realtime";
import useSocialInteractions from "../../src/components/status/useSocialInteractions";

export function Fixture() {
  const [posts, setPosts] = useState([{ id: 41, comments: [], comments_count: 0 }, { id: 42, comments: [], comments_count: 0 }]);
  useSocialInteractions(posts, setPosts);
  return posts.map((post) => <section key={post.id} aria-label={`Post ${post.id}`}>
    <p>{post.comments_count} comments</p>
    {post.comments.map((comment) => <p key={comment.id}>{comment.text}</p>)}
  </section>);
}
realtime.start();
createRoot(document.getElementById("root")).render(<Fixture />);
