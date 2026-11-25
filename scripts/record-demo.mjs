// Records the README hero GIF from a running demo: `hydra-mcp demo --no-open`, then
//
//   node scripts/record-demo.mjs "http://127.0.0.1:8765/admin/#token=..."   [out.gif]
//
// Needs Playwright (npm i -D playwright && npx playwright install chromium) and ffmpeg.
// The scene: two Demo Tracker workspaces are connected; we add a third through the provider's
// own sign-in page, name it, and give a client read access to it; then the tool calls an AI app
// makes. Every click goes through the real admin page and the real OAuth flow, and the last
// scene prints real responses from the running proxy (only their display is styled here).
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

// require() (not import) so a globally installed Playwright (NODE_PATH) is found too.
const { chromium } = createRequire(import.meta.url)("playwright");

const adminUrl = process.argv[2];
const out = resolve(process.argv[3] ?? "docs/assets/demo.gif");
if (!adminUrl || !adminUrl.includes("#token=")) {
  console.error('usage: node scripts/record-demo.mjs "<admin link printed by hydra-mcp demo>" [out.gif]');
  process.exit(2);
}
const size = { width: 1180, height: 660 };
const videoDir = mkdtempSync(join(tmpdir(), "hydra-demo-video-"));
const pause = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await chromium.launch(
  process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {},
);
const context = await browser.newContext({
  viewport: size,
  recordVideo: { dir: videoDir, size },
  colorScheme: "light",
});
const page = await context.newPage();

// A visible cursor: headless video has none, and the viewer needs to follow the clicks.
await context.addInitScript(() => {
  addEventListener("DOMContentLoaded", () => {
    const dot = document.createElement("div");
    dot.id = "__cursor";
    Object.assign(dot.style, {
      position: "fixed", zIndex: 99999, width: "18px", height: "18px", borderRadius: "50%",
      background: "rgba(107,92,255,.35)", border: "2px solid #6b5cff", pointerEvents: "none",
      transform: "translate(-50%,-50%)", transition: "left .35s ease, top .35s ease",
      left: sessionStorage.getItem("cx") || "-40px", top: sessionStorage.getItem("cy") || "-40px",
    });
    document.body.appendChild(dot);
    addEventListener("mousemove", (e) => {
      dot.style.left = e.clientX + "px"; dot.style.top = e.clientY + "px";
      sessionStorage.setItem("cx", dot.style.left); sessionStorage.setItem("cy", dot.style.top);
    });
  });
});

async function moveTo(locator) {
  const box = await locator.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 12 });
  await pause(350);
}
async function click(locator, wait = 900) {
  await moveTo(locator);
  await locator.click();
  await pause(wait);
}

// 1. Connections: two accounts of the same service, side by side.
await page.goto(adminUrl); // logs in (the token is in the fragment), then
await page.waitForTimeout(500);
await page.evaluate(() => (window.location.hash = "connections"));
await page.getByText("+ Add another account").waitFor();
await pause(2200);

// 2. Add a third: the provider's own sign-in page, pick the workspace.
await click(page.getByText("+ Add another account"), 300);
await page.getByText("Sign in to Demo Tracker").waitFor();
await pause(1500);
await click(page.locator('button[data-workspace="initech"]'), 300);

// 3. Back in hydra-mcp: name the new account.
await page.getByText(/Connected/).first().waitFor();
await pause(1200);
const save = page.getByRole("button", { name: /save|done|keep/i }).first();
await click(save, 1500);

// 4. Clients: drag the new account into the client, read only.
await page.evaluate(() => (window.location.hash = "clients"));
await page.getByText("Claude Code (demo)").first().waitFor();
await pause(1500);
const chip = page.locator("[draggable=true]", { hasText: "initech" }).first();
const zone = page.locator(".zone", { hasText: "Read only" }).first();
await moveTo(chip);
await chip.dragTo(zone);
await page.mouse.move((await zone.boundingBox()).x + 60, (await zone.boundingBox()).y + 40, { steps: 12 });
await pause(2500);

// 5. What the AI sees: one tool, an `account` argument, each account answering with its own data.
// Real requests to the running proxy with the demo client's key (rotated for the recording).
const base = new URL(adminUrl).origin;
const adminToken = decodeURIComponent(adminUrl.split("#token=")[1]);
const { key } = await (
  await fetch(`${base}/admin/api/clients/claude-code-demo/key`, {
    method: "POST",
    headers: { Authorization: `Bearer ${adminToken}` },
  })
).json();
async function rpc(method, params) {
  const r = await fetch(`${base}/mcp`, {
    method: "POST",
    headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
  });
  return (await r.json()).result;
}
const tools = (await rpc("tools/list", {})).tools;
const search = tools.find((t) => t.name === "demo__search_issues");
const issues = async (account) =>
  JSON.parse((await rpc("tools/call", { name: search.name, arguments: { account, status: "open" } })).content[0].text)
    .issues.map((i) => `${i.key}  ${i.title}`);
const lines = [
  ["dim", "# what your AI app sees through hydra-mcp"],
  ["cmd", "tools/list"],
  ["out", `${search.name}(account: ${search.inputSchema.properties.account.enum.map((a) => `"${a}"`).join(" | ")}, query, status)`],
  ["gap", ""],
  ["cmd", 'demo__search_issues(account: "acme", status: "open")'],
  ...(await issues("acme")).map((l) => ["out", l]),
  ["gap", ""],
  ["cmd", 'demo__search_issues(account: "initech", status: "open")'],
  ...(await issues("initech")).map((l) => ["out", l]),
];
await page.setContent(`<!doctype html><meta charset="utf-8"><style>
  body{margin:0;height:100vh;display:grid;place-items:center;background:#f4f4f6;font:15px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace}
  .term{width:960px;background:#17171c;color:#e6e6ee;border-radius:12px;box-shadow:0 10px 40px #0003;overflow:hidden}
  .bar{height:34px;background:#24242b;display:flex;align-items:center;gap:8px;padding:0 14px}
  .bar i{width:12px;height:12px;border-radius:50%;display:block}
  pre{margin:0;padding:18px 22px;min-height:400px;white-space:pre-wrap}
  .cmd{color:#a99dff}.cmd::before{content:"› ";color:#6b6b75}.dim{color:#6b6b75}.out{color:#d7d7e0}
</style><div class="term"><div class="bar"><i style="background:#ff5f57"></i><i style="background:#febc2e"></i><i style="background:#28c840"></i></div><pre id="t"></pre></div>`);
for (const [kind, text] of lines) {
  await page.evaluate(([kind, text]) => {
    const span = document.createElement("div");
    span.className = kind;
    span.textContent = text || " ";
    document.getElementById("t").appendChild(span);
  }, [kind, text]);
  await pause(kind === "cmd" ? 700 : kind === "gap" ? 150 : 260);
}
await pause(3500);

await context.close(); // flushes the video
await browser.close();

const webm = join(videoDir, readdirSync(videoDir).find((f) => f.endsWith(".webm")));
// Two-pass palette GIF: 12 fps, 960 px wide, small enough for a README (< 5 MB).
const filters = "fps=12,scale=960:-1:flags=lanczos";
const palette = join(videoDir, "palette.png");
execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-i", webm, "-vf", `${filters},palettegen=stats_mode=diff`, palette]);
execFileSync("ffmpeg", [
  "-y", "-loglevel", "error", "-i", webm, "-i", palette,
  "-lavfi", `${filters}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle`,
  out,
]);
rmSync(videoDir, { recursive: true, force: true });
console.log(`wrote ${out}`);
