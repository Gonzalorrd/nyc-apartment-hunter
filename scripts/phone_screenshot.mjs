// Phone-width screenshot of the share site, with console errors printed.
// Usage: node scripts/phone_screenshot.mjs <url> <out.png> [width=390] [height=900] [waitMs=8000]
// Env: CHROME=<path to chrome>, SCROLL=<px to scroll before capture>, FULL=1 (whole page).
// Why: `chrome --headless --window-size` clamps layout to ~500 px and
// `--virtual-time-budget` never lets MapLibre (the plotly map) finish, so plain
// headless screenshots show clipped pages and blank maps. This drives Chrome over the
// DevTools protocol with a device-metrics override and real waiting instead.
import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [url, out, width = "390", height = "900", waitMs = "8000"] = process.argv.slice(2);
if (!url || !out) {
  console.error("Usage: node scripts/phone_screenshot.mjs <url> <out.png> [width] [height] [waitMs]");
  process.exit(2);
}
const chrome = process.env.CHROME ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
const port = 9333;
const browser = spawn(chrome, [
  "--headless=new",
  `--remote-debugging-port=${port}`,
  `--user-data-dir=${mkdtempSync(join(tmpdir(), "phone-shot-"))}`,
  "--use-angle=swiftshader",
  "--enable-unsafe-swiftshader", // software WebGL for the map
  "--hide-scrollbars",
  "about:blank",
]);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

let page;
for (let i = 0; i < 50 && !page; i++) {
  await sleep(200);
  try {
    const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
    page = targets.find((t) => t.type === "page");
  } catch {}
}
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve) => ws.addEventListener("open", resolve));
let nextId = 0;
const pending = new Map();
ws.addEventListener("message", (event) => {
  const msg = JSON.parse(event.data);
  if (msg.id && pending.has(msg.id)) {
    pending.get(msg.id)(msg.result);
    pending.delete(msg.id);
  }
  if (msg.method === "Runtime.exceptionThrown") {
    const details = msg.params.exceptionDetails;
    console.log("exception:", details.exception?.description ?? details.text);
  }
  if (msg.method === "Log.entryAdded" && msg.params.entry.level === "error") {
    console.log("error:", msg.params.entry.text, msg.params.entry.url ?? "");
  }
});
const send = (method, params = {}) =>
  new Promise((resolve) => {
    const id = ++nextId;
    pending.set(id, resolve);
    ws.send(JSON.stringify({ id, method, params }));
  });

await send("Runtime.enable");
await send("Log.enable");
await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", {
  width: Number(width),
  height: Number(height),
  deviceScaleFactor: 1,
  mobile: Number(width) < 600,
});
await send("Page.navigate", { url });
if (process.env.SCROLL) {
  await sleep(3000);
  await send("Runtime.evaluate", { expression: `window.scrollTo(0, ${Number(process.env.SCROLL)})` });
}
await sleep(Number(waitMs));
const layout = await send("Runtime.evaluate", {
  expression:
    "JSON.stringify({scrollWidth: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight})",
  returnByValue: true,
});
console.log("layout:", layout.result.value, "(scrollWidth > width means horizontal overflow)");
const shot = await send("Page.captureScreenshot", {
  format: "png",
  captureBeyondViewport: process.env.FULL === "1",
});
writeFileSync(out, Buffer.from(shot.data, "base64"));
ws.close();
browser.kill();
process.exit(0);
