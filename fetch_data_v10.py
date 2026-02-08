#!/usr/bin/env python3
"""
EDM Monitor - Automated Data Fetcher v10
Event-Driven Markets / Prediction Markets / Event Contracts

CHANGES IN V10:
- MUCH tighter Federal Register filtering - title must contain relevant keywords
- Auto-upgrade to Tier 1 if URL contains .gov
- Better source detection for CFTC, SEC, state gaming
- Cleaner news filtering - only approved quality sources
- Smarter category assignment (enforcement, courts detected from keywords)

CATEGORIES (must match index.html):
- federal: CFTC, SEC, Federal Register, NFA regulatory actions
- state: State gaming commissions, state-level regulation
- enforcement: Cease & desist, penalties, fines, enforcement actions
- courts: Court rulings, lawsuits, injunctions, litigation
- trade: AGA, Indian Gaming Association, trade groups
- participants: Kalshi, Polymarket, Nadex, prediction market companies
- news: Quality news coverage (Tier 3)
"""

import feedparser
import requests
import csv
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set
import re
import hashlib
from bs4 import BeautifulSoup
import time
import os

# =============================================================================
# CONFIGURATION
# =============================================================================

SEEN_URLS_FILE = "seen_urls.txt"
OUTPUT_DRAFT_CSV = "data_draft.csv"
OUTPUT_DRAFT_JSON = "data_draft.json"

# STRICT keywords - title MUST contain at least one of these
STRICT_KEYWORDS = [
    "prediction market", "prediction markets",
    "event contract", "event contracts",
    "kalshi", "polymarket", "forecastex", "nadex", "predictit",
    "designated contract market", "dcm",
    "binary option", "binary options",
    "election contract", "election contracts",
    "sports betting", "sports wagering", "sports wager",
    "event-based", "event based",
    "robinhood prediction", "coinbase prediction",
    "gemini titan", "xchange alpha",
]

# Broader relevance keywords (for secondary check)
RELEVANCE_KEYWORDS = [
    "cftc", "commodity futures trading",
    "gaming commission", "gaming control",
    "gambling", "wagering",
]

# High priority keywords
HIGH_PRIORITY_KEYWORDS = [
    "ruling", "ruled", "court order", "injunction", "restraining order",
    "enforcement", "cease and desist", "penalty", "fine", "settlement",
    "approved", "denied", "granted", "rejected", "blocked",
    "lawsuit", "litigation", "appeals court", "circuit court",
    "withdrawal", "withdrawn", "rescind", "rescinded", "vacated", "overturned",
    "designated", "designation", "license", "licensed", "registration",
    "banned", "prohibited", "illegal", "unlawful",
    "no-action", "no action letter", "staff letter",
    "amended order", "order of designation",
]

# Category detection keywords
ENFORCEMENT_KEYWORDS = [
    "enforcement", "cease and desist", "cease-and-desist", "penalty", "fine",
    "settlement", "violation", "enforcement action", "civil penalty",
    "consent order", "disciplinary", "sanction", "warning", "alert",
    "attorney general", "ag ", " ag,", "warns",
]

COURTS_KEYWORDS = [
    "court", "judge", "ruling", "ruled", "lawsuit", "litigation", "injunction",
    "restraining order", "appeal", "appeals court", "circuit court", "district court",
    "supreme court", "plaintiff", "defendant", "complaint filed", "motion",
    "preliminary injunction", "temporary restraining", "tro", "class action",
]

# Excluded domains - law firm commentary, crypto sites, betting sites
EXCLUDED_DOMAINS = [
    "jdsupra.com", "lexology.com", "mondaq.com", "nationallawreview.com",
    "law.com", "lawfare", "law360",
    "seekingalpha.com", "patch.com", "triblive.com", "wesa.fm", "wpxi.com",
    "abc27.com", "boston25", "fox", "wgn", "wthr", "khou", "wfaa", "wcvb",
    "myheraldreview", "newsbreak.com", "aol.com",
    "financialcontent.com", "grafa", "bitget.com", "newsbtc",
    "actionnetwork.com", "sportsbettingdime.com", "legalsportsreport.com",
    "covers.com", "oddschecker.com", "vegasinsider.com",
    "medium.com", "substack.com",
]

# Sources that should be EXCLUDED from results
EXCLUDED_SOURCE_PATTERNS = [
    "Law360", "JD Supra", "Lexology", "Mondaq", "National Law Review",
    "Action Network", "Legal Sports Report", "Covers",
    "AOL", "Business Insider",
    "Bookies.com", "DeFi Rate", "iGamingToday",
]

# Quality news sources we trust
APPROVED_NEWS_SOURCES = [
    "reuters", "associated press", "ap news", "ap ",
    "bloomberg", "cnbc", "bbc", "npr", "guardian",
    "politico", "the hill", "axios", "washington post", "new york times",
    "wall street journal", "wsj", "financial times",
    "nbc news", "cbs news", "abc news", "cnn",
    "boston globe", "nevada independent",
]

# Government domains - auto Tier 1
GOV_DOMAINS = [
    ".gov", "federalregister.gov", "cftc.gov", "sec.gov", "nfa.futures.org",
    "gaming.nv.gov", "gaming.ny.gov", "gamingcontrolboard.pa.gov",
]

JUNK_PATTERNS = [
    r'^support@', r'^contact', r'^email', r'^subscribe', r'^newsletter',
    r'^read more', r'^learn more', r'^click here', r'^view all', r'^see all',
    r'^home$', r'^about$', r'^menu$', r'^search$', r'@.*\.org$', r'@.*\.com$',
]

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def is_strictly_relevant(text: str) -> bool:
    """Title MUST contain one of the strict keywords"""
    text_lower = text.lower()
    return any(kw in text_lower for kw in STRICT_KEYWORDS)


def is_broadly_relevant(text: str) -> bool:
    """Broader relevance check"""
    text_lower = text.lower()
    return any(kw in text_lower for kw in STRICT_KEYWORDS + RELEVANCE_KEYWORDS)


def is_gov_url(url: str) -> bool:
    """Check if URL is a government source"""
    url_lower = url.lower()
    return any(domain in url_lower for domain in GOV_DOMAINS)


def is_excluded_source(url: str, title: str = "", source: str = "") -> bool:
    """Check if source should be excluded"""
    url_lower = url.lower()
    
    # Check URL domains
    for domain in EXCLUDED_DOMAINS:
        if domain in url_lower:
            return True
    
    # Check source name patterns
    combined = f"{title} {source}".lower()
    for pattern in EXCLUDED_SOURCE_PATTERNS:
        if pattern.lower() in combined:
            return True
    
    return False


def is_approved_news(source_name: str) -> bool:
    """Check if news source is on our approved list"""
    source_lower = source_name.lower()
    return any(s in source_lower for s in APPROVED_NEWS_SOURCES)


def is_junk_title(title: str) -> bool:
    """Filter out navigation/junk text"""
    title_lower = title.lower().strip()
    if len(title_lower) < 15:
        return True
    for pattern in JUNK_PATTERNS:
        if re.search(pattern, title_lower):
            return True
    return False


def determine_priority(text: str) -> str:
    """Determine priority based on keywords"""
    text_lower = text.lower()
    if any(kw in text_lower for kw in HIGH_PRIORITY_KEYWORDS):
        return "high"
    return "medium"


def determine_category(title: str, source: str, url: str, base_category: str) -> str:
    """Determine the proper category for dashboard heatmap"""
    title_lower = title.lower()
    source_lower = source.lower()
    
    # Check for enforcement (highest priority - overrides others)
    if any(kw in title_lower for kw in ENFORCEMENT_KEYWORDS):
        return "enforcement"
    
    # Check for courts/litigation
    if any(kw in title_lower for kw in COURTS_KEYWORDS):
        return "courts"
    
    # Map base categories to dashboard categories
    if base_category == "industry":
        return "trade"
    
    # Keep other categories as-is if they match dashboard
    if base_category in ["federal", "state", "participants", "news", "trade"]:
        return base_category
    
    return base_category


def determine_tier(url: str, source: str, base_tier: int) -> int:
    """Auto-upgrade to Tier 1 if government source"""
    if is_gov_url(url):
        return 1
    
    source_lower = source.lower()
    if any(s in source_lower for s in ["cftc", "sec", "federal register", "nfa", "gaming commission", "gaming control", "attorney general"]):
        return 1
    
    return base_tier


def extract_state(text: str) -> Optional[str]:
    """Extract state from text"""
    states = {
        "nevada": "NV", "massachusetts": "MA", "new york": "NY",
        "new jersey": "NJ", "california": "CA", "texas": "TX",
        "pennsylvania": "PA", "michigan": "MI", "tennessee": "TN",
        "maryland": "MD", "connecticut": "CT", "florida": "FL",
        "illinois": "IL", "arizona": "AZ", "ohio": "OH",
    }
    text_lower = text.lower()
    for state, abbrev in states.items():
        if state in text_lower:
            return abbrev
    
    # Check for state abbreviations
    abbrev_pattern = r'\b(NV|MA|NY|NJ|CA|TX|PA|MI|TN|MD|CT|FL|IL|AZ|OH)\b'
    match = re.search(abbrev_pattern, text)
    if match:
        return match.group(1)
    
    return None


def parse_date(entry) -> str:
    """Parse date from feed entry"""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime(*entry.published_parsed[:3]).strftime("%Y-%m-%d")
    if hasattr(entry, "updated_parsed") and entry.updated_parsed:
        return datetime(*entry.updated_parsed[:3]).strftime("%Y-%m-%d")
    return datetime.now().strftime("%Y-%m-%d")


def clean_title(title: str) -> str:
    """Clean title - remove source suffix"""
    if " - " in title:
        title = title.rsplit(" - ", 1)[0].strip()
    title = re.sub(r'\s+', ' ', title).strip()
    return title


def extract_source(title: str) -> str:
    """Extract source from title"""
    if " - " in title:
        return title.rsplit(" - ", 1)[1].strip()
    return "News"


def deduplicate(items: List[Dict]) -> List[Dict]:
    """Remove duplicate items"""
    seen = set()
    unique = []
    for item in items:
        # Create key from normalized title
        key = re.sub(r'[^a-z0-9]', '', item["title"].lower())[:50]
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def generate_id(item: Dict) -> str:
    """Generate unique ID for item"""
    return hashlib.md5(f"{item['title']}{item['url']}".encode()).hexdigest()[:8]


def fetch_with_retry(url: str, retries: int = 2, timeout: int = 30) -> Optional[requests.Response]:
    """Fetch URL with retries"""
    for i in range(retries):
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            response = requests.get(url, headers=headers, timeout=timeout)
            if response.status_code == 200:
                return response
        except Exception as e:
            if i == retries - 1:
                print(f"      Failed: {e}")
    return None


def create_item(title: str, source: str, url: str, date: str, base_category: str, tier: int, state: str = None, needs_primary: bool = False) -> Dict:
    """Create a properly formatted item"""
    final_category = determine_category(title, source, url, base_category)
    final_tier = determine_tier(url, source, tier)
    
    return {
        "title": title,
        "source": source,
        "url": url,
        "date": date,
        "category": final_category,
        "tier": final_tier,
        "priority": determine_priority(title),
        "state": state or extract_state(title),
        "needs_primary_source": needs_primary,
    }


# =============================================================================
# SEEN URLS TRACKING
# =============================================================================

def load_seen_urls() -> Set[str]:
    """Load previously seen URLs from file"""
    seen = set()
    if os.path.exists(SEEN_URLS_FILE):
        with open(SEEN_URLS_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                url = line.strip()
                if url and not url.startswith('#'):
                    seen.add(url.lower())
    print(f"  Loaded {len(seen)} previously seen URLs")
    return seen


def is_new_url(url: str, seen_urls: Set[str]) -> bool:
    """Check if URL has not been seen before"""
    return url.lower() not in seen_urls


# =============================================================================
# TIER 1: FEDERAL GOVERNMENT SOURCES
# =============================================================================

def fetch_federal_register(days_back: int = 30, seen_urls: Set[str] = None) -> List[Dict]:
    """Fetch from Federal Register API - STRICT filtering"""
    print("    Federal Register API...")
    items = []
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back)
    
    # Very specific search terms
    search_terms = [
        '"event contract"',
        '"prediction market"',
        'Kalshi',
        'Polymarket',
        '"designated contract market"',
    ]
    
    for term in search_terms:
        try:
            url = "https://www.federalregister.gov/api/v1/documents.json"
            params = {
                "conditions[term]": term,
                "conditions[publication_date][gte]": start_date.strftime("%Y-%m-%d"),
                "conditions[publication_date][lte]": end_date.strftime("%Y-%m-%d"),
                "per_page": 20,
                "order": "newest",
            }
            response = requests.get(url, params=params, timeout=30)
            if response.status_code == 200:
                for doc in response.json().get("results", []):
                    title = doc.get("title", "")
                    doc_url = doc.get("html_url", "")
                    
                    if seen_urls and not is_new_url(doc_url, seen_urls):
                        continue
                    
                    # STRICT: Title must contain relevant keyword
                    if is_strictly_relevant(title):
                        items.append(create_item(
                            title=title,
                            source="Federal Register",
                            url=doc_url,
                            date=doc.get("publication_date", ""),
                            base_category="federal",
                            tier=1,
                        ))
        except Exception as e:
            print(f"      Error: {e}")
    
    print(f"      Found: {len(deduplicate(items))} new")
    return deduplicate(items)


def scrape_cftc_press_releases(seen_urls: Set[str] = None) -> List[Dict]:
    """Scrape CFTC press releases"""
    print("    CFTC Press Releases...")
    items = []
    
    try:
        response = fetch_with_retry("https://www.cftc.gov/PressRoom/PressReleases")
        if response:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            for link in soup.find_all('a', href=True):
                href = link.get('href', '')
                title = link.get_text(strip=True)
                
                if '/PressRoom/PressReleases/' in href and title and len(title) > 20:
                    full_url = f"https://www.cftc.gov{href}" if href.startswith('/') else href
                    
                    if seen_urls and not is_new_url(full_url, seen_urls):
                        continue
                    
                    # Include if strictly relevant OR broadly relevant (CFTC is always important)
                    if is_strictly_relevant(title) or is_broadly_relevant(title):
                        items.append(create_item(
                            title=title,
                            source="CFTC Press Release",
                            url=full_url,
                            date=datetime.now().strftime("%Y-%m-%d"),
                            base_category="federal",
                            tier=1,
                        ))
    except Exception as e:
        print(f"      Error: {e}")
    
    print(f"      Found: {len(items)} new")
    return items


def scrape_cftc_speeches(seen_urls: Set[str] = None) -> List[Dict]:
    """Scrape CFTC speeches and testimony"""
    print("    CFTC Speeches/Testimony...")
    items = []
    
    try:
        response = fetch_with_retry("https://www.cftc.gov/PressRoom/SpeechesTestimony")
        if response:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            for link in soup.find_all('a', href=True):
                href = link.get('href', '')
                title = link.get_text(strip=True)
                
                if '/PressRoom/SpeechesTestimony/' in href and title and len(title) > 20:
                    full_url = f"https://www.cftc.gov{href}" if href.startswith('/') else href
                    
                    if seen_urls and not is_new_url(full_url, seen_urls):
                        continue
                    
                    if is_strictly_relevant(title) or is_broadly_relevant(title):
                        items.append(create_item(
                            title=title,
                            source="CFTC Speech/Testimony",
                            url=full_url,
                            date=datetime.now().strftime("%Y-%m-%d"),
                            base_category="federal",
                            tier=1,
                        ))
    except Exception as e:
        print(f"      Error: {e}")
    
    print(f"      Found: {len(items)} new")
    return items


def scrape_cftc_orders(seen_urls: Set[str] = None) -> List[Dict]:
    """Scrape CFTC orders RSS feed"""
    print("    CFTC Orders...")
    items = []
    
    try:
        feed = feedparser.parse("https://www.cftc.gov/rss/cftcorders.xml")
        for entry in feed.entries[:20]:
            title = entry.get("title", "")
            entry_url = entry.get("link", "")
            
            if seen_urls and not is_new_url(entry_url, seen_urls):
                continue
            
            if is_strictly_relevant(title) or is_broadly_relevant(title):
                items.append(create_item(
                    title=title,
                    source="CFTC Order",
                    url=entry_url,
                    date=parse_date(entry),
                    base_category="federal",
                    tier=1,
                ))
    except Exception as e:
        print(f"      Error: {e}")
    
    print(f"      Found: {len(items)} new")
    return items


def scrape_cftc_staff_letters(seen_urls: Set[str] = None) -> List[Dict]:
    """Scrape CFTC no-action letters and staff letters"""
    print("    CFTC Staff Letters/No-Action...")
    items = []
    
    try:
        # No-action letters page
        response = fetch_with_retry("https://www.cftc.gov/LawRegulation/CFTCStaffLetters/index.htm")
        if response:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            for link in soup.find_all('a', href=True):
                title = link.get_text(strip=True)
                href = link.get('href', '')
                
                if title and len(title) > 15 and ('/csl/' in href.lower() or 'letter' in href.lower()):
                    full_url = f"https://www.cftc.gov{href}" if href.startswith('/') else href
                    
                    if seen_urls and not is_new_url(full_url, seen_urls):
                        continue
                    
                    if is_strictly_relevant(title) or is_broadly_relevant(title):
                        items.append(create_item(
                            title=title,
                            source="CFTC Staff Letter",
                            url=full_url,
                            date=datetime.now().strftime("%Y-%m-%d"),
                            base_category="federal",
                            tier=1,
                        ))
    except Exception as e:
        print(f"      Error: {e}")
    
    print(f"      Found: {len(items)} new")
    return items


def fetch_sec_rss(seen_urls: Set[str] = None) -> List[Dict]:
    """Fetch SEC RSS feeds"""
    print("    SEC RSS...")
    items = []
    
    feeds = [
        ("https://www.sec.gov/news/pressreleases.rss", "SEC Press Release"),
        ("https://www.sec.gov/news/statements.rss", "SEC Statement"),
        ("https://www.sec.gov/rss/litigation/litreleases.xml", "SEC Litigation"),
    ]
    
    for feed_url, source_name in feeds:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:20]:
                title = entry.get("title", "")
                entry_url = entry.get("link", "")
                
                if seen_urls and not is_new_url(entry_url, seen_urls):
                    continue
                
                if is_strictly_relevant(title):
                    items.append(create_item(
                        title=title,
                        source=source_name,
                        url=entry_url,
                        date=parse_date(entry),
                        base_category="federal",
                        tier=1,
                    ))
        except Exception as e:
            print(f"      Error {source_name}: {e}")
    
    print(f"      Found: {len(items)} new")
    return items


def fetch_nfa(seen_urls: Set[str] = None) -> List[Dict]:
    """Fetch NFA news"""
    print("    NFA...")
    items = []
    
    try:
        feed = feedparser.parse("https://www.nfa.futures.org/news/newsRss.asp")
        for entry in feed.entries[:15]:
            title = entry.get("title", "")
            entry_url = entry.get("link", "")
            
            if seen_urls and not is_new_url(entry_url, seen_urls):
                continue
            
            if is_strictly_relevant(title) or is_broadly_relevant(title):
                items.append(create_item(
                    title=title,
                    source="NFA",
                    url=entry_url,
                    date=parse_date(entry),
                    base_category="federal",
                    tier=1,
                ))
    except Exception as e:
        print(f"      Error: {e}")
    
    print(f"      Found: {len(items)} new")
    return items


# =============================================================================
# TIER 1: STATE GAMING COMMISSIONS
# =============================================================================

def scrape_nv_gaming(seen_urls: Set[str] = None) -> List[Dict]:
    """Scrape Nevada Gaming Control Board"""
    print("    NV Gaming Control Board...")
    items = []
    
    try:
        response = fetch_with_retry("https://gaming.nv.gov/index.aspx?page=149")
        if response:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            for link in soup.find_all('a', href=True):
                title = link.get_text(strip=True)
                href = link.get('href', '')
                
                if title and len(title) > 15:
                    if is_strictly_relevant(title) or any(kw in title.lower() for kw in ['cease', 'desist', 'complaint', 'order', 'ruling']):
                        full_url = href if href.startswith('http') else f"https://gaming.nv.gov{href}"
                        
                        if seen_urls and not is_new_url(full_url, seen_urls):
                            continue
                        
                        items.append(create_item(
                            title=title,
                            source="NV Gaming Control Board",
                            url=full_url,
                            date=datetime.now().strftime("%Y-%m-%d"),
                            base_category="state",
                            tier=1,
                            state="NV",
                        ))
    except Exception as e:
        print(f"      Error: {e}")
    
    print(f"      Found: {len(items)} new")
    return items


def scrape_ma_gaming(seen_urls: Set[str] = None) -> List[Dict]:
    """Scrape Massachusetts Gaming Commission"""
    print("    MA Gaming Commission...")
    items = []
    
    try:
        response = fetch_with_retry("https://massgaming.com/news-events/")
        if response:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            for link in soup.find_all('a', href=True):
                title = link.get_text(strip=True)
                href = link.get('href', '')
                
                if title and len(title) > 15 and not is_junk_title(title):
                    if is_strictly_relevant(title):
                        full_url = href if href.startswith('http') else f"https://massgaming.com{href}"
                        
                        if seen_urls and not is_new_url(full_url, seen_urls):
                            continue
                        
                        items.append(create_item(
                            title=title,
                            source="MA Gaming Commission",
                            url=full_url,
                            date=datetime.now().strftime("%Y-%m-%d"),
                            base_category="state",
                            tier=1,
                            state="MA",
                        ))
    except Exception as e:
        print(f"      Error: {e}")
    
    print(f"      Found: {len(items)} new")
    return items


def scrape_state_gaming_commissions(seen_urls: Set[str] = None) -> List[Dict]:
    """Scrape other state gaming commissions"""
    print("    Other State Gaming Commissions...")
    items = []
    
    sources = [
        ("https://gamingcontrolboard.pa.gov/news-and-transparency/press-release", "PA Gaming Control Board", "PA"),
        ("https://www.njoag.gov/about/divisions-and-offices/division-of-gaming-enforcement-home/news-and-updates/", "NJ Division of Gaming", "NJ"),
        ("https://www.michigan.gov/mgcb/news", "MI Gaming Control Board", "MI"),
        ("https://igb.illinois.gov/news/press-releases.html", "IL Gaming Board", "IL"),
    ]
    
    for url, source_name, state in sources:
        try:
            response = fetch_with_retry(url)
            if response:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                for link in soup.find_all('a', href=True):
                    title = link.get_text(strip=True)
                    href = link.get('href', '')
                    
                    if title and len(title) > 15 and not is_junk_title(title):
                        if is_strictly_relevant(title):
                            full_url = href if href.startswith('http') else url.rsplit('/', 1)[0] + '/' + href
                            
                            if seen_urls and not is_new_url(full_url, seen_urls):
                                continue
                            
                            items.append(create_item(
                                title=title,
                                source=source_name,
                                url=full_url,
                                date=datetime.now().strftime("%Y-%m-%d"),
                                base_category="state",
                                tier=1,
                                state=state,
                            ))
        except Exception as e:
            print(f"      Error {source_name}: {e}")
    
    print(f"      Found: {len(items)} new")
    return items


# =============================================================================
# TIER 1: STATE ATTORNEYS GENERAL
# =============================================================================

def scrape_state_ags(seen_urls: Set[str] = None) -> List[Dict]:
    """Scrape State Attorneys General"""
    print("    State Attorneys General...")
    items = []
    
    sources = [
        ("https://ag.nv.gov/News/Press_Releases/", "NV Attorney General", "NV"),
        ("https://ag.ny.gov/press-releases", "NY Attorney General", "NY"),
        ("https://www.texasattorneygeneral.gov/news", "TX Attorney General", "TX"),
        ("https://oag.ca.gov/news", "CA Attorney General", "CA"),
        ("https://www.mass.gov/orgs/office-of-attorney-general-andrea-joy-campbell", "MA Attorney General", "MA"),
        ("https://www.ohioattorneygeneral.gov/Media/News-Releases", "OH Attorney General", "OH"),
    ]
    
    for url, source_name, state in sources:
        try:
            response = fetch_with_retry(url)
            if response:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                for link in soup.find_all('a', href=True):
                    title = link.get_text(strip=True)
                    href = link.get('href', '')
                    
                    if title and len(title) > 15 and not is_junk_title(title):
                        if is_strictly_relevant(title):
                            full_url = href if href.startswith('http') else url.rsplit('/', 1)[0] + href
                            
                            if seen_urls and not is_new_url(full_url, seen_urls):
                                continue
                            
                            items.append(create_item(
                                title=title,
                                source=source_name,
                                url=full_url,
                                date=datetime.now().strftime("%Y-%m-%d"),
                                base_category="state",
                                tier=1,
                                state=state,
                            ))
        except Exception as e:
            print(f"      Error {source_name}: {e}")
    
    print(f"      Found: {len(items)} new")
    return items


# =============================================================================
# TIER 2: TRADE ORGANIZATIONS & PREDICTION MARKET COMPANIES
# =============================================================================

def scrape_trade_orgs(seen_urls: Set[str] = None) -> List[Dict]:
    """Scrape AGA and other trade organizations"""
    print("    Trade Organizations...")
    items = []
    
    # AGA RSS
    try:
        feed = feedparser.parse("https://www.americangaming.org/feed/")
        for entry in feed.entries[:20]:
            title = entry.get("title", "")
            entry_url = entry.get("link", "")
            
            if seen_urls and not is_new_url(entry_url, seen_urls):
                continue
            
            if not is_junk_title(title) and is_strictly_relevant(title):
                items.append(create_item(
                    title=title,
                    source="American Gaming Association",
                    url=entry_url,
                    date=parse_date(entry),
                    base_category="trade",
                    tier=2,
                ))
    except Exception as e:
        print(f"      AGA RSS error: {e}")
    
    print(f"      Found: {len(items)} new")
    return items


def scrape_prediction_market_companies(seen_urls: Set[str] = None) -> List[Dict]:
    """Scrape Kalshi, Polymarket, Nadex company blogs"""
    print("    Prediction Market Companies...")
    items = []
    
    # Kalshi
    try:
        response = fetch_with_retry("https://kalshi.com/blog")
        if response:
            soup = BeautifulSoup(response.text, 'html.parser')
            for link in soup.find_all('a', href=True):
                title = link.get_text(strip=True)
                href = link.get('href', '')
                
                if title and len(title) > 20 and not is_junk_title(title):
                    if '/blog/' in href or is_strictly_relevant(title) or any(kw in title.lower() for kw in ['cftc', 'regulation', 'legal', 'court', 'announcement', 'launch']):
                        full_url = href if href.startswith('http') else f"https://kalshi.com{href}"
                        
                        if seen_urls and not is_new_url(full_url, seen_urls):
                            continue
                        
                        items.append(create_item(
                            title=title,
                            source="Kalshi",
                            url=full_url,
                            date=datetime.now().strftime("%Y-%m-%d"),
                            base_category="participants",
                            tier=2,
                        ))
    except Exception as e:
        print(f"      Kalshi error: {e}")
    
    # Polymarket
    try:
        response = fetch_with_retry("https://polymarket.com/blog")
        if response:
            soup = BeautifulSoup(response.text, 'html.parser')
            for link in soup.find_all('a', href=True):
                title = link.get_text(strip=True)
                href = link.get('href', '')
                
                if title and len(title) > 20 and not is_junk_title(title):
                    if '/blog/' in href or is_strictly_relevant(title):
                        full_url = href if href.startswith('http') else f"https://polymarket.com{href}"
                        
                        if seen_urls and not is_new_url(full_url, seen_urls):
                            continue
                        
                        items.append(create_item(
                            title=title,
                            source="Polymarket",
                            url=full_url,
                            date=datetime.now().strftime("%Y-%m-%d"),
                            base_category="participants",
                            tier=2,
                        ))
    except Exception as e:
        print(f"      Polymarket error: {e}")
    
    print(f"      Found: {len(deduplicate(items))} new")
    return deduplicate(items)


# =============================================================================
# TIER 3: GOOGLE NEWS - Quality sources only
# =============================================================================

def fetch_google_news(seen_urls: Set[str] = None) -> List[Dict]:
    """Fetch Google News - STRICT source filtering"""
    print("    Google News (Quality Sources Only)...")
    items = []
    
    searches = [
        "Kalshi CFTC",
        "Kalshi regulation court",
        "Polymarket CFTC regulation",
        "Polymarket lawsuit court",
        "prediction market CFTC regulation",
        "prediction market court ruling",
        "event contract CFTC",
        "CFTC event contract rule",
        "Coinbase prediction market",
        "Robinhood prediction market",
        "state attorney general prediction market",
        "gaming commission prediction market",
    ]
    
    for query in searches:
        try:
            encoded = requests.utils.quote(query)
            feed_url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
            
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:5]:  # Limit per search
                title = entry.get("title", "")
                link = entry.get("link", "")
                source = extract_source(title)
                
                # Skip excluded sources
                if is_excluded_source(link, title, source):
                    continue
                
                if seen_urls and not is_new_url(link, seen_urls):
                    continue
                
                # Determine tier based on URL
                if is_gov_url(link):
                    tier = 1
                    base_category = "federal"
                    needs_primary = False
                elif is_approved_news(source):
                    tier = 3
                    base_category = "news"
                    needs_primary = True
                else:
                    # Skip non-approved sources
                    continue
                
                items.append(create_item(
                    title=clean_title(title),
                    source=source,
                    url=link,
                    date=parse_date(entry),
                    base_category=base_category,
                    tier=tier,
                    needs_primary=needs_primary,
                ))
                
            time.sleep(0.3)
        except Exception as e:
            print(f"      Error: {e}")
    
    print(f"      Found: {len(deduplicate(items))} new")
    return deduplicate(items)


# =============================================================================
# MAIN
# =============================================================================

def main():
    print(f"\n{'='*70}")
    print(f"EDM Monitor v10 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Event-Driven Markets / Prediction Markets / Event Contracts")
    print(f"STRICT FILTERING MODE")
    print(f"{'='*70}\n")
    
    # Load seen URLs
    print("[SETUP] Loading seen URLs...")
    seen_urls = load_seen_urls()
    
    all_items = []
    
    # TIER 1: Federal Government
    print("\n[TIER 1] Federal Government (.gov)")
    print("-" * 40)
    all_items.extend(fetch_federal_register(days_back=30, seen_urls=seen_urls))
    all_items.extend(scrape_cftc_press_releases(seen_urls=seen_urls))
    all_items.extend(scrape_cftc_speeches(seen_urls=seen_urls))
    all_items.extend(scrape_cftc_orders(seen_urls=seen_urls))
    all_items.extend(scrape_cftc_staff_letters(seen_urls=seen_urls))
    all_items.extend(fetch_sec_rss(seen_urls=seen_urls))
    all_items.extend(fetch_nfa(seen_urls=seen_urls))
    
    # TIER 1: State Gaming Commissions
    print("\n[TIER 1] State Gaming Commissions")
    print("-" * 40)
    all_items.extend(scrape_nv_gaming(seen_urls=seen_urls))
    all_items.extend(scrape_ma_gaming(seen_urls=seen_urls))
    all_items.extend(scrape_state_gaming_commissions(seen_urls=seen_urls))
    
    # TIER 1: State AGs
    print("\n[TIER 1] State Attorneys General")
    print("-" * 40)
    all_items.extend(scrape_state_ags(seen_urls=seen_urls))
    
    # TIER 2: Trade Organizations
    print("\n[TIER 2] Trade Organizations & Companies")
    print("-" * 40)
    all_items.extend(scrape_trade_orgs(seen_urls=seen_urls))
    all_items.extend(scrape_prediction_market_companies(seen_urls=seen_urls))
    
    # TIER 3: Quality News
    print("\n[TIER 3] Quality News Sources")
    print("-" * 40)
    all_items.extend(fetch_google_news(seen_urls=seen_urls))
    
    # Deduplicate
    all_items = deduplicate(all_items)
    
    # Sort by date, tier, priority
    priority_order = {"high": 0, "medium": 1, "low": 2}
    all_items.sort(key=lambda x: (
        x["date"] or "1900-01-01",
        x["tier"],
        priority_order.get(x["priority"], 2)
    ), reverse=True)
    
    # Add IDs
    for item in all_items:
        item["id"] = generate_id(item)
    
    # Category breakdown
    category_counts = {}
    for item in all_items:
        cat = item["category"]
        category_counts[cat] = category_counts.get(cat, 0) + 1
    
    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"NEW items to review: {len(all_items)}")
    print(f"\nBy Tier:")
    print(f"  Tier 1 (Government):      {len([i for i in all_items if i['tier'] == 1])}")
    print(f"  Tier 2 (Trade/Companies): {len([i for i in all_items if i['tier'] == 2])}")
    print(f"  Tier 3 (News):            {len([i for i in all_items if i['tier'] == 3])}")
    print(f"\nBy Category (for dashboard heatmap):")
    for cat, count in sorted(category_counts.items()):
        print(f"  {cat:15} {count}")
    print(f"\nPriority:")
    print(f"  High Priority:            {len([i for i in all_items if i['priority'] == 'high'])}")
    print(f"  Need Primary Source:      {len([i for i in all_items if i.get('needs_primary_source')])}")
    
    # Save CSV
    with open(OUTPUT_DRAFT_CSV, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["id", "date", "tier", "priority", "category", "title", "source", "state", "url", "needs_primary_source"]
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_items)
    
    # Save JSON
    with open(OUTPUT_DRAFT_JSON, "w", encoding="utf-8") as f:
        json.dump({
            "last_updated": datetime.now().isoformat(),
            "total_items": len(all_items),
            "items": all_items
        }, f, indent=2)
    
    print(f"\nSaved to {OUTPUT_DRAFT_CSV} and {OUTPUT_DRAFT_JSON}")
    
    # Show preview
    if all_items:
        print(f"\n{'='*70}")
        print("NEW ITEMS TO REVIEW (Top 20):")
        print(f"{'='*70}")
        for item in all_items[:20]:
            flag = "📰 FIND PRIMARY" if item.get("needs_primary_source") else "✅ PRIMARY"
            cat_display = f"[{item['category'][:6]:6}]"
            print(f"[T{item['tier']}] {cat_display} [{item['priority'].upper():6}] {flag}")
            print(f"      {item['source'][:25]:25} | {item['title'][:50]}...")
            print()
        
        if len(all_items) > 20:
            print(f"... and {len(all_items) - 20} more items")
    else:
        print("\n✅ No new items to review!")
    
    return all_items


if __name__ == "__main__":
    main()
