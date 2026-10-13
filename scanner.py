import os, time, datetime as dt
import requests, pandas as pd

GH = {"Authorization": f"Bearer {os.environ['GH_TOKEN']}"}
CG = {"x-cg-demo-api-key": os.environ["CG_KEY"]}
CGU = "https://api.coingecko.com/api/v3"
SINCE = (dt.datetime.utcnow() - dt.timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
LIMIT = 40
T = 20

def get(url, **kw):
    for _ in range(3):
        try:
            r = requests.get(url, timeout=T, **kw)
            if r.status_code == 429:
                print("429, czekam 30s", flush=True)
                time.sleep(30)
                continue
            return r
        except requests.RequestException as e:
            print("blad zapytania:", e, flush=True)
            time.sleep(5)
    return None

def coins():
    r = get(f"{CGU}/coins/markets", headers=CG, params={
        "vs_currency": "usd", "category": "proof-of-work-pow",
        "order": "market_cap_desc", "per_page": LIMIT, "page": 1})
    if r is None or r.status_code != 200:
        print("Blad listy monet:", r.status_code if r else "brak", r.text[:300] if r else "", flush=True)
        raise SystemExit(1)
    return r.json()

def repo_of(coin_id):
    r = get(f"{CGU}/coins/{coin_id}", headers=CG, params={
        "localization": "false", "tickers": "false", "market_data": "false",
        "community_data": "false", "developer_data": "false"})
    if r is None or r.status_code != 200:
        return None
    urls = [u for u in r.json()["links"]["repos_url"]["github"] if u]
    return urls[0] if urls else None

def dev_stats(repo_url):
    parts = repo_url.rstrip("/").split("github.com/")[-1].split("/")
    if len(parts) < 2:
        return None
    owner, name = parts[0], parts[1]
    commits, page = [], 1
    while page <= 5:
        r = get(f"https://api.github.com/repos/{owner}/{name}/commits",
                headers=GH, params={"since": SINCE, "per_page": 100, "page": page})
        if r is None or r.status_code != 200:
            break
        data = r.json()
        if not data:
            break
        commits += data
        page += 1
    authors = {c["author"]["login"] for c in commits
               if c.get("author") and "bot" not in c["author"]["login"].lower()}
    return len(commits), len(authors)

rows = []
cl = coins()
print("Monet:", len(cl), flush=True)
for i, c in enumerate(cl, 1):
    print(i, c["symbol"], flush=True)
    repo = repo_of(c["id"])
    time.sleep(2.5)
    if not repo or "github.com" not in repo:
        continue
    st = dev_stats(repo)
    if not st:
        continue
    commits, authors = st
    mcap = c["market_cap"] or 1
    rows.append({
        "date": dt.date.today().isoformat(),
        "coin": c["symbol"].upper(), "name": c["name"],
        "price": c["current_price"], "market_cap": mcap,
        "volume_24h": c["total_volume"],
        "commits_90d": commits, "authors_90d": authors,
        "score": round(commits * authors / mcap * 1e6, 4),
        "repo": repo})

df = pd.DataFrame(rows)
if df.empty:
    print("Brak wynikow", flush=True)
    raise SystemExit(1)
df = df.sort_values("score", ascending=False)
os.makedirs("data", exist_ok=True)
df.to_csv(f"data/{dt.date.today().isoformat()}.csv", index=False)

with open("report.md", "w", encoding="utf-8") as f:
    f.write(f"# Raport {dt.date.today()}\n\n")
    f.write(df.head(15)[["coin", "market_cap", "commits_90d", "authors_90d", "score"]]
            .to_markdown(index=False))
print("Gotowe", flush=True)
