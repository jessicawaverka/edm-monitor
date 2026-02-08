#!/usr/bin/env python3
"""
EDM Monitor - Automated Data Fetcher v9
Event-Driven Markets / Prediction Markets / Event Contracts

CHANGES IN V9:
- Fixed categories to match dashboard: federal, state, enforcement, courts, trade, participants, news
- Smart category detection based on keywords
- Proper tagging for heatmap display

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

# Keywords for relevance filtering
PREDICTION_MARKET_KEYWORDS = [
    "prediction market", "prediction markets",
    "event contract", "event contracts", 
    "kalshi", "polymarket", "forecastex", "nadex", "predictit",
    "designated contract market", "dcm registration",
    "binary option", "binary options",
    "election contract", "election contracts",
    "sports betting", "sports wagering", "sports event contract",
    "event-based contract",
    "forecast contract",
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
]

# Category detection keywords
ENFORCEMENT_KEYWORDS = [
    "enforcement", "cease and desist", "cease-and-desist", "penalty", "fine", 
    "settlement", "violation", "enforcement action", "civil penalty",
    "consent order", "disciplinary", "sanction",
]

COURTS_KEYWORDS = [
    "court", "judge", "ruling", "ruled", "lawsuit", "litigation", "injunction",
    "restraining order", "appeal", "appeals court", "circuit court", "district court",
    "supreme court", "plaintiff", "defendant", "complaint filed", "motion",
    "preliminary injunction", "temporary restraining", "tro",
]

# Excluded domains
EXCLUDED_DOMAINS = [
    "jdsupra.com", "lexology.com", "mondaq.com", "nationallawreview.com",
    "law.com", "lawfare", "law360", "wsj.com", "ft.com", "barrons.com", 
    "seekingalpha.com", "patch.com", "triblive.com", "wesa.fm", "wpxi.com", 
    "abc27.com", "boston25", "fox", "wgn", "wthr", "khou", "wfaa", "wcvb",
    "myheraldreview", "newsbreak.com", "yahoo.com", "msn.com", "aol.com", 
    "financialcontent.com", "coindesk.com", "cointelegraph.com", "decrypt.co", 
    "theblock.co", "grafa", "bitget.com", "cryptonews", "newsbtc",
    "actionnetwork.com", "sportsbettingdime.com", "legalsportsreport.com",
    "covers.com", "oddschecker.com", "vegasinsider.com",
    "forbes.com", "businessinsider.com", "medium.com", "substack.com",
]

EXCLUDED_SOURCE_NAMES = [
    "Law360", "Bloomberg Law", "WSJ", "Financial Times", "Barron's",
    "JD Supra", "Lexology", "Mondaq", "National Law Review",
    "CoinDesk", "Cointelegraph", "Decrypt", "The Block",
    "Action Network", "Legal Sports Report", "Covers",
    "Yahoo", "MSN", "AOL", "Forbes", "Business Insider",
]

APPROVED_NEWS_SOURCES = [
    "reuters", "associated press", "ap news",
    "bloomberg", "cnbc", "bbc", "npr", "guardian",
    "politico", "the hill", "axios",
]

JUNK_PATTERNS = [
    r'^support@', r'^contact', r'^email', r'^subscribe', r'^newsletter',
    r'^read more', r'^learn more', r'^click here', r'^view all', r'^see all',
    r'^home$', r'^about$', r'^menu$', r'^search$', r'@.*\.org$', r'@.*\.com$',
]

# =============================================================================
# CATEGORY DETECTION
# =============================================================================

def determine_category(title: str, source: str, base_category: str) -> str:
    """
    Determine the proper category for dashboard heatmap.
    Categories: federal, state, enforcement, courts, trade, participants, news
    """
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
    if base_category in ["federal", "state", "participants", "news"]:
        return base_category
    
    return base_category


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
# HELPER FUNCTIONS
# =============================================================================

def is_junk_title(title: str) -> bool:
    title_lower = title.lower().strip()
    if len(title_lower) < 15:
        return True
    for pattern in JUNK_PATTERNS:
        if re.search(pattern, title_lower):
            return True
    return False


def is_excluded(url: str, title: str = "") -> bool:
    url_lower = url.lower()
    for domain in EXCLUDED_DOMAINS:
        if domain in url_lower:
            return True
    if " - " in title:
        source = title.split(" - ")[-1].strip().lower()
        for excluded in EXCLUDED_SOURCE_NAMES:
            if excluded.lower() in source:
                return True
    return False


def is_relevant(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in PREDICTION_MARKET_KEYWORDS)


def is_approved_news(source_name: str) -> bool:
    source_lower = source_name.lower()
    return any(s in source_lower for s in APPROVED_NEWS_SOURCES)


def determine_priority(text: str) -> str:
    text_lower = text.lower()
    if any(kw in text_lower for kw in HIGH_PRIORITY_KEYWORDS):
        return "high"
    return "medium"


def extract_state(text: str) -> Optional[str]:
    states = {
        "nevada": "NV", "massachusetts": "MA", "new york": "NY",
        "new jersey": "NJ", "california": "CA", "texas": "TX",
        "pennsylvania": "PA", "michigan": "MI", "tennessee": "TN",
        "maryland": "MD", "connecticut": "CT", "florida": "FL",
        "illinois": "IL", "arizona": "AZ",
    }
    text_lower = text.lower()
    for state, abbrev in states.items():
        if state in text_lower:
            return abbrev
    return None


def parse_date(entry) -> str:
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime(*entry.published_parsed[:3]).strftime("%Y-%m-%d")
    if hasattr(entry, "updated_parsed") and entry.updated_parsed:
        return datetime(*entry.updated_parsed[:3]).strftime("%Y-%m-%d")
    return datetime.now().strftime("%Y-%m-%d")


def clean_title(title: str) -> str:
    if " - " in title:
        title = title.rsplit(" - ", 1)[0].strip()
    title = re.sub(r'\s+', ' ', title).strip()
    return title


def extract_source(title: str) -> str:
    if " - " in title:
        return title.rsplit(" - ", 1)[1].strip()
    return "News"


def deduplicate(items: List[Dict]) -> List[Dict]:
    seen = set()
    unique = []
    for item in items:
        key = re.sub(r'[^a-z0-9]', '', item["title"].lower())[:50]
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def generate_id(item: Dict) -> str:
    return hashlib.md5(f"{item['title']}{item['url']}".encode()).hexdigest()[:8]


def fetch_with_retry(url: str, retries: int = 2, timeout: int = 30) -> Optional[requests.Response]:
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
    """Create a properly formatted item with correct category"""
    final_category = determine_category(title, source, base_category)
    return {
        "title": title,
        "source": source,
        "url": url,
        "date": date,
        "category": final_category,
        "tier": tier,
        "priority": determine_priority(title),
        "state": state or extract_state(title),
        "needs_primary_source": needs_primary,
    }


# =============================================================================
# TIER 1: FEDERAL GOVERNMENT SOURCES
# =============================================================================

def fetch_federal_register(days_back: int = 30, seen_urls: Set[str] = None) -> List[Dict]:
    print("    Federal Register API...")
    items = []
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back)
    
    search_terms = ['"event contract"', '"prediction market"', "Kalshi", "Polymarket"]
    
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
                    
                    if is_relevant(title):
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
                    
                    if is_relevant(title):
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
                    
                    if is_relevant(title):
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
    print("    CFTC Orders...")
    items = []
    
    try:
        feed = feedparser.parse("https://www.cftc.gov/rss/cftcorders.xml")
        for entry in feed.entries[:20]:
            title = entry.get("title", "")
            entry_url = entry.get("link", "")
            
            if seen_urls and not is_new_url(entry_url, seen_urls):
                continue
            
            if is_relevant(title):
                items.append(create_item(
                    title=title,
                    source="CFTC Order",
                    url=entry_url,
                    date=parse_date(entry),
                    base_category="federal",  # Will become "enforcement" if keywords match
                    tier=1,
                ))
    except Exception as e:
        print(f"      Error: {e}")
    
    print(f"      Found: {len(items)} new")
    return items


def scrape_cftc_dcm(seen_urls: Set[str] = None) -> List[Dict]:
    print("    CFTC DCM Registrations...")
    items = []
    
    try:
        response = fetch_with_retry("https://www.cftc.gov/MarketReports/DCMReports/index.htm")
        if response:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            for link in soup.find_all('a', href=True):
                title = link.get_text(strip=True)
                href = link.get('href', '')
                
                if title and len(title) > 15 and is_relevant(title):
                    full_url = f"https://www.cftc.gov{href}" if href.startswith('/') else href
                    
                    if seen_urls and not is_new_url(full_url, seen_urls):
                        continue
                    
                    items.append(create_item(
                        title=title,
                        source="CFTC DCM",
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
                
                if is_relevant(title):
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
    print("    NFA...")
    items = []
    
    try:
        feed = feedparser.parse("https://www.nfa.futures.org/news/newsRss.asp")
        for entry in feed.entries[:15]:
            title = entry.get("title", "")
            entry_url = entry.get("link", "")
            
            if seen_urls and not is_new_url(entry_url, seen_urls):
                continue
            
            if is_relevant(title):
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
    print("    NV Gaming Control Board...")
    items = []
    
    try:
        response = fetch_with_retry("https://www.gaming.nv.gov/about-us/press-releases-public-statements/")
        if response:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            for link in soup.find_all('a', href=True):
                title = link.get_text(strip=True)
                href = link.get('href', '')
                
                if title and len(title) > 15:
                    if any(kw in title.lower() for kw in ['kalshi', 'polymarket', 'prediction', 'event contract', 'coinbase', 'cease', 'desist', 'complaint', 'restraining']):
                        full_url = href if href.startswith('http') else f"https://www.gaming.nv.gov{href}"
                        
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


def scrape_ny_gaming(seen_urls: Set[str] = None) -> List[Dict]:
    print("    NY Gaming Commission...")
    items = []
    
    try:
        response = fetch_with_retry("https://gaming.ny.gov/newsroom")
        if response:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            for link in soup.find_all('a', href=True):
                title = link.get_text(strip=True)
                href = link.get('href', '')
                
                if title and len(title) > 15 and not is_junk_title(title):
                    if is_relevant(title):
                        full_url = href if href.startswith('http') else f"https://gaming.ny.gov{href}"
                        
                        if seen_urls and not is_new_url(full_url, seen_urls):
                            continue
                        
                        items.append(create_item(
                            title=title,
                            source="NY Gaming Commission",
                            url=full_url,
                            date=datetime.now().strftime("%Y-%m-%d"),
                            base_category="state",
                            tier=1,
                            state="NY",
                        ))
    except Exception as e:
        print(f"      Error: {e}")
    
    print(f"      Found: {len(items)} new")
    return items


def scrape_state_gaming_commissions(seen_urls: Set[str] = None) -> List[Dict]:
    """Scrape PA, NJ, MA, MI, IL gaming commissions"""
    print("    Other State Gaming Commissions...")
    items = []
    
    sources = [
        ("https://gamingcontrolboard.pa.gov/news-and-transparency/press-release", "PA Gaming Control Board", "PA"),
        ("https://www.njoag.gov/about/divisions-and-offices/division-of-gaming-enforcement-home/news-and-updates/", "NJ Division of Gaming", "NJ"),
        ("https://massgaming.com/news-events/", "MA Gaming Commission", "MA"),
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
                        if is_relevant(title):
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
    """Scrape NV, NY, TX, CA Attorneys General"""
    print("    State Attorneys General...")
    items = []
    
    sources = [
        ("https://ag.nv.gov/News/Press_Releases/", "NV Attorney General", "NV"),
        ("https://ag.ny.gov/press-releases", "NY Attorney General", "NY"),
        ("https://www.texasattorneygeneral.gov/news", "TX Attorney General", "TX"),
        ("https://oag.ca.gov/news", "CA Attorney General", "CA"),
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
                        if is_relevant(title):
                            full_url = href if href.startswith('http') else url.rsplit('/', 1)[0] + href
                            
                            if seen_urls and not is_new_url(full_url, seen_urls):
                                continue
                            
                            # AG actions are often enforcement
                            items.append(create_item(
                                title=title,
                                source=source_name,
                                url=full_url,
                                date=datetime.now().strftime("%Y-%m-%d"),
                                base_category="state",  # Will become enforcement if keywords match
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
    """Scrape AGA and Indian Gaming Association"""
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
            
            if not is_junk_title(title):
                items.append(create_item(
                    title=title,
                    source="American Gaming Association",
                    url=entry_url,
                    date=parse_date(entry),
                    base_category="trade",  # FIXED: was "industry"
                    tier=2,
                ))
    except Exception as e:
        print(f"      AGA RSS error: {e}")
    
    # Indian Gaming Association
    try:
        response = fetch_with_retry("https://indiangaming.org/posts/")
        if response:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            for article in soup.find_all(['article', 'div'], class_=re.compile(r'(post|news|article|entry)', re.I)):
                link = article.find('a', href=True)
                if link:
                    title = link.get_text(strip=True)
                    href = link.get('href', '')
                    
                    if is_junk_title(title) or len(title) < 25 or '@' in title:
                        continue
                    
                    if seen_urls and not is_new_url(href, seen_urls):
                        continue
                    
                    if is_relevant(title) or any(kw in title.lower() for kw in ['prediction', 'regulation', 'legislation', 'congress', 'federal', 'cftc', 'illegal']):
                        items.append(create_item(
                            title=title,
                            source="Indian Gaming Association",
                            url=href,
                            date=datetime.now().strftime("%Y-%m-%d"),
                            base_category="trade",  # FIXED: was "industry"
                            tier=2,
                        ))
    except Exception as e:
        print(f"      IGA error: {e}")
    
    print(f"      Found: {len(items)} new")
    return items


def scrape_prediction_market_companies(seen_urls: Set[str] = None) -> List[Dict]:
    """Scrape Kalshi, Polymarket, Nadex, Interactive Brokers"""
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
                    if '/blog/' in href or is_relevant(title) or any(kw in title.lower() for kw in ['cftc', 'regulation', 'legal', 'court', 'announcement', 'launch']):
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
                    if '/blog/' in href or is_relevant(title):
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
    
    # Nadex
    try:
        response = fetch_with_retry("https://www.nadex.com/blog/")
        if response:
            soup = BeautifulSoup(response.text, 'html.parser')
            for link in soup.find_all('a', href=True):
                title = link.get_text(strip=True)
                href = link.get('href', '')
                
                if title and len(title) > 20 and not is_junk_title(title):
                    if '/blog/' in href or is_relevant(title):
                        full_url = href if href.startswith('http') else f"https://www.nadex.com{href}"
                        
                        if seen_urls and not is_new_url(full_url, seen_urls):
                            continue
                        
                        items.append(create_item(
                            title=title,
                            source="Nadex",
                            url=full_url,
                            date=datetime.now().strftime("%Y-%m-%d"),
                            base_category="participants",
                            tier=2,
                        ))
    except Exception as e:
        print(f"      Nadex error: {e}")
    
    # Interactive Brokers - STRICT filter
    try:
        response = fetch_with_retry("https://www.interactivebrokers.com/en/general/about/press-and-media.php")
        if response:
            soup = BeautifulSoup(response.text, 'html.parser')
            for link in soup.find_all('a', href=True):
                title = link.get_text(strip=True)
                href = link.get('href', '')
                
                if title and len(title) > 20 and not is_junk_title(title):
                    # STRICT: only event contract/forecast mentions
                    if any(kw in title.lower() for kw in ['event contract', 'forecast', 'prediction market', 'forecastex', 'kalshi']):
                        full_url = href if href.startswith('http') else f"https://www.interactivebrokers.com{href}"
                        
                        if seen_urls and not is_new_url(full_url, seen_urls):
                            continue
                        
                        items.append(create_item(
                            title=title,
                            source="Interactive Brokers",
                            url=full_url,
                            date=datetime.now().strftime("%Y-%m-%d"),
                            base_category="participants",
                            tier=2,
                        ))
    except Exception as e:
        print(f"      IB error: {e}")
    
    print(f"      Found: {len(deduplicate(items))} new")
    return deduplicate(items)


# =============================================================================
# TIER 3: GOOGLE NEWS
# =============================================================================

def fetch_google_news(seen_urls: Set[str] = None) -> List[Dict]:
    print("    Google News...")
    items = []
    
    searches = [
        "Kalshi CFTC", "Kalshi regulation", "Kalshi lawsuit",
        "Polymarket regulation", "Polymarket CFTC", "Polymarket lawsuit",
        "prediction market regulation", "prediction market court",
        "event contract CFTC", "ForecastEx event contract",
        "CME event contract", "PredictIt CFTC", "Nadex regulation",
        "Cantor Exchange prediction", "Tastytrade prediction market",
        "Robinhood prediction market", "Webull prediction market",
        "Interactive Brokers ForecastEx",
    ]
    
    for query in searches:
        try:
            encoded = requests.utils.quote(query)
            feed_url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
            
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:8]:
                title = entry.get("title", "")
                link = entry.get("link", "")
                source = extract_source(title)
                
                if is_excluded(link, title):
                    continue
                
                if seen_urls and not is_new_url(link, seen_urls):
                    continue
                
                if ".gov" in link.lower():
                    tier = 1
                    base_category = "federal"
                    needs_primary = False
                elif is_approved_news(source):
                    tier = 3
                    base_category = "news"
                    needs_primary = True
                else:
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
    print(f"EDM Monitor v9 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Event-Driven Markets / Prediction Markets / Event Contracts")
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
    all_items.extend(scrape_cftc_dcm(seen_urls=seen_urls))
    all_items.extend(fetch_sec_rss(seen_urls=seen_urls))
    all_items.extend(fetch_nfa(seen_urls=seen_urls))
    
    # TIER 1: State Gaming Commissions
    print("\n[TIER 1] State Gaming Commissions")
    print("-" * 40)
    all_items.extend(scrape_nv_gaming(seen_urls=seen_urls))
    all_items.extend(scrape_ny_gaming(seen_urls=seen_urls))
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
    
    # Sort
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
    
    # Show items
    if all_items:
        print(f"\n{'='*70}")
        print("NEW ITEMS TO REVIEW:")
        print(f"{'='*70}")
        for item in all_items[:20]:
            flag = "📰 FIND PRIMARY" if item.get("needs_primary_source") else "✅ PRIMARY"
            cat_display = f"[{item['category'][:6]:6}]"
            print(f"[T{item['tier']}] {cat_display} [{item['priority'].upper():6}] {flag}")
            print(f"      {item['source'][:25]:25} | {item['title'][:45]}...")
            print()
        
        if len(all_items) > 20:
            print(f"... and {len(all_items) - 20} more items")
    else:
        print("\n✅ No new items to review!")
    
    return all_items


if __name__ == "__main__":
    main()
