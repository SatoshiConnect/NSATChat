/**
 * Sponsored-content surface for first-party campaign inventory.
 * Empty placements remain hidden until a real, moderated campaign is supplied.
 * Do not render third-party HTML or tracking pixels here.
 */
export default function AdPlacement({ placement, creative = null }) {
  if (!creative?.title || !creative?.href) {
    return <div data-ad-placement={placement} hidden aria-hidden="true" />;
  }

  const parsedHref = (() => {
    try {
      const url = new URL(creative.href, window.location.origin);
      return url.protocol === "https:" || url.origin === window.location.origin ? url : null;
    } catch {
      return null;
    }
  })();
  if (!parsedHref) return <div data-ad-placement={placement} hidden aria-hidden="true" />;
  const safeImage = (() => {
    if (!creative.image) return "";
    try {
      const url = new URL(creative.image, window.location.origin);
      return url.protocol === "https:" || url.origin === window.location.origin ? url.href : "";
    } catch {
      return "";
    }
  })();

  return (
    <aside className="ad-placement" data-ad-placement={placement} aria-label="Sponsored">
      {safeImage ? <img src={safeImage} alt="" loading="lazy" /> : null}
      <div className="ad-placement__copy">
        <span>Sponsored</span>
        <strong>{creative.title}</strong>
        {creative.description ? <p>{creative.description}</p> : null}
      </div>
      <a href={parsedHref.href} target={parsedHref.origin === window.location.origin ? undefined : "_blank"} rel="noreferrer">
        {creative.action || "Learn more"}
      </a>
    </aside>
  );
}
