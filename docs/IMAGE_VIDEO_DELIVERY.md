# Image and video delivery

## Current optimizations

- Chat photos are resized to a 1600 px longest edge and JPEG encoded before upload by default. The existing HD option preserves larger originals.
- Social posts and Stories convert large/high-resolution still photos to WebP at up to 1920 px on the longest edge. Animated GIFs remain unchanged.
- Off-screen feed, chat, and media-gallery videos start with no source attached. A shared `IntersectionObserver` attaches the URL when a preview comes within 300 px of the viewport; only then may the browser fetch metadata/preview data. Browsers without IntersectionObserver attach the source immediately as a compatibility fallback.
- Authorized Post and Story media endpoints support a single HTTP byte range and return `206 Partial Content`, allowing browsers to start/seek playback without downloading the complete file first. Signed viewer authorization is rechecked on each request. Responses remain private and non-cacheable.
- In-app camera video capture requests up to 720p and records at a target 1.5 Mbps video / 96 kbps audio. Browser codecs and devices can choose different effective settings. Gallery-selected videos are preserved as provided and are not silently transcoded.

## Production scaling path

The app has no asynchronous media transcoding/CDN rendition pipeline today. At higher traffic, add a background job that generates image thumbnails and adaptive video renditions (for example HLS) in object storage, then serve them through a range-capable CDN. Keep original uploads for download and use bounded variants for feed previews. That requires queue capacity, storage lifecycle policies, authorization-aware signed delivery, and cost monitoring; it should not be approximated by synchronous transcoding during an upload request.

Do not claim that this release transcodes gallery videos or produces adaptive video renditions.
