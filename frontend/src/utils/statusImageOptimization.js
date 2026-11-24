const MAX_EDGE = 1920;
const MIN_BYTES_TO_OPTIMIZE = 1024 * 1024;

/**
 * Make camera photos cheaper to upload and render in Stories. Animated GIFs,
 * unsupported browsers and already-small images keep their original bytes.
 */
export async function optimizeStatusImage(file, {
  decode = globalThis.createImageBitmap,
  documentRef = globalThis.document,
} = {}) {
  if (!file?.type?.startsWith("image/") || file.type === "image/gif" || typeof decode !== "function" || !documentRef?.createElement) {
    return file;
  }

  let bitmap;
  try {
    bitmap = await decode(file, { imageOrientation: "from-image" });
    const longest = Math.max(bitmap.width, bitmap.height);
    if (longest <= MAX_EDGE && file.size <= MIN_BYTES_TO_OPTIMIZE) return file;

    const scale = Math.min(1, MAX_EDGE / longest);
    const canvas = documentRef.createElement("canvas");
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    const context = canvas.getContext("2d");
    if (!context) return file;
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);

    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/webp", 0.82));
    if (!blob || blob.size >= file.size * 0.95) return file;

    const outputType = blob.type || "image/png";
    const extension = outputType === "image/webp" ? "webp" : outputType === "image/jpeg" ? "jpg" : "png";
    const baseName = String(file.name || "story-image").replace(/\.[^.]+$/, "") || "story-image";
    return new File([blob], `${baseName}-optimized.${extension}`, {
      type: outputType,
      lastModified: file.lastModified || Date.now(),
    });
  } catch {
    // Optimization is a speed improvement, never a reason to block posting.
    return file;
  } finally {
    bitmap?.close?.();
  }
}
