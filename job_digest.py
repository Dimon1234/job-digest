#!/usr/bin/env python3
"""
UK Senior Kotlin/Java Contract — daily job digest with accumulation.

Reads: ADZUNA_APP_ID, ADZUNA_APP_KEY, REED_API_KEY (optional)
       DELIVERY (email|console), EMAIL_TO, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS
       VACANCIES_FILE (default: data/job_vacancies.json relative to script)
"""

import json
import os
import smtplib
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

ADZUNA_APP_ID    = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY   = os.getenv("ADZUNA_APP_KEY", "")
REED_API_KEY     = os.getenv("REED_API_KEY", "")
DELIVERY         = os.getenv("DELIVERY", "console").lower()
EMAIL_TO         = os.getenv("EMAIL_TO", "")
SMTP_HOST        = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT        = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER        = os.getenv("SMTP_USER", EMAIL_TO)
SMTP_PASS        = os.getenv("SMTP_PASS", "")
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DAYS_LOOKBACK    = int(os.getenv("DAYS_LOOKBACK", "0"))  # 0 = auto (1d weekday / 3d weekend)
_default_store = Path(__file__).parent / "data" / "job_vacancies.json"
VACANCIES_FILE = Path(os.getenv("VACANCIES_FILE", _default_store))

SEARCH_DATE = datetime.now(timezone.utc).strftime("%Y-%m-%d")
SEARCH_TS   = datetime.now(timezone.utc).isoformat()

# ── Adzuna ────────────────────────────────────────────────────────────────────

def fetch_adzuna() -> list[dict]:
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        print("[ADZUNA] Skipped — ADZUNA_APP_ID / ADZUNA_APP_KEY not set", file=sys.stderr)
        return []

    from datetime import date
    if DAYS_LOOKBACK > 0:
        days_old = DAYS_LOOKBACK
    else:
        days_old = 3 if date.today().weekday() >= 5 else 1

    queries = ["senior kotlin contract", "senior java contract",
               "kotlin developer contract", "java developer contract"]

    results = []
    for query in queries:
        page, total_pages = 1, 1
        while page <= total_pages:
            params = urllib.parse.urlencode({
                "app_id":           ADZUNA_APP_ID,
                "app_key":          ADZUNA_APP_KEY,
                "results_per_page": 50,
                "what":             query,
                "where":            "UK",
                "max_days_old":     days_old,
                "sort_by":          "date",
            })
            url = f"https://api.adzuna.com/v1/api/jobs/gb/search/{page}?{params}"
            try:
                with urllib.request.urlopen(url, timeout=15) as r:
                    data = json.load(r)
                count    = data.get("count", 0)
                found    = data.get("results", [])
                total_pages = max(1, (count + 49) // 50)  # ceil division
                print(f"[ADZUNA] '{query}' p{page}/{total_pages}: "
                      f"{len(found)} jobs (total ~{count}, last {days_old}d)",
                      file=sys.stderr)
                for job in found:
                    results.append(parse_adzuna(job))
                if not found:
                    break
                page += 1
            except urllib.error.HTTPError as e:
                print(f"[ADZUNA] HTTP {e.code} p{page} '{query}': {e.reason}",
                      file=sys.stderr)
                break
            except Exception as e:
                print(f"[ADZUNA] Error p{page} '{query}': {e}", file=sys.stderr)
                break
    return results


def parse_adzuna(j: dict) -> dict:
    desc = j.get("description", "")
    return {
        "id":              f"adzuna_{j.get('id', '')}",
        "source":          "adzuna",
        "fetched_at":      SEARCH_TS,
        "title":           j.get("title", ""),
        "company":         j.get("company", {}).get("display_name", ""),
        "location":        j.get("location", {}).get("display_name", ""),
        "salary_min":      j.get("salary_min"),
        "salary_max":      j.get("salary_max"),
        "contract_type":   j.get("contract_type", ""),
        "contract_time":   j.get("contract_time", ""),
        "created":         j.get("created", ""),
        "redirect_url":    j.get("redirect_url", ""),
        "description":     desc,
        "key_skills":      extract_skills(desc),
        "ir35_status":     extract_ir35(desc),
        "overseas_notes":  extract_overseas(desc),
        "remote":          is_remote(j.get("title", "") + " " + desc),
    }


# ── Reed ─────────────────────────────────────────────────────────────────────

def fetch_reed() -> list[dict]:
    if not REED_API_KEY:
        print("[REED] Skipped — REED_API_KEY not set", file=sys.stderr)
        return []

    results = []
    for kw in ["senior kotlin contract", "senior java contract"]:
        params = urllib.parse.urlencode({
            "keywords":       kw,
            "locationName":   "UK",
            "contractType":   "Contract",
            "postedByRecruitmentAgency": "true",
            "resultsToTake":  100,
        })
        url = f"https://www.reed.co.uk/api/1.0/search?{params}"
        req = urllib.request.Request(url)
        import base64
        token = base64.b64encode(f"{REED_API_KEY}:".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.load(r)
            for job in data.get("results", []):
                results.append(parse_reed(job))
        except urllib.error.HTTPError as e:
            print(f"[REED] HTTP {e.code} for '{kw}': {e.reason}", file=sys.stderr)
        except Exception as e:
            print(f"[REED] Error for '{kw}': {e}", file=sys.stderr)
    return results


def parse_reed(j: dict) -> dict:
    desc = j.get("jobDescription", "")
    return {
        "id":              f"reed_{j.get('jobId', '')}",
        "source":          "reed",
        "fetched_at":      SEARCH_TS,
        "title":           j.get("jobTitle", ""),
        "company":         j.get("employerName", ""),
        "location":        j.get("locationName", ""),
        "salary_min":      j.get("minimumSalary"),
        "salary_max":      j.get("maximumSalary"),
        "contract_type":   "Contract",
        "contract_time":   "",
        "created":         j.get("date", ""),
        "redirect_url":    j.get("jobUrl", ""),
        "description":     desc,
        "key_skills":      extract_skills(desc),
        "ir35_status":     extract_ir35(desc),
        "overseas_notes":  extract_overseas(desc),
        "remote":          is_remote(j.get("jobTitle", "") + " " + desc),
    }


# ── Web search (DuckDuckGo, no API key) ──────────────────────────────────────

WEB_QUERIES = [
    '"senior kotlin" contract UK remote "outside IR35"',
    '"senior java" contract UK remote "outside IR35"',
    '"kotlin developer" contract UK remote "per day"',
    '"java developer" contract UK remote "outside IR35" "per day"',
    'site:cwjobs.co.uk senior kotlin java contract remote',
    'site:totaljobs.com senior kotlin java contract remote "outside IR35"',
    'site:jobsite.co.uk senior kotlin java contract remote',
    'site:contractspy.co.uk kotlin java senior',
    'site:itjobswatch.co.uk kotlin java contract remote',
]

def fetch_web() -> list[dict]:
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
    except ImportError:
        print("[WEB] Skipped — install: pip install ddgs", file=sys.stderr)
        return []

    results = []
    seen_urls: set[str] = set()

    try:
        with DDGS() as ddgs:
            for query in WEB_QUERIES:
                try:
                    hits = list(ddgs.text(query, max_results=15))
                    print(f"[WEB] '{query[:55]}': {len(hits)} results", file=sys.stderr)
                    for h in hits:
                        url = h.get("href", "")
                        if url in seen_urls:
                            continue
                        seen_urls.add(url)
                        job = parse_web_result(h)
                        if job:
                            results.append(job)
                except Exception as e:
                    print(f"[WEB] Query error: {e}", file=sys.stderr)
    except Exception as e:
        print(f"[WEB] DDGS error: {e}", file=sys.stderr)

    print(f"[WEB] {len(results)} unique results total", file=sys.stderr)
    return results


def parse_web_result(hit: dict) -> dict | None:
    import hashlib, re as _re
    title = hit.get("title", "")
    url   = hit.get("href", "")
    body  = hit.get("body", "")
    text  = f"{title} {body}"

    # Skip non-job pages
    if not any(k in text.lower() for k in ["contract", "kotlin", "java", "developer", "engineer"]):
        return None

    # Extract rate: £400/day, £400 per day, 400pd, £400-£500
    rate_match = _re.search(
        r'£\s*(\d{3,4})\s*(?:[-–]\s*£?\s*(\d{3,4}))?\s*(?:per\s+day|p/?d|/day|/d\b)',
        text, _re.IGNORECASE
    )
    salary_min = salary_max = None
    if rate_match:
        salary_min = float(rate_match.group(1))
        salary_max = float(rate_match.group(2)) if rate_match.group(2) else salary_min

    uid = f"web_{hashlib.md5(url.encode()).hexdigest()[:12]}"

    return {
        "id":             uid,
        "source":         "web",
        "fetched_at":     SEARCH_TS,
        "title":          title,
        "company":        "",
        "location":       "UK",
        "salary_min":     salary_min,
        "salary_max":     salary_max,
        "contract_type":  "Contract",
        "contract_time":  "",
        "created":        SEARCH_DATE,
        "redirect_url":   url,
        "description":    body,
        "key_skills":     extract_skills(text),
        "ir35_status":    extract_ir35(text),
        "overseas_notes": extract_overseas(text),
        "remote":         is_remote(text),
    }

SKILLS_VOCAB = [
    "Kotlin", "Java", "Spring Boot", "Spring", "Microservices", "Kafka",
    "Kubernetes", "Docker", "AWS", "GCP", "Azure", "Terraform", "CI/CD",
    "REST", "GraphQL", "PostgreSQL", "MySQL", "MongoDB", "Redis",
    "Gradle", "Maven", "JVM", "Hibernate", "JPA", "Reactive",
    "Coroutines", "gRPC", "OpenAPI", "Swagger", "TDD", "DDD",
    "Event-driven", "CQRS", "Git", "Agile", "Scrum",
]

def extract_skills(text: str) -> list[str]:
    text_lower = text.lower()
    return [s for s in SKILLS_VOCAB if s.lower() in text_lower]

def extract_ir35(text: str) -> str:
    t = text.lower()
    if "outside ir35" in t:
        return "outside IR35"
    if "inside ir35" in t:
        return "inside IR35"
    return "not specified"

def extract_overseas(text: str) -> str:
    t = text.lower()
    notes = []
    if any(x in t for x in ["right to work", "right-to-work"]):
        notes.append("requires right to work in UK")
    if any(x in t for x in ["no sponsorship", "unable to sponsor", "cannot sponsor"]):
        notes.append("no visa sponsorship")
    if any(x in t for x in ["sc clearance", "dv clearance", "security clearance", "nsc", "bpss"]):
        notes.append("security clearance required")
    if any(x in t for x in ["overseas", "non-uk", "remote worldwide", "work from anywhere"]):
        notes.append("overseas/non-UK mentioned")
    return "; ".join(notes) if notes else "no restriction stated"

def is_remote(text: str) -> bool:
    t = text.lower()
    return any(x in t for x in ["remote", "work from home", "wfh", "fully remote", "home based"])

def rate_str(job: dict) -> str:
    lo, hi = job.get("salary_min"), job.get("salary_max")
    if lo and hi:
        return f"£{int(lo):,}–£{int(hi):,}"
    if lo:
        return f"£{int(lo):,}+"
    if hi:
        return f"up to £{int(hi):,}"
    return "rate not stated"


# ── Accumulation ──────────────────────────────────────────────────────────────

def load_store() -> dict:
    if VACANCIES_FILE.exists():
        try:
            return json.loads(VACANCIES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"vacancies": {}, "runs": []}


def save_store(store: dict) -> None:
    VACANCIES_FILE.write_text(
        json.dumps(store, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def accumulate(store: dict, new_jobs: list[dict]) -> tuple[list[dict], list[dict]]:
    """Return (added, already_seen) lists."""
    added, seen = [], []
    for job in new_jobs:
        jid = job["id"]
        if jid not in store["vacancies"]:
            store["vacancies"][jid] = job
            added.append(job)
        else:
            seen.append(job)
    store["runs"].append({
        "date": SEARCH_DATE,
        "ts":   SEARCH_TS,
        "fetched": len(new_jobs),
        "new":     len(added),
        "total_in_store": len(store["vacancies"]),
    })
    return added, seen


# ── Filter ────────────────────────────────────────────────────────────────────

def is_senior(job: dict) -> bool:
    t = (job["title"] + " " + job["description"]).lower()
    senior_kw = ["senior", "lead", "principal", "staff engineer", "sr.", "architect",
                 "5+ years", "5 years", "6+ years", "7+ years", "8+ years"]
    return any(k in t for k in senior_kw)

def is_kotlin_or_java(job: dict) -> bool:
    t = (job["title"] + " " + job["description"]).lower()
    return "kotlin" in t or "java" in t

def overseas_ok(job: dict) -> bool:
    notes = job.get("overseas_notes", "")
    blockers = ["requires right to work", "security clearance required"]
    return not any(b in notes for b in blockers)

def filter_jobs(jobs: list[dict]) -> list[dict]:
    return [j for j in jobs if is_senior(j) and is_kotlin_or_java(j) and overseas_ok(j)]


# ── Digest text ───────────────────────────────────────────────────────────────

def build_digest(new_jobs: list[dict], store: dict) -> tuple[str, str]:
    total = len(store["vacancies"])
    run_info = store["runs"][-1] if store["runs"] else {}

    intro = (
        f"UK Senior Kotlin/Java Contract Digest — {SEARCH_DATE}\n"
        f"{'='*55}\n"
        f"New roles today: {len(new_jobs)} | "
        f"Total in archive: {total} | "
        f"Archive: {VACANCIES_FILE}\n"
    )

    if not new_jobs:
        body_txt = intro + "\nNo new matching roles found in the last 24 hours.\n"
        body_html = f"<p>{intro.replace(chr(10),'<br>')}</p><p>No new matching roles found.</p>"
        return body_txt, body_html

    rows_txt, rows_html = [], []
    for i, job in enumerate(new_jobs, 1):
        skills = ", ".join(job["key_skills"]) or "see description"
        txt = (
            f"\n{'─'*55}\n"
            f"{i}. {job['title']}\n"
            f"   Company:       {job['company'] or 'not stated'}\n"
            f"   Location:      {job['location']}{'  [REMOTE]' if job['remote'] else ''}\n"
            f"   Rate:          {rate_str(job)}\n"
            f"   IR35:          {job['ir35_status']}\n"
            f"   Overseas:      {job['overseas_notes']}\n"
            f"   Key skills:    {skills}\n"
            f"   Posted:        {job['created'][:10] if job['created'] else 'unknown'}\n"
            f"   Apply:         {job['redirect_url']}\n"
            f"\n   Full requirements:\n"
            f"   {job['description'][:1200].strip()}\n"
            + ("   [description truncated — see archive for full text]\n"
               if len(job["description"]) > 1200 else "")
        )
        rows_txt.append(txt)

        html = (
            f"<hr><h3>{i}. {job['title']}</h3>"
            f"<table>"
            f"<tr><td><b>Company</b></td><td>{job['company'] or 'not stated'}</td></tr>"
            f"<tr><td><b>Location</b></td><td>{job['location']}{'&nbsp;<b>[REMOTE]</b>' if job['remote'] else ''}</td></tr>"
            f"<tr><td><b>Rate</b></td><td>{rate_str(job)}</td></tr>"
            f"<tr><td><b>IR35</b></td><td>{job['ir35_status']}</td></tr>"
            f"<tr><td><b>Overseas</b></td><td>{job['overseas_notes']}</td></tr>"
            f"<tr><td><b>Key skills</b></td><td>{skills}</td></tr>"
            f"<tr><td><b>Posted</b></td><td>{job['created'][:10] if job['created'] else 'unknown'}</td></tr>"
            f"<tr><td><b>Apply</b></td><td><a href='{job['redirect_url']}'>{job['redirect_url']}</a></td></tr>"
            f"</table>"
            f"<details><summary>Full requirements (click to expand)</summary>"
            f"<pre style='white-space:pre-wrap'>{job['description'][:3000]}</pre>"
            + ("<p><i>[truncated — full text in archive]</i></p>" if len(job["description"]) > 3000 else "")
            + "</details>"
        )
        rows_html.append(html)

    footer_txt = (
        f"\n{'='*55}\n"
        f"Roles in this digest: {len(new_jobs)}\n"
        f"Total accumulated:    {total}\n"
        f"Archive file:         {VACANCIES_FILE}\n"
        f"Search date:          {SEARCH_DATE}\n"
    )

    body_txt  = intro + "".join(rows_txt) + footer_txt
    body_html = (
        f"<h2>UK Senior Kotlin/Java Contract Digest — {SEARCH_DATE}</h2>"
        f"<p>New roles today: <b>{len(new_jobs)}</b> | "
        f"Total in archive: <b>{total}</b></p>"
        + "".join(rows_html)
        + f"<hr><p><small>Archive: {VACANCIES_FILE} | {SEARCH_DATE}</small></p>"
    )
    return body_txt, body_html


# ── Delivery ──────────────────────────────────────────────────────────────────

def deliver_console(body_txt: str) -> None:
    print(body_txt)


def _tg_send(text: str) -> None:
    """Send one message; Telegram max is 4096 chars — split if needed."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    for chunk in chunks:
        payload = json.dumps({
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }).encode()
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.load(r)
            if not resp.get("ok"):
                raise RuntimeError(f"Telegram API error: {resp}")


def build_tg_digest(new_jobs: list[dict], store: dict) -> str:
    total = len(store["vacancies"])
    if not new_jobs:
        return (
            f"<b>UK Job Digest — {SEARCH_DATE}</b>\n\n"
            f"No new senior Kotlin/Java contract roles in the last 24h.\n"
            f"Total in archive: {total}"
        )

    lines = [f"<b>UK Job Digest — {SEARCH_DATE}</b>",
             f"New roles: <b>{len(new_jobs)}</b>  |  Archive: <b>{total}</b>\n"]

    for i, job in enumerate(new_jobs, 1):
        skills  = ", ".join(job["key_skills"]) or "see description"
        remote  = " [REMOTE]" if job["remote"] else ""
        lines.append(
            f"<b>{i}. {job['title']}</b>\n"
            f"🏢 {job['company'] or 'not stated'}\n"
            f"📍 {job['location']}{remote}\n"
            f"💰 {rate_str(job)}\n"
            f"⚖️  IR35: {job['ir35_status']}\n"
            f"🌍 Overseas: {job['overseas_notes']}\n"
            f"🛠 {skills}\n"
            f"📅 Posted: {job['created'][:10] if job['created'] else '—'}\n"
            f"🔗 <a href='{job['redirect_url']}'>Apply</a>\n"
            f"\n<b>Requirements:</b>\n"
            f"{job['description'][:800].strip()}"
            + (" …[full text in archive]" if len(job["description"]) > 800 else "")
            + "\n"
        )

    lines.append(f"\n<i>Archive: {VACANCIES_FILE}</i>")
    return "\n".join(lines)


def deliver_telegram(new_jobs: list[dict], store: dict) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("[TG] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set — falling back to console",
              file=sys.stderr)
        body_txt, _ = build_digest(new_jobs, store)
        deliver_console(body_txt)
        return

    # Send header + one message per job (avoids 4096-char limit on big descriptions)
    total = len(store["vacancies"])
    try:
        if not new_jobs:
            _tg_send(
                f"<b>UK Job Digest — {SEARCH_DATE}</b>\n\n"
                f"No new senior Kotlin/Java contract roles in the last 24h.\n"
                f"Total in archive: <b>{total}</b>"
            )
        else:
            _tg_send(
                f"<b>UK Job Digest — {SEARCH_DATE}</b>\n"
                f"New roles: <b>{len(new_jobs)}</b>  |  Archive: <b>{total}</b>"
            )
            for i, job in enumerate(new_jobs, 1):
                skills = ", ".join(job["key_skills"]) or "see description"
                remote = " [REMOTE]" if job["remote"] else ""
                desc   = job["description"][:1200].strip()
                tail   = "\n…<i>[truncated — full text in archive]</i>" if len(job["description"]) > 1200 else ""
                msg = (
                    f"<b>{i}. {job['title']}</b>\n"
                    f"🏢 <b>Company:</b> {job['company'] or 'not stated'}\n"
                    f"📍 <b>Location:</b> {job['location']}{remote}\n"
                    f"💰 <b>Rate:</b> {rate_str(job)}\n"
                    f"⚖️  <b>IR35:</b> {job['ir35_status']}\n"
                    f"🌍 <b>Overseas:</b> {job['overseas_notes']}\n"
                    f"🛠 <b>Skills:</b> {skills}\n"
                    f"📅 <b>Posted:</b> {job['created'][:10] if job['created'] else '—'}\n"
                    f"🔗 <b>Apply:</b> <a href='{job['redirect_url']}'>{job['redirect_url']}</a>\n\n"
                    f"<b>Full requirements:</b>\n{desc}{tail}"
                )
                _tg_send(msg)
        print(f"[TG] Digest sent to chat {TELEGRAM_CHAT_ID}")
    except Exception as e:
        print(f"[TG] Send failed: {e} — falling back to console", file=sys.stderr)
        body_txt, _ = build_digest(new_jobs, store)
        deliver_console(body_txt)


def deliver_email(body_txt: str, body_html: str, new_count: int) -> None:
    if not EMAIL_TO:
        print("[EMAIL] EMAIL_TO not set — falling back to console", file=sys.stderr)
        deliver_console(body_txt)
        return
    if not SMTP_PASS:
        print("[EMAIL] SMTP_PASS not set — falling back to console", file=sys.stderr)
        deliver_console(body_txt)
        return

    subject = (
        f"[Job Digest] {new_count} new UK Kotlin/Java contracts — {SEARCH_DATE}"
        if new_count
        else f"[Job Digest] No new UK Kotlin/Java contracts — {SEARCH_DATE}"
    )
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_USER
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText(body_txt,  "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html",  "utf-8"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
            s.ehlo()
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(SMTP_USER, [EMAIL_TO], msg.as_bytes())
        print(f"[EMAIL] Digest sent to {EMAIL_TO}")
    except Exception as e:
        print(f"[EMAIL] Send failed: {e} — falling back to console", file=sys.stderr)
        deliver_console(body_txt)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"[{SEARCH_TS}] Fetching jobs …", file=sys.stderr)

    raw = fetch_adzuna() + fetch_reed() + fetch_web()
    print(f"[INFO] Fetched {len(raw)} raw jobs", file=sys.stderr)

    filtered = filter_jobs(raw)
    print(f"[INFO] {len(filtered)} passed senior/Kotlin/Java/overseas filter", file=sys.stderr)

    store = load_store()
    new_jobs, _ = accumulate(store, filtered)
    save_store(store)
    print(f"[INFO] {len(new_jobs)} new | {len(store['vacancies'])} total in archive", file=sys.stderr)

    body_txt, body_html = build_digest(new_jobs, store)

    if DELIVERY == "telegram":
        deliver_telegram(new_jobs, store)
    elif DELIVERY == "email":
        deliver_email(body_txt, body_html, len(new_jobs))
    else:
        deliver_console(body_txt)


if __name__ == "__main__":
    main()
