import { createRoot } from "react-dom/client";
import { useState } from "react";
import Lightbox from "../../src/components/media/Lightbox";
import "../../src/styles/media.css";

const fixture = (name, id) => ({
  message: { id, sender: { id: 1 }, created_at: "2026-01-01T00:00:00Z" },
  attachment: { id, file: `/qa-video/${name}`, file_name: name, mime_type: "video/mp4" },
});
const items = [fixture("one.mp4", 1), fixture("two.mp4", 2)];

export function Fixture() {
  const [opened, setOpened] = useState(false);
  return <>
    <button onClick={() => setOpened(true)}>Play received attachment</button>
    {opened ? <Lightbox items={items} nameOf={() => "Test sender"} onClose={() => setOpened(false)} /> : null}
  </>;
}
createRoot(document.getElementById("root")).render(<Fixture />);
