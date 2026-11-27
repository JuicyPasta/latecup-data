// Read shops' own pages in a headless browser, for the pages that show their hours only after scripts run.
//
// usage: NODE_PATH=$(npm root -g) node tools/harvest_browser.mjs candidates.json out-folder [--workers 3]
//
// It takes the candidates file of tools/harvest.py and writes the same records (out/<id>.json, with
// "read_with": "browser"): the text a person would see on the page (visible elements only), the schema.org
// hours, hours kept in the page's scripts, and the final address. Which sites may be read, which page comes
// next and what goes into a record are decided by tools/harvest.py (--step plan|next|shape), so both readers
// follow one set of rules. Nothing is decided here either.
//
// How it reads: two page loads a site at most, a few seconds apart; an honest User-Agent that names the project
// and nothing about who runs it; a fresh browser context for every site, so no cookie is kept from one site to
// the next; no click, no form, no consent or sign-in wall gone through; images, media and fonts not loaded. A
// page behind a bot check is left alone. Nothing is downloaded or installed: the browser is the one already on
// this machine (LATECUP_CHROME, default below), and when none can be started the reader stops and says so.
//
// Environment: LATECUP_CHROME (the browser), LATECUP_PYTHON (the Python that runs tools/harvest.py; default:
// .venv/bin/python of this checkout, else python3).

import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const HARVEST = join(ROOT, "tools", "harvest.py");
const CHROME = process.env.LATECUP_CHROME || join(homedir(), "Library/Caches/ms-playwright/chromium_headless_shell-1255",
  "chrome-headless-shell-mac-arm64/chrome-headless-shell");
const PYTHON = process.env.LATECUP_PYTHON ||
  (existsSync(join(ROOT, ".venv/bin/python")) ? join(ROOT, ".venv/bin/python") : "python3");
const LOAD_TIMEOUT = 30_000;
const MAX_HTML = 1_500_000;
const BOT_CHECK = /just a moment|checking your browser|verify you are human|attention required|cf-chl|captcha|are you a robot|access denied/i;

function die(message) {
  console.error(`harvest_browser: ${message}`);
  process.exit(2);
}

function py(stepName, doc) {
  return new Promise((ok, fail) => {
    const child = spawn(PYTHON, [HARVEST, "--step", stepName], { cwd: ROOT, stdio: ["pipe", "pipe", "pipe"] });
    let out = "", err = "";
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (err += d));
    child.on("error", fail);
    child.on("close", (code) => {
      if (code) return fail(new Error(`tools/harvest.py --step ${stepName} ended with ${code}: ${err.slice(-2000)}`));
      try {
        ok(JSON.parse(out));
      } catch (e) {
        fail(new Error(`tools/harvest.py --step ${stepName} printed no JSON: ${out.slice(0, 500)} ${err.slice(-500)}`));
      }
    });
    child.stdin.end(JSON.stringify(doc));
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function hostOf(url) {
  try {
    return new URL(url).hostname.toLowerCase();
  } catch {
    return "";
  }
}

// Run in the page: hide what a person cannot see (zero-size boxes that clip their content, boxes moved off the
// page, transparent or invisible ones), then take the rendered text, which already leaves out display:none.
function visibleText() {
  const doc = document.documentElement;
  const hide = [];
  for (const el of document.body ? document.body.querySelectorAll("*") : []) {
    const cs = getComputedStyle(el);
    if (cs.display === "none") continue;
    let hidden = false;
    if (el.checkVisibility && !el.checkVisibility({ opacityProperty: true, visibilityProperty: true })) {
      hidden = true;
    } else {
      const r = el.getBoundingClientRect();
      const x = r.left + window.scrollX, y = r.top + window.scrollY;
      const clipped = (cs.overflow === "hidden" || cs.overflowX === "hidden" || cs.overflowY === "hidden" ||
        /rect\(\s*0(px)?[ ,]+0(px)?[ ,]+0(px)?[ ,]+0(px)?\s*\)/.test(cs.clip) || cs.clipPath === "inset(50%)");
      if ((r.width <= 1 || r.height <= 1) && clipped) hidden = true;
      if (x + r.width < 0 || y + r.height < 0 || x > doc.scrollWidth + 50) hidden = true;
    }
    if (hidden) hide.push(el);
  }
  for (const el of hide) el.style.setProperty("display", "none", "important");
  return document.body ? document.body.innerText : "";
}

async function settle(page) {
  await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => {});
  // scroll through once, so sections that draw themselves when seen are drawn, then back to the top
  await page.evaluate(async () => {
    const step = Math.max(400, window.innerHeight * 0.8);
    for (let y = 0; y < Math.min(document.body ? document.body.scrollHeight : 0, 30_000); y += step) {
      window.scrollTo(0, y);
      await new Promise((r) => setTimeout(r, 150));
    }
    window.scrollTo(0, 0);
  }).catch(() => {});
  // text that is still filling in ("Checking hours…", a locator loading its stores): wait until it holds still
  let last = -1;
  for (let i = 0; i < 6; i++) {
    await sleep(1_500);
    const n = await page.evaluate(() => (document.body ? document.body.innerText.length : 0)).catch(() => -2);
    if (n === last) break;
    last = n;
  }
}

async function load(context, url, plan) {
  const page = await context.newPage();
  page.on("dialog", (d) => d.dismiss().catch(() => {}));
  try {
    let response;
    try {
      response = await page.goto(url, { waitUntil: "domcontentloaded", timeout: LOAD_TIMEOUT });
    } catch (e) {
      return { error: (e.message || String(e)).split("\n")[0].replace(/^page\.goto: /, "").slice(0, 160) };
    }
    const status = response ? response.status() : null;
    const title = await page.title().catch(() => "");
    if (status && status >= 400) {
      const peek = await page.evaluate(() => (document.body ? document.body.innerText.slice(0, 2000) : "")).catch(() => "");
      return { error: BOT_CHECK.test(`${title}\n${peek}`) ? `HTTP ${status}, a bot check: not read` : `HTTP ${status}` };
    }
    if (BOT_CHECK.test(title)) return { error: "a bot check: not read" };
    await settle(page);
    const final = page.url();
    const host = hostOf(final);
    if (new RegExp(plan.listing_hosts).test(host)) return { error: "redirected to a listing site" };
    if (new RegExp(plan.social_hosts).test(host)) return { error: "redirected to Instagram or Facebook" };
    let text = await page.evaluate(visibleText).catch(() => "");
    // frames on the page that are the shop's own or its ordering page (not a map or a listing site)
    for (const frame of page.frames().slice(1, 6)) {
      const fh = hostOf(frame.url());
      if (!fh || new RegExp(plan.listing_hosts).test(fh) || new RegExp(plan.social_hosts).test(fh)) continue;
      const inner = await frame.evaluate(visibleText).catch(() => "");
      if (inner.trim()) text += `\n[in a frame from ${fh}]\n` + inner.split("\n").slice(0, 300).join("\n");
    }
    const html = (await page.content().catch(() => "")).slice(0, MAX_HTML);
    const lines = text.split("\n").map((l) => l.replace(/\s+/g, " ").trim()).filter(Boolean);
    return { page: { url, final, status, html, lines } };
  } finally {
    await page.close().catch(() => {});
  }
}

async function readSite(browser, site, cands, plan, out) {
  const context = await browser.newContext({
    userAgent: plan.user_agent, locale: "en-US", viewport: { width: 1280, height: 1600 },
    serviceWorkers: "block", acceptDownloads: false, javaScriptEnabled: true,
  });
  await context.route("**/*", (route) =>
    ["image", "media", "font"].includes(route.request().resourceType()) ? route.abort() : route.continue());
  context.on("page", async (p) => { if (await p.opener().catch(() => null)) p.close().catch(() => {}); });   // no pop-ups
  const pages = [];
  let error = null;
  try {
    let target = site.url;
    for (let n = 0; n < plan.max_pages && target; n++) {
      if (n) await sleep(plan.pause_s * 1000);
      const got = await load(context, target, plan);
      if (got.error) {
        const msg = n ? `${target}: ${got.error}` : got.error;
        error = error ? `${error}; ${msg}` : msg;
        target = n === 0 ? (await py("next", { url: site.url, candidates: cands, pages: [], error: got.error })).next
          : null;
        continue;
      }
      pages.push(got.page);
      target = n + 1 < plan.max_pages ? (await py("next", { url: site.url, candidates: cands, pages })).next : null;
    }
  } finally {
    await context.close().catch(() => {});
  }
  await py("shape", { url: site.url, candidates: cands, pages, error, out });
  return { url: site.url, pages: pages.length, error };
}

async function main() {
  const args = process.argv.slice(2);
  if (args.length < 2) die("usage: node tools/harvest_browser.mjs candidates.json out-folder [--workers 3]");
  const [candFile, outDir] = args;
  const workers = args.includes("--workers") ? Number(args[args.indexOf("--workers") + 1]) : 3;
  const cands = JSON.parse(readFileSync(candFile, "utf8"));
  const byId = new Map(cands.map((c) => [c.id, c]));
  mkdirSync(outDir, { recursive: true });
  const plan = await py("plan", { candidates: cands, out: resolve(outDir) });

  let chromium;
  try {
    ({ chromium } = require("playwright"));
  } catch {
    die("Playwright is not installed where Node looks (run with NODE_PATH=$(npm root -g)). Nothing was installed.");
  }
  if (!existsSync(CHROME)) die(`no browser at ${CHROME} (set LATECUP_CHROME). Nothing was downloaded.`);
  let browser;
  try {
    browser = await chromium.launch({ executablePath: CHROME, headless: true });
  } catch (e) {
    die(`the browser at ${CHROME} would not start: ${(e.message || e).toString().split("\n")[0]}`);
  }

  // one host at a time: a site is never read by two workers at once
  const byHost = new Map();
  for (const site of plan.sites) {
    const h = hostOf(site.url);
    if (!byHost.has(h)) byHost.set(h, []);
    byHost.get(h).push(site);
  }
  console.log(`${plan.sites.length} sites on ${byHost.size} hosts, ${workers} at a time`);
  const queue = [...byHost.values()];
  let done = 0;
  const worker = async () => {
    for (let sites; (sites = queue.shift()); ) {
      for (const [n, site] of sites.entries()) {
        if (n) await sleep(plan.pause_s * 1000);
        try {
          const r = await readSite(browser, site, site.ids.map((id) => byId.get(id)), plan, resolve(outDir));
          console.log(`${++done}/${plan.sites.length} ${r.url}: ${r.pages} page(s)${r.error ? ", " + r.error : ""}`);
        } catch (e) {
          console.log(`${++done}/${plan.sites.length} ${site.url}: failed: ${(e.message || e).toString().split("\n")[0]}`);
        }
      }
    }
  };
  try {
    await Promise.all(Array.from({ length: Math.max(1, workers) }, worker));
  } finally {
    await browser.close().catch(() => {});
  }
}

main().catch((e) => die(e.stack || String(e)));
