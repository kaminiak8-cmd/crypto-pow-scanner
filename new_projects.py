import os, re, json, time, datetime as dt
import requests, pandas as pd

GH_H = {"Authorization": f"Bearer {os.environ['GH_TOKEN']}",
        "Accept": "application/vnd.github+json"}
CG_H = {"x-cg-demo-api-key": os.environ["CG_KEY"]}
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept": "text/html,application/xhtml+xml"}
CGU = "https://api.coingecko.com/api/v3"
TODAY = dt.date.today()
CREATED = (TODAY - dt.timedelta(days=270)).isoformat()
PUSHED = (TODAY - dt.timedelta(days=21)).isoformat()
SINCE30 = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
STATE = "data/new_projects_seen.json"
NOTIFIED = "data/early_notified.json"
NOTIFY_MIN = 8
MAX_REPOS = 80

STOP = {"coin", "coins", "network", "chain", "core", "node", "miner", "mining", "pool",
        "cash", "gold", "labs", "protocol", "token", "bitcoin", "crypto", "blockchain"}

NOISE = ["captcha", "anti-bot", "antibot", "bot ", "bots", "ddos", "waf", "firewall",
         "email", "nginx", "credential", "relay", "chat", "wordpress", "honeypot",
         "agent", "cli", "dashboard", "library", "bindings"]
GOOD = ["blockchain", "layer-1", "layer 1", "l1", "coin", "ledger", "mining", "miner",
        "mainnet", "testnet", "chain"]
GOOD_FLAGS = ("mainnet", "miner", "stratum", "randomx", "kawpow", "l1", "layer1")
TOOLING = re.compile(r"miner for|mining software|stratum server|pool software|curated list|awesome|"
                     r"contributions to|android|\bios\b|simulation|educational|tutorial|wallet app|"
                     r"explorer for|\bsdk\b")
OWN_CHAIN = re.compile(r"layer[- ]?1|\bl1\b|blockchain|\bchain\b|fork of|independent")

QUERIES = [
    "proof-of-work mainnet miner",
    "pow blockchain gpu miner stratum",
    "layer1 blockchain mining pool mainnet",
    "kawpow new coin mainnet",
    "randomx new coin mainnet",
    "cpu mining cryptocurrency mainnet launch",
    "proof of useful work blockchain",
    "topic:proof-of-work",
    "topic:mining blockchain",
]
FLAGS = ["mainnet", "testnet", "stratum", "miner", "pool", "proof-of-work", "pow",
         "gpu", "asic", "randomx", "kawpow", "layer1", "l1"]

def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())

def get(url, headers=None, **kw):
    for _ in range(3):
        try:
            r = requests.get(url, headers=headers, timeout=25, **kw)
            if r.status_code in (403, 429):
                print("limit, czekam 60s", flush=True)
                time.sleep(60)
                continue
            return r
        except requests.RequestException as e:
            print("blad:", e, flush=True)
            time.sleep(5)
    return None

def wtm_names():
    try:
        r = requests.get("https://whattomine.com/calculators", headers=UA, timeout=30)
    except requests.RequestException as e:
        print("WTM blad:", e, flush=True)
        return None
    if r.status_code != 200:
        print("WTM status:", r.status_code, flush=True)
        return None
    slugs = set(re.findall(r"/coins/\d+-([a-z0-9\-]+)", r.text))
    names = set()
    for s in slugs:
        names.add(norm(s))
        for p in s.split("-"):
            if len(p) >= 4 and p not in STOP:
                names.add(p)
    print("WTM monet:", len(slugs), flush=True)
    return names if slugs else None

def cg_names():
    r = get(f"{CGU}/coins/list", headers=CG_H)
    if r is None or r.status_code != 200:
        print("CG blad", r.status_code if r else "brak", flush=True)
        return None
    names = set()
    data = r.json()
    for c in data:
        for k in ("id", "name", "symbol"):
            n = norm(c.get(k, ""))
            if len(n) >= 3:
                names.add(n)
    print("CG monet:", len(data), flush=True)
    return names

def variants(it):
    out = set()
    for base in (it["name"], it["owner"]["login"]):
        n = norm(base)
        out.add(n)
        out.add(norm(re.sub(r"[-_.]?(core|node|miner|blockchain|network|chain|coin|pow)$", "", base.lower())))
    return {v for v in out if len(v) >= 3}

def miner_release(full):
    r = get(f"https://api.github.com/repos/{full}/releases/latest", headers=GH_H)
    if r is None or r.status_code != 200:
        return False, 0
    assets = [a["name"].lower() for a in r.json().get("assets", [])]
    ok = any(k in a for a in assets for k in ("miner", "mining", "stratum"))
    return ok, len(assets)

def looks_like_coin(desc, flags):
    d = (desc or "").lower()
    if any(n in d for n in NOISE):
        return False
    return any(g in d for g in GOOD) or any(g in flags for g in GOOD_FLAGS)

def readme_text(full):
    h = dict(GH_H)
    h["Accept"] = "application/vnd.github.raw+json"
    r = get(f"https://api.github.com/repos/{full}/readme", headers=h)
    if r is None or r.status_code != 200:
        return ""
    return r.text[:30000].lower()

def early_profile(created, has_miner, commits, authors, text, readme):
    t = text + " " + readme
    age = (TODAY - dt.date.fromisoformat(created[:10])).days
    f = {
        "miner": bool(has_miner),
        "pool": bool(re.search(r"stratum|mining[- ]?pool", t)),
        "mainnet": "mainnet" in t,
        "paper": bool(re.search(r"white\s?paper|arxiv|\bpaper\b", t)),
        "fair": bool(re.search(r"fair launch|fair-launch|no pre-?mine|without pre-?mine|100% mined", t)),
        "red": bool(re.search(r"pre-?sale|\bico\b|airdrop|guaranteed|passive income|\bapy\b|\broi\b", t)),
        "proto": bool(re.search(r"pre-launch|prototype|proof of concept|simulation|educational", t)),
    }
    s = 2 if age <= 120 else (1 if age <= 270 else 0)
    s += 3 * f["miner"] + 2 * f["pool"] + 2 * f["mainnet"] + 2 * f["paper"] + 2 * f["fair"]
    s += int(authors >= 2) + int(commits >= 20)
    s -= 3 * f["red"] + 2 * f["proto"]
    if "testnet" in t and not f["mainnet"]:
        s -= 2
    return s, age, f

wtm = wtm_names()
cg = cg_names()

found = {}
for kw in QUERIES:
    q = f"{kw} created:>{CREATED} pushed:>{PUSHED} stars:>=2 fork:false"
    r = get("https://api.github.com/search/repositories", headers=GH_H,
            params={"q": q, "sort": "updated", "order": "desc", "per_page": 50})
    print(kw, r.status_code if r else "brak", flush=True)
    if r is not None and r.status_code == 200:
        for it in r.json().get("items", []):
            found[it["full_name"]] = it
    time.sleep(3)

print("Znaleziono:", len(found), flush=True)
items = sorted(found.values(), key=lambda x: x["stargazers_count"], reverse=True)[:MAX_REPOS]

os.makedirs("data", exist_ok=True)
seen = json.load(open(STATE)) if os.path.exists(STATE) else {}
first_run = not seen

rows = []
for it in items:
    full = it["full_name"]
    vs = variants(it)
    in_wtm = None if wtm is None else bool(vs & wtm)
    in_cg = None if cg is None else bool(vs & cg)
    r = get(f"https://api.github.com/repos/{full}/commits", headers=GH_H,
            params={"since": SINCE30, "per_page": 100})
    commits = authors = 0
    if r is not None and r.status_code == 200:
        data = r.json()
        commits = len(data)
        authors = len({c["author"]["login"] for c in data
                       if c.get("author") and "bot" not in c["author"]["login"].lower()})
    has_miner, n_assets = miner_release(full)
    desc = it.get("description") or ""
    text = (desc + " " + " ".join(it.get("topics", []))).lower()
    flags = ",".join(f for f in FLAGS if f in text)
    cand = (looks_like_coin(desc, flags) and not TOOLING.search(text) and bool(OWN_CHAIN.search(text))
            and in_wtm != True and in_cg != True)
    early, age, ef = 0, None, {}
    if cand:
        early, age, ef = early_profile(it["created_at"], has_miner, commits, authors, text, readme_text(full))
    if full not in seen:
        seen[full] = TODAY.isoformat()
    rows.append({
        "date": TODAY.isoformat(), "repo": full,
        "in_wtm": in_wtm, "in_coingecko": in_cg,
        "coin_like": looks_like_coin(desc, flags),
        "stars": it["stargazers_count"], "commits_30d": commits, "authors_30d": authors,
        "miner_release": has_miner, "release_assets": n_assets,
        "score": commits * max(authors, 1) + it["stargazers_count"] + (20 if has_miner else 0),
        "early_score": early, "age_days": age,
        "early_flags": ",".join(k for k, v in ef.items() if v),
        "created": it["created_at"][:10], "pushed": it["pushed_at"][:10],
        "flags": flags,
        "new_today": (not first_run) and seen[full] == TODAY.isoformat(),
        "description": desc[:90].replace("|", "/"),
        "url": it["html_url"]})
    time.sleep(0.5)

json.dump(seen, open(STATE, "w"), indent=1)
df = pd.DataFrame(rows)
if df.empty:
    print("Brak wynikow", flush=True)
    raise SystemExit(0)
df = df.sort_values("score", ascending=False)
df.to_csv(f"data/new_projects-{TODAY.isoformat()}.csv", index=False)

cols = ["repo", "stars", "commits_30d", "authors_30d", "miner_release", "flags", "description"]
unknown = df[(df.in_wtm != True) & (df.in_coingecko != True) & (df.coin_like)]
ec = ["repo", "early_score", "age_days", "stars", "commits_30d", "early_flags", "description"]
early_df = unknown[unknown.early_score > 0].sort_values("early_score", ascending=False)

with open("new_projects.md", "w", encoding="utf-8") as f:
    f.write(f"# Projekty bez WTM i bez CoinGecko - {TODAY}\n\n")
    if wtm is None:
        f.write("UWAGA: nie udalo sie pobrac listy WhatToMine, sprawdz recznie.\n\n")
    if cg is None:
        f.write("UWAGA: nie udalo sie pobrac listy CoinGecko, sprawdz recznie.\n\n")
    f.write("## Nowe dzisiaj\n\n")
    n = unknown[unknown.new_today]
    f.write(n[cols].to_markdown(index=False) if len(n) else "Brak nowych (albo pierwsze uruchomienie).")
    f.write("\n\n## Wczesne okazje (profil Pearl)\n\n")
    f.write("Punkty: mlody projekt, wydany miner, pula/stratum, mainnet, whitepaper, fair launch, "
            "autorzy i commity; minus za presale/ICO, prototyp, sam testnet. Narzedzia i dodatki "
            "do istniejacych lancuchow sa odrzucane. To heurystyka z README, nie ocena inwestycyjna.\n\n")
    f.write(early_df.head(15)[ec].to_markdown(index=False) if len(early_df) else "Brak.")
    f.write("\n\n## Ranking kandydatow\n\n")
    f.write(unknown.head(30)[cols].to_markdown(index=False) if len(unknown) else "Brak.")

if os.path.exists("early_issue.md"):
    os.remove("early_issue.md")
notified = json.load(open(NOTIFIED)) if os.path.exists(NOTIFIED) else {}
fresh = early_df[(early_df.early_score >= NOTIFY_MIN) & (~early_df.repo.isin(list(notified)))]
if len(fresh):
    top = fresh.head(5)
    with open("early_issue.md", "w", encoding="utf-8") as g:
        g.write(f"Nowe wczesne projekty PoW ({TODAY}), wynik >= {NOTIFY_MIN}. "
                "Heurystyka z README, nie ocena inwestycyjna.\n\n")
        g.write(top[ec + ["url"]].to_markdown(index=False))
    for name in top.repo:
        notified[name] = TODAY.isoformat()
    json.dump(notified, open(NOTIFIED, "w"), indent=1)
print("Gotowe:", len(df), "wszystkich,", len(unknown), "kandydatow,", len(fresh), "do powiadomienia", flush=True)
