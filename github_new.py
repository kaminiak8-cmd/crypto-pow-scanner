import os, json, time, datetime as dt
import requests, pandas as pd

H = {"Authorization": f"Bearer {os.environ['GH_TOKEN']}",
     "Accept": "application/vnd.github+json"}
TODAY = dt.date.today()
CREATED = (TODAY - dt.timedelta(days=180)).isoformat()
PUSHED = (TODAY - dt.timedelta(days=14)).isoformat()
SINCE30 = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
STATE = "data/github_seen.json"
MAX_REPOS = 60

QUERIES = [
    "proof-of-work mainnet miner",
    "pow blockchain gpu miner stratum",
    "layer1 blockchain mining pool mainnet",
    "kawpow new coin mainnet",
    "randomx new coin mainnet",
    "cpu mining cryptocurrency mainnet launch",
    "proof of useful work blockchain",
]
FLAGS = ["mainnet", "testnet", "stratum", "miner", "pool", "proof-of-work", "pow", "gpu", "asic", "randomx", "kawpow"]

def get(url, **kw):
    for _ in range(3):
        try:
            r = requests.get(url, headers=H, timeout=20, **kw)
            if r.status_code in (403, 429):
                print("limit, czekam 60s", flush=True)
                time.sleep(60)
                continue
            return r
        except requests.RequestException as e:
            print("blad:", e, flush=True)
            time.sleep(5)
    return None

found = {}
for kw in QUERIES:
    q = f"{kw} created:>{CREATED} pushed:>{PUSHED} stars:>=3 fork:false"
    r = get("https://api.github.com/search/repositories",
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
for i, it in enumerate(items, 1):
    name = it["full_name"]
    r = get(f"https://api.github.com/repos/{name}/commits",
            params={"since": SINCE30, "per_page": 100})
    commits, authors = 0, 0
    if r is not None and r.status_code == 200:
        data = r.json()
        commits = len(data)
        authors = len({c["author"]["login"] for c in data
                       if c.get("author") and "bot" not in c["author"]["login"].lower()})
    text = ((it.get("description") or "") + " " + " ".join(it.get("topics", []))).lower()
    flags = ",".join(f for f in FLAGS if f in text)
    if name not in seen:
        seen[name] = TODAY.isoformat()
    rows.append({
        "date": TODAY.isoformat(), "repo": name,
        "stars": it["stargazers_count"], "commits_30d": commits, "authors_30d": authors,
        "score": commits * max(authors, 1) + it["stargazers_count"],
        "created": it["created_at"][:10], "pushed": it["pushed_at"][:10],
        "flags": flags, "new_today": (not first_run) and seen[name] == TODAY.isoformat(),
        "description": (it.get("description") or "")[:90].replace("|", "/"),
        "url": it["html_url"]})
    time.sleep(0.5)

json.dump(seen, open(STATE, "w"), indent=1)
df = pd.DataFrame(rows)
if df.empty:
    print("Brak wynikow", flush=True)
    raise SystemExit(0)
df = df.sort_values("score", ascending=False)
df.to_csv(f"data/github-{TODAY.isoformat()}.csv", index=False)

cols = ["repo", "stars", "commits_30d", "authors_30d", "created", "flags", "description"]
with open("github_new.md", "w", encoding="utf-8") as f:
    f.write(f"# Nowe projekty z GitHuba {TODAY}\n\n## Nowe dzisiaj\n\n")
    n = df[df.new_today]
    f.write(n[cols].to_markdown(index=False) if len(n) else "Brak nowych (albo pierwsze uruchomienie).")
    f.write("\n\n## Ranking aktywnosci\n\n")
    f.write(df.head(25)[cols].to_markdown(index=False))
print("Gotowe", len(df), flush=True)
