import test from "node:test";
import assert from "node:assert/strict";
import { optimizeStatusImage } from "./statusImageOptimization.js";

test("leaves animated GIFs and unsupported files untouched", async () => {
  const gif = { name: "loop.gif", type: "image/gif", size: 8_000_000 };
  const pdf = { name: "doc.pdf", type: "application/pdf", size: 8_000_000 };
  assert.equal(await optimizeStatusImage(gif), gif);
  assert.equal(await optimizeStatusImage(pdf), pdf);
});

test("shrinks large camera photos and releases decoded image memory", async () => {
  const source = { name: "camera.jpg", type: "image/jpeg", size: 4_000_000, lastModified: 123 };
  let closed = false;
  let drawnSize;
  const result = await optimizeStatusImage(source, {
    decode: async () => ({ width: 4000, height: 3000, close: () => { closed = true; } }),
    documentRef: {
      createElement: () => ({
        getContext: () => ({ drawImage: (_bitmap, _x, _y, width, height) => { drawnSize = [width, height]; } }),
        toBlob: (callback, type) => callback(new Blob([new Uint8Array(400_000)], { type })),
      }),
    },
  });
  assert.equal(closed, true);
  assert.deepEqual(drawnSize, [1920, 1440]);
  assert.equal(result.type, "image/webp");
  assert.equal(result.name, "camera-optimized.webp");
  assert.equal(result.size, 400_000);
});

test("keeps the original if the browser cannot decode or encode the image", async () => {
  const source = { name: "camera.jpg", type: "image/jpeg", size: 3_000_000 };
  assert.equal(await optimizeStatusImage(source, { decode: null }), source);
  assert.equal(await optimizeStatusImage(source, { decode: async () => { throw new Error("decode failed"); } }), source);
});
