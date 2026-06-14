#!/usr/bin/env python3
"""
Skill analysis for UK senior Kotlin/Java contract vacancies.

Filters: fully remote  +  outside IR35  +  rate >= MIN_RATE/day
Outputs: skill frequency ranking, co-occurrence pairs, clusters (if sklearn available)

Usage:
    python analyze.py                     # default: rate >= 500
    python analyze.py --min-rate 400
    python analyze.py --min-rate 500 --top 30
    python analyze.py --min-rate 500 --clusters 6
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

VACANCIES_FILE = Path(__file__).parent / "data" / "job_vacancies.json"

# Comprehensive skill taxonomy
SKILLS = {
    # Languages
    "Kotlin": r"\bkotlin\b",
    "Java": r"\bjava\b(?! ?script)",
    "JavaScript": r"\bjavascript\b|\bjs\b",
    "TypeScript": r"\btypescript\b|\bts\b",
    "Python": r"\bpython\b",
    "Go / Golang": r"\bgolang\b|\bgo\b(?= developer| engineer| backend| lang)",
    "Scala": r"\bscala\b",
    "Groovy": r"\bgroovy\b",
    "SQL": r"\bsql\b",

    # Frameworks / Libraries
    "Spring Boot": r"\bspring\s*boot\b",
    "Spring": r"\bspring\s*(?:framework|mvc|core|security|data|cloud)?\b",
    "Micronaut": r"\bmicronaut\b",
    "Quarkus": r"\bquarkus\b",
    "Ktor": r"\bktor\b",
    "Hibernate / JPA": r"\bhibernate\b|\bjpa\b",
    "gRPC": r"\bgrpc\b",
    "GraphQL": r"\bgraphql\b",
    "REST / RESTful": r"\brest(?:ful)?\s*api\b|\brest\s*(?:services|endpoints)\b",
    "Reactive / WebFlux": r"\breactive\b|\bwebflux\b|\breactor\b|\bproject\s*reactor\b",
    "Coroutines": r"\bcoroutines?\b",

    # Architecture / Patterns
    "Microservices": r"\bmicroservices?\b",
    "Event-Driven": r"\bevent.driven\b",
    "CQRS": r"\bcqrs\b",
    "DDD": r"\bdomain.driven\b|\bddd\b",
    "Hexagonal / Clean Arch": r"\bhexagonal\b|\bclean\s*architecture\b|\bonion\b",
    "SOLID": r"\bsolid\b(?= principles| design)",
    "TDD / BDD": r"\btdd\b|\bbdd\b|\btest.driven\b|\bbehaviour.driven\b",

    # Messaging
    "Kafka": r"\bkafka\b",
    "RabbitMQ": r"\brabbitmq\b",
    "ActiveMQ": r"\bactivemq\b",
    "SQS / SNS": r"\bsqs\b|\bsns\b",

    # Cloud
    "AWS": r"\baws\b|\bamazon\s*web\s*services\b",
    "GCP": r"\bgcp\b|\bgoogle\s*cloud\b",
    "Azure": r"\bazure\b",
    "Terraform": r"\bterraform\b",
    "CDK": r"\bcdk\b|\bcloud\s*development\s*kit\b",

    # Containers / Orchestration
    "Docker": r"\bdocker\b",
    "Kubernetes / K8s": r"\bkubernetes\b|\bk8s\b",
    "Helm": r"\bhelm\b(?= chart)",
    "ECS / EKS": r"\becs\b|\beks\b",

    # CI/CD
    "CI/CD": r"\bci/?\s*cd\b|\bcontinuous\s*(?:integration|delivery|deployment)\b",
    "GitHub Actions": r"\bgithub\s*actions\b",
    "Jenkins": r"\bjenkins\b",
    "GitLab CI": r"\bgitlab\s*ci\b",
    "ArgoCD": r"\bargocd\b",

    # Observability
    "Observability": r"\bobservability\b|\bmonitoring\b",
    "Prometheus": r"\bprometheus\b",
    "Grafana": r"\bgrafana\b",
    "Datadog": r"\bdatadog\b",
    "OpenTelemetry": r"\bopentelemetry\b|\botel\b",

    # Databases
    "PostgreSQL": r"\bpostgres(?:ql)?\b",
    "MySQL": r"\bmysql\b",
    "MongoDB": r"\bmongodb\b",
    "Redis": r"\bredis\b",
    "Elasticsearch": r"\belasticsearch\b|\belastic\b",
    "Cassandra": r"\bcassandra\b",
    "DynamoDB": r"\bdynamodb\b",

    # Build tools
    "Gradle": r"\bgradle\b",
    "Maven": r"\bmaven\b",

    # Security / Compliance
    "OAuth2 / OIDC": r"\boauth2?\b|\boidc\b|\bkeycloak\b",
    "Security / Auth": r"\bsecurity\b|\bauthentication\b|\bauthorisation\b",

    # Soft / Process
    "Agile / Scrum": r"\bagile\b|\bscrum\b|\bkanban\b",
    "Git": r"\bgit\b(?! hub| lab| ops)",
    "API Design": r"\bapi\s*design\b|\bapi.first\b|\bopenapi\b|\bswagger\b",

    # Domain-specific
    "FinTech / Finance": r"\bfintech\b|\bfinancial\s*services\b|\btrading\b|\bpayments?\b",
    "HealthTech": r"\bhealthtech\b|\bhealthcare\b|\bnhs\b",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def extract_skills(text: str) -> list[str]:
    text = text.lower()
    return [name for name, pattern in SKILLS.items() if re.search(pattern, text)]


def _job_text(job: dict) -> str:
    return (job.get("title", "") + " " + job.get("description", "")).lower()


# ── Radar classification (overseas-contractor fit) ───────────────────────────

# Onsite / hybrid signals — any required UK presence is a structural blocker
_HYBRID_RE = re.compile(
    r"\bhybrid\b"
    r"|\bon[\s-]?site\b"
    r"|\bin[\s-]the[\s-]office\b"
    r"|\b\d\s*days?\s*(?:a|per)\s*week\b"
    r"|\bdays?\s*(?:a|per)\s*week\s*(?:in|on)\b"
    r"|\boccasional(?:ly)?\s*(?:travel|visit|on[\s-]?site|office)\b"
    r"|\btravel\s*to\s*(?:the\s*)?(?:office|london|client)\b"
    r"|\bweekly\s*in\s*the\s*office\b",
    re.IGNORECASE,
)

_FULLY_REMOTE_RE = re.compile(
    r"\bfully\s*remote\b|\b100%\s*remote\b|\bremote[\s-]first\b"
    r"|\bwork\s*from\s*anywhere\b|\bremote\s*\(?\s*(?:worldwide|global|europe|eu)\b",
    re.IGNORECASE,
)
_REMOTE_RE = re.compile(r"\bremote\b|\bwork\s*from\s*home\b|\bwfh\b", re.IGNORECASE)

# UK-residency / clearance restrictions that exclude an overseas contractor
_UK_ONLY_RE = re.compile(
    r"\buk[\s-]based\b"
    r"|\bbased\s*(?:in|within)\s*(?:the\s*)?uk\b"
    r"|\buk\s*residents?\b"
    r"|\bmust\s*(?:be\s*)?(?:located|reside|live)\s*(?:in|within)\s*(?:the\s*)?uk\b"
    r"|\bright\s*to\s*work\s*in\s*the\s*uk\b"
    r"|\bmust\s*have\s*(?:the\s*)?right\s*to\s*work\b"
    r"|\bno\s*sponsorship\b|\b(?:cannot|unable\s*to)\s*(?:provide\s*)?sponsor"
    r"|\bsc\s*clear|\bdv\s*clear|\bsecurity\s*clear|\bbpss\b"
    r"|\beligible\s*to\s*work\s*in\s*the\s*uk\b",
    re.IGNORECASE,
)

# Agency / recruiter signals
_AGENCY_NAME_RE = re.compile(
    r"recruit|consult|resourc|talent|staffing|\bsearch\b|people|solutions"
    r"|associates|partners|frank\b|harvey nash|hays|robert half|lorien|experis"
    r"|sthree|nigel frank|understanding|oliver bernard|technet|virtuetech|spinks"
    r"|opus|x4|tenth revolution|in technology|cv-?library",
    re.IGNORECASE,
)
_AGENCY_PHRASE_RE = re.compile(
    r"\bour\s*client\b|\bmy\s*client\b|\bon\s*behalf\s*of\b"
    r"|\bwe\s*are\s*(?:working\s*with|partnering)\b|\bworking\s*(?:with|on\s*behalf)\b"
    r"|\bleading\s*(?:recruitment|agency)\b|\b(?:a|our)\s*(?:client|customer)\s*(?:is|are|based)\b",
    re.IGNORECASE,
)


def remote_type(job: dict) -> str:
    """fully_remote | hybrid | remote_unclear | onsite | unknown"""
    t = _job_text(job)
    if _HYBRID_RE.search(t):
        return "hybrid"
    if _FULLY_REMOTE_RE.search(t):
        return "fully_remote"
    if _REMOTE_RE.search(t):
        return "remote_unclear"
    return "unknown"


def is_uk_only(job: dict) -> bool:
    return bool(_UK_ONLY_RE.search(_job_text(job)))


def client_type(job: dict) -> str:
    """direct | agency | unknown"""
    name = job.get("company", "") or ""
    text = job.get("description", "") or ""
    agency = bool(_AGENCY_NAME_RE.search(name)) or bool(_AGENCY_PHRASE_RE.search(text))
    if agency:
        return "agency"
    if name.strip():           # named end-employer, no agency markers
        return "direct"
    return "unknown"


def overseas_fit(job: dict) -> bool:
    """Structurally applicable for a non-UK-resident contractor."""
    return remote_type(job) == "fully_remote" and not is_uk_only(job)


def parse_rate(job: dict) -> float | None:
    """Return the best daily-rate estimate from a job record."""
    lo = job.get("salary_min")
    hi = job.get("salary_max")
    # Adzuna returns annual figures; daily rate typically 200–800 → if > 2000 it's annual
    def _daily(v):
        if v is None:
            return None
        v = float(v)
        return v / 220 if v > 2000 else v   # 220 working days/year

    d_lo = _daily(lo)
    d_hi = _daily(hi)
    if d_lo and d_hi:
        return (d_lo + d_hi) / 2
    return d_lo or d_hi


def is_outside_ir35(job: dict) -> bool:
    return "outside" in job.get("ir35_status", "").lower()


# ── Analysis ──────────────────────────────────────────────────────────────────

def load_jobs(path: Path) -> list[dict]:
    if not path.exists():
        sys.exit(f"[ERROR] Archive not found: {path}\nRun: DAYS_LOOKBACK=165 bash run_digest.sh")
    store = json.loads(path.read_text())
    return list(store.get("vacancies", {}).values())


def filter_jobs(jobs: list[dict], min_rate: float) -> list[dict]:
    """Strict overseas-contractor filter: fully remote, not UK-only, outside IR35, rate."""
    out = []
    for job in jobs:
        if not overseas_fit(job):
            continue
        if not is_outside_ir35(job):
            continue
        rate = parse_rate(job)
        if rate is None or rate < min_rate:
            continue
        out.append(job)
    return out


def radar_funnel(jobs: list[dict], min_rate: float) -> dict:
    """Step-by-step attrition so you can see where roles drop out."""
    f = {"total": len(jobs)}
    s1 = [j for j in jobs if remote_type(j) == "fully_remote"]
    f["fully_remote"] = len(s1)
    f["hybrid"]       = sum(1 for j in jobs if remote_type(j) == "hybrid")
    f["remote_unclear"] = sum(1 for j in jobs if remote_type(j) == "remote_unclear")
    s2 = [j for j in s1 if not is_uk_only(j)]
    f["not_uk_only"]  = len(s2)
    f["uk_only_dropped"] = len(s1) - len(s2)
    s3 = [j for j in s2 if is_outside_ir35(j)]
    f["outside_ir35"] = len(s3)
    f["no_rate_data"] = sum(1 for j in s3 if parse_rate(j) is None)
    s4 = [j for j in s3 if (r := parse_rate(j)) is not None and r >= min_rate]
    f["rate_ok"] = len(s4)
    # client split on the final cleaned set
    f["final_direct"] = sum(1 for j in s4 if client_type(j) == "direct")
    f["final_agency"] = sum(1 for j in s4 if client_type(j) == "agency")
    f["final_unknown"] = sum(1 for j in s4 if client_type(j) == "unknown")
    return f


def skill_frequency(jobs: list[dict]) -> Counter:
    c = Counter()
    for job in jobs:
        text = job.get("title", "") + " " + job.get("description", "")
        for skill in extract_skills(text):
            c[skill] += 1
    return c


def skill_cooccurrence(jobs: list[dict], top_skills: list[str]) -> dict:
    skill_set = set(top_skills)
    co = defaultdict(Counter)
    for job in jobs:
        text = job.get("title", "") + " " + job.get("description", "")
        present = [s for s in extract_skills(text) if s in skill_set]
        for i, a in enumerate(present):
            for b in present[i+1:]:
                co[a][b] += 1
                co[b][a] += 1
    return co


def cluster_jobs(jobs: list[dict], n_clusters: int) -> list[tuple[int, list[str], list[str]]]:
    """K-means clustering using sklearn. Returns list of (cluster_id, top_skills, job_titles)."""
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.cluster import KMeans
        import numpy as np
    except ImportError:
        return []

    corpus = [
        (job.get("title", "") + " " + job.get("description", ""))[:3000]
        for job in jobs
    ]
    if len(corpus) < n_clusters:
        n_clusters = max(2, len(corpus))

    vec = TfidfVectorizer(max_features=200, stop_words="english",
                          token_pattern=r"[a-zA-Z#\+\.]{2,}")
    X = vec.fit_transform(corpus)
    km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = km.fit_predict(X)

    feature_names = vec.get_feature_names_out()
    results = []
    for cid in range(n_clusters):
        idxs = np.where(labels == cid)[0]
        center = km.cluster_centers_[cid]
        top_idx = center.argsort()[::-1][:12]
        top_terms = [feature_names[i] for i in top_idx]
        titles = [jobs[i]["title"] for i in idxs[:5]]
        results.append((cid, top_terms, titles))
    return results


# ── Report ────────────────────────────────────────────────────────────────────

def print_report(jobs_all: list[dict], jobs_filtered: list[dict],
                 min_rate: float, top_n: int, n_clusters: int) -> None:

    print(f"\n{'='*60}")
    print(f"  UK CONTRACT JOB SKILL ANALYSIS")
    print(f"  Filter: fully remote (overseas-OK) | outside IR35 | >= £{min_rate:.0f}/day")
    print(f"{'='*60}")
    print(f"  Total in archive:  {len(jobs_all)}")
    print(f"  After filter:      {len(jobs_filtered)}")

    # ── Radar funnel: where roles drop out ───────────────────────
    f = radar_funnel(jobs_all, min_rate)
    print(f"\n{'─'*60}")
    print(f"  RADAR FUNNEL  (overseas-contractor structural fit)")
    print(f"{'─'*60}")
    print(f"  Total collected ............... {f['total']:>3}")
    print(f"  ├─ fully remote ............... {f['fully_remote']:>3}")
    print(f"  │   (dropped: hybrid {f['hybrid']}, remote-unclear {f['remote_unclear']})")
    print(f"  ├─ not UK-only / no clearance . {f['not_uk_only']:>3}   (−{f['uk_only_dropped']} UK-only)")
    print(f"  ├─ outside IR35 ............... {f['outside_ir35']:>3}")
    print(f"  └─ rate >= £{min_rate:.0f}/day ......... {f['rate_ok']:>3}  ← your reachable pool")
    if f["no_rate_data"]:
        print(f"      (note: {f['no_rate_data']} outside-IR35 roles had NO rate data — "
              f"excluded here, may still qualify)")
    print(f"\n  Final pool by client type:")
    print(f"    • Direct client ... {f['final_direct']:>3}   (best — hire internationally)")
    print(f"    • Agency .......... {f['final_agency']:>3}   (often UK-only by default)")
    print(f"    • Unknown ......... {f['final_unknown']:>3}")

    if not jobs_filtered:
        print("\n  No jobs pass the strict overseas filter yet.")
        print("  Re-run with full descriptions: ENRICH=1 DAYS_LOOKBACK=165 bash run_digest.sh")
        return

    # ── Skill frequency ──────────────────────────────────────────
    freq = skill_frequency(jobs_filtered)
    print(f"\n{'─'*60}")
    print(f"  TOP {top_n} SKILLS  (by mention frequency)")
    print(f"{'─'*60}")
    top_skills = freq.most_common(top_n)
    max_count = top_skills[0][1] if top_skills else 1
    for skill, count in top_skills:
        pct  = count / len(jobs_filtered) * 100
        bar  = "█" * int(pct / 3)
        print(f"  {skill:<28} {bar:<20} {count:>3} jobs  ({pct:.0f}%)")

    # ── Core skill set (>50%) ────────────────────────────────────
    core = [(s, c) for s, c in top_skills if c / len(jobs_filtered) >= 0.5]
    if core:
        print(f"\n{'─'*60}")
        print(f"  CORE SKILLS (present in >50% of matching roles)")
        print(f"{'─'*60}")
        for skill, count in core:
            pct = count / len(jobs_filtered) * 100
            print(f"  ✓  {skill}  ({pct:.0f}%)")

    # ── Co-occurrence top pairs ──────────────────────────────────
    top_names = [s for s, _ in freq.most_common(20)]
    co = skill_cooccurrence(jobs_filtered, top_names)
    pairs = []
    seen = set()
    for a, others in co.items():
        for b, cnt in others.items():
            key = tuple(sorted([a, b]))
            if key not in seen and cnt > 1:
                pairs.append((cnt, a, b))
                seen.add(key)
    pairs.sort(reverse=True)

    if pairs:
        print(f"\n{'─'*60}")
        print(f"  TOP SKILL COMBINATIONS (co-occur most often)")
        print(f"{'─'*60}")
        for cnt, a, b in pairs[:15]:
            print(f"  {a}  +  {b:<28}  ×{cnt}")

    # ── Clusters ─────────────────────────────────────────────────
    if n_clusters > 0:
        clusters = cluster_jobs(jobs_filtered, n_clusters)
        if clusters:
            print(f"\n{'─'*60}")
            print(f"  JOB CLUSTERS  (k-means, k={len(clusters)})")
            print(f"{'─'*60}")
            for cid, terms, titles in clusters:
                print(f"\n  Cluster {cid+1}: {', '.join(terms[:8])}")
                for t in titles:
                    print(f"    • {t}")
        elif n_clusters > 0:
            print("\n  [clusters] Install scikit-learn for ML clustering:")
            print("  pip install scikit-learn")

    # ── Rate distribution ────────────────────────────────────────
    rates = [r for job in jobs_filtered if (r := parse_rate(job)) is not None]
    if rates:
        rates.sort()
        n = len(rates)
        print(f"\n{'─'*60}")
        print(f"  RATE DISTRIBUTION  (matching roles, £/day)")
        print(f"{'─'*60}")
        print(f"  Min:    £{min(rates):.0f}")
        print(f"  Median: £{rates[n//2]:.0f}")
        print(f"  P75:    £{rates[int(n*0.75)]:.0f}")
        print(f"  Max:    £{max(rates):.0f}")
        buckets = [(500,600),(600,700),(700,800),(800,9999)]
        for lo, hi in buckets:
            cnt = sum(1 for r in rates if lo <= r < hi)
            label = f"£{lo}–£{hi}/d" if hi < 9999 else f"£{lo}+/d"
            print(f"  {label:<14} {'█'*cnt} {cnt}")

    # ── The actual reachable shortlist ───────────────────────────
    print(f"\n{'─'*60}")
    print(f"  YOUR SHORTLIST  (fully remote · not UK-only · outside IR35 · £{min_rate:.0f}+)")
    print(f"{'─'*60}")
    # direct clients first — they hire internationally more often
    ranked = sorted(jobs_filtered,
                    key=lambda j: (client_type(j) != "direct", -(parse_rate(j) or 0)))
    for job in ranked:
        ct = client_type(job)
        tag = {"direct": "[DIRECT]", "agency": "[agency]", "unknown": "[?]"}[ct]
        rate = parse_rate(job)
        rate_s = f"£{rate:.0f}/d" if rate else "rate n/a"
        print(f"  {tag:<9} {rate_s:<9} {job['title'][:50]}")
        print(f"            {job.get('company') or '—'}  |  {job.get('redirect_url','')[:60]}")

    print(f"\n{'='*60}\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    default_file = str(Path(__file__).parent / "data" / "job_vacancies.json")
    p = argparse.ArgumentParser(description="Analyse job vacancies archive")
    p.add_argument("--min-rate",  type=float, default=500,
                   help="Minimum daily rate in GBP (default: 500)")
    p.add_argument("--top",       type=int,   default=25,
                   help="Number of top skills to show (default: 25)")
    p.add_argument("--clusters",  type=int,   default=0,
                   help="K-means clusters (0=off, needs scikit-learn)")
    p.add_argument("--file",      type=str,   default=default_file,
                   help="Path to job_vacancies.json")
    args = p.parse_args()

    path          = Path(args.file)
    jobs_all      = load_jobs(path)
    jobs_filtered = filter_jobs(jobs_all, args.min_rate)
    print_report(jobs_all, jobs_filtered, args.min_rate, args.top, args.clusters)


if __name__ == "__main__":
    main()
