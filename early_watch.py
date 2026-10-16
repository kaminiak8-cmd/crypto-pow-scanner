import os, re, json, time, datetime as dt
import xml.etree.ElementTree as ET
import requests

GH_H = {"Authorization": f"Bearer {os.environ['GH_TOKEN']}",
        "Accept": "application/vnd.github+json"}
TODAY = dt.date.today()
ARXIV_DAYS = 120
REPO_DAYS = 45
STATE = "data/early_watch_seen.json"
SEEN_ALL = "data/seen_all.json"
NOTIFIED = "data/early_notified.json"
OUT_MD = "early_watch.md"
OUT_ISSUE = "watch_issue.md"
PAPER_MIN = 3
REPO_MIN = 4
A = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}

ARXIV_QUERIES = [
    'abs:"proof of useful work"',
    'abs:"useful proof of work"',
    'abs:"proof of work" AND abs:"under construction"',
    'abs:"proof of work" AND (abs:"new blockchain" OR abs:"new cryptocurrency" OR abs:"layer-1" OR abs:"mainnet")',
    'abs:"useful work" AND abs:"blockchain" AND (abs:"GPU" OR abs:"mining")',
    'abs:"proof-of-work" AND abs:"blockchain" AND (abs:"machine learning" OR abs:"AI")',
]
SIGNALS = {
    "building": r"under construction|we (are )?(building|launching|deploying)|will launch|forthcoming|upcoming",
    "chain": r"new (blockchain|cryptocurrency|layer[- ]?1|l1)|our (blockchain|protocol|network)|layer[- ]?1",
    "code": r"github\.com|open[- ]source|reference implementation|prototype implementation|we implement",
    "mining": r"\bminers?\b|\bmining\b|\bgpu\b",
    "mainnet": r"mainnet|testnet|genesis",
}
PRE_QUERIES = [
    "genesis block proof-of-work whitepaper",
    "proof-of-work testnet launch mining layer1",
    "new cryptocurrency pow mainnet soon",
    "proof of useful work",
    "gpu mining new blockchain testnet",
]
TOOLING = re.compile(r"miner for|mining software|stratum server|pool software|curated list|awesome|"
                     r"contributions to|android|\bios\b|simulation|educational|tutorial|wallet app|"
                     r"explorer for|\bsdk\b")
OWN_CHAIN = re.compile(r"layer[- ]?1|\bl1\b|blockchain|\bchain\b|fork of|independent")


def get(url, headers=None, **kw):
    for _ in range(3):
        try:
            r = requests.get(url, headers=headers, timeout=30, **kw)
            if r.status_code in (403, 429):
                print("limit, czekam 60s", flush=True)
                time.sleep(60)
                continue
            return r
        except requests.RequestException as e:
            print("blad:", e, flush=True)
            time.sleep(5)
    return None


def parse_arxiv(xml_bytes):
    out = []
    root = ET.fromstring(xml_bytes)
    for e in root.findall("a:entry", A):
        id_url = e.findtext("a:id", "", A)
        aid = re.sub(r"v\d+$", "", id_url.rsplit("/abs/", 1)[-1])
        out.append({
            "id": aid,
            "pub": e.findtext("a:published", "", A)[:10],
            "title": re.sub(r"\s+", " ", e.findtext("a:title", "", A)).strip(),
            "summary": re.sub(r"\s+", " ", e.findtext("a:summary", "", A)).strip(),
            "comment": e.findtext("x:comment", "", A) or "",
            "url": f"https://arxiv.org/abs/{aid}",
        })
    return out


def arxiv_search(q):
    r = get("https://export.arxiv.org/api/query",
            headers={"User-Agent": "crypto-pow-scanner"},
            params={"search_query": q, "start": 0, "max_results": 40,
                    "sortBy": "submittedDate", "sortOrder": "descending"})
    if r is None or r.status_code != 200:
        print("arXiv blad:", r.status_code if r else "brak", flush=True)
        return []
    try:
        return parse_arxiv(r.content)
    except ET.ParseError as e:
        print("arXiv parse:", e, flush=True)
        return []


def repos_citing(aid):
    r = get("https://api.github.com/search/repositories", headers=GH_H,
            params={"q": f'"{aid}" in:readme', "per_page": 5})
    time.sleep(3)
    if r is None or r.status_code != 200:
        return []
    return [i["full_name"] for i in r.json().get("items", [])]


def readme_text(full):
    h = dict(GH_H)
    h["Accept"] = "application/vnd.github.raw+json"
    r = get(f"https://api.github.com/repos/{full}/readme", headers=h)
    if r is None or r.status_code != 200:
        return ""
    return r.text[:30000].lower()


def repo_score(it, readme):
    desc = (it.get("description") or "")
    text = (desc + " " + " ".join(it.get("topics", []))).lower()
    t = text + " " + readme
    age = (TODAY - dt.date.fromisoformat(it["created_at"][:10])).days
    flags = []
    s = 2 if age <= 14 else (1 if age <= REPO_DAYS else 0)
    for name, rx in (("paper", r"white\s?paper|arxiv|\bpaper\b"),
                     ("genesis", r"genesis"),
                     ("net", r"mainnet|testnet"),
                     ("fair", r"fair launch|fair-launch|no pre-?mine|without pre-?mine"),
                     ("miner", r"\bminers?\b|\bmining\b")):
        if re.search(rx, t):
            s += 1
            flags.append(name)
    if re.search(r"pre-?sale|\bico\b|airdrop|guaranteed|passive income|\bapy\b|\broi\b", t):
        s -= 3
        flags.append("red")
    return s, age, ",".join(flags)


def table(rows, cols):
    if not rows:
        return "Brak."
    head = "| " + " | ".join(cols) + " |\n|" + "|".join(["---"] * len(cols)) + "|\n"
    body = "\n".join("| " + " | ".join(str(r.get(c, "")).replace("|", "/") for c in cols) + " |"
                     for r in rows)
    return head + body


def mark_seen_all(full):
    seen_all = json.load(open(SEEN_ALL)) if os.path.exists(SEEN_ALL) else {}
    if full not in seen_all:
        seen_all[full] = {"first_seen": TODAY.isoformat(), "sources": ["early_watch"]}
    else:
        if "early_watch" not in seen_all[full].get("sources", []):
            seen_all[full]["sources"].append("early_watch")
    json.dump(seen_all, open(SEEN_ALL, "w"), indent=1)


def main():
    os.makedirs("data", exist_ok=True)
    if os.path.exists(OUT_ISSUE):
        os.remove(OUT_ISSUE)
    seen = json.load(open(STATE)) if os.path.exists(STATE) else {}
    notified = json.load(open(NOTIFIED)) if os.path.exists(NOTIFIED) else {}

    papers = {}
    for q in ARXIV_QUERIES:
        for p in arxiv_search(q):
            papers[p["id"]] = p
        time.sleep(3.5)
    cut = (TODAY - dt.timedelta(days=ARXIV_DAYS)).isoformat()
    plist = [p for p in papers.values() if p["pub"] >= cut]
    for p in plist:
        t = (p["title"] + " " + p["summary"] + " " + p["comment"]).lower()
        p["sig"] = [k for k, rx in SIGNALS.items() if re.search(rx, t)]
        p["score"] = len(p["sig"])
        p["repos"] = []
    plist.sort(key=lambda x: (x["score"], x["pub"]), reverse=True)
    for p in plist[:25]:
        if p["score"] >= 1:
            p["repos"] = repos_citing(p["id"])
            if p["repos"]:
                p["score"] += 2
    plist.sort(key=lambda x: (x["score"], x["pub"]), reverse=True)
    prow = [{"score": p["score"], "date": p["pub"], "title": p["title"][:90],
             "signals": ",".join(p["sig"]), "repos": " ".join(p["repos"]), "url": p["url"]}
            for p in plist if p["score"] >= 2][:20]

    found = {}
    since = (TODAY - dt.timedelta(days=REPO_DAYS)).isoformat()
    for kw in PRE_QUERIES:
        r = get("https://api.github.com/search/repositories", headers=GH_H,
                params={"q": f"{kw} created:>{since} stars:>=1 fork:false",
                        "sort": "updated", "order": "desc", "per_page": 40})
        print(kw, r.status_code if r else "brak", flush=True)
        if r is not None and r.status_code == 200:
            for it in r.json().get("items", []):
                found[it["full_name"]] = it
        time.sleep(3)
    rrows = []
    for full, it in found.items():
        desc = it.get("description") or ""
        text = (desc + " " + " ".join(it.get("topics", []))).lower()
        if TOOLING.search(text) or not OWN_CHAIN.search(text):
            continue
        s, age, fl = repo_score(it, readme_text(full))
        rrows.append({"score": s, "age_days": age, "stars": it["stargazers_count"],
                      "flags": fl, "repo": full, "description": desc[:80], "url": it["html_url"]})
        mark_seen_all(full)
        time.sleep(0.5)
    rrows.sort(key=lambda x: (x["score"], -x["age_days"]), reverse=True)

    new_p = [r for r in prow if r["score"] >= PAPER_MIN and r["url"] not in seen]
    new_r = [r for r in rrows if r["score"] >= REPO_MIN and r["url"] not in seen
             and r["repo"] not in notified]

    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(f"# Bardzo wczesny radar - {TODAY}\n\n")
        f.write("Heurystyka: nowe prace arXiv o dowodzie (uzytecznej) pracy z sygnalami budowy lancucha "
                "i mlode repozytoria przed mainnetem. Nie jest to ocena inwestycyjna.\n\n")
        f.write(f"## Prace arXiv (ostatnie {ARXIV_DAYS} dni)\n\n")
        f.write(table(prow, ["score", "date", "title", "signals", "repos", "url"]))
        f.write(f"\n\n## Mlode repozytoria (do {REPO_DAYS} dni)\n\n")
        f.write(table(rrows[:20], ["score", "age_days", "stars", "flags", "repo", "description", "url"]))
        f.write("\n")

    if new_p or new_r:
        with open(OUT_ISSUE, "w", encoding="utf-8") as g:
            g.write(f"Nowe bardzo wczesne sygnaly ({TODAY}). Heurystyka, nie ocena inwestycyjna.\n\n")
            if new_p:
                g.write("## Prace arXiv\n\n")
                g.write(table(new_p[:5], ["score", "date", "title", "signals", "repos", "url"]) + "\n\n")
            if new_r:
                g.write("## Repozytoria\n\n")
                g.write(table(new_r[:5], ["score", "age_days", "stars", "flags", "repo", "url"]) + "\n")
        for r in new_p[:5] + new_r[:5]:
            seen[r["url"]] = TODAY.isoformat()
        json.dump(seen, open(STATE, "w"), indent=1)
    print("Gotowe: prac", len(prow), "repo", len(rrows), "nowych", len(new_p) + len(new_r), flush=True)


if __name__ == "__main__":
    main()
