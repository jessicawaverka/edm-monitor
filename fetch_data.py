#!/usr/bin/env python3
"""
EDM Monitor - Automated Data Fetcher
Fetches regulatory developments from primary sources and saves to draft CSV for review.

Sources:
- Federal Register API (rules, proposed rules, notices)
- CFTC RSS (press releases)
- SEC RSS (press releases, statements)
- Google News RSS (filtered searches)

Output: data_draft.csv (for review before publishing)
"""

import feedparser
import requests
import csv
import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import re
import hashlib

# =============================================================================
# CONFIGURATION
# =============================================================================

# Keywords to search for
KEYWORDS = [
    "prediction market", "prediction markets",
    "event contract", "event contracts", 
    "Kalshi", "Polymarket", "ForecastEx", "Nadex",
    "binary option", "binary options",
    "election contract", "election contracts",
    "sports betting", "sports wagering",
    "CFTC designated contract market",
]

# High priority keywords (boost priority)
HIGH_PRIORITY_KEYWORDS = [
    "ruling", "ruled", "court order", "injunction",
    "enforcement", "cease and desist", "penalty", "fine",
    "approved", "denied", "granted", "rejected",
    "settlement", "lawsuit", "litigation",
    "appeals court", "circuit court", "supreme court",
]

# Medium priority keywords
MEDIUM_PRIORITY_KEYWORDS = [
    "proposed rule", "comment period", "rulemaking",
    "hearing", "testimony", "investigation",
    "guidance", "advisory", "bulletin",
    "application", "filing", "submission",
]

# Sources to EXCLUDE (law firms, etc.)
EXCLUDED_DOMAINS = [
    "jdsupra.com", "lexology.com", "mondaq.com",
    "nationallawreview.com", "law.com", "lawfare",
    "nortonrosefulbright", "skadden", "kirkland",
    "sidley", "winston", "latham", "davis polk",
    "sullivan cromwell", "wachtell", "cleary",
    "cravath", "simpson thacher", "paul weiss",
]

# Tier assignments by source
TIER_1_SOURCES = [
    "federalregister.gov", "cftc.gov", "sec.gov",
    "courtlistener.com", "pacer.uscourts.gov",
    "mass.gov", "gaming.nv.gov", "ny.gov", "texas.gov",
    "ca.gov", "nj.gov", "pa.gov", "michigan.gov",
]

TIER_2_SOURCES = [
    "americangaming.org", "nigc.gov", "ncaa.org",
    "prnewswire.com", "businesswire.com", "globenewswire.com",
]

# =============================================================================
# FETCHER FUNCTIONS
# =============================================================================

def fetch_federal_register(days_back: int = 7) -> List[Dict]:
    """Fetch from Federal Register API"""
    items = []
    
    # Calculate date range
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back)
    
    # Build search terms
    search_terms = [
        "prediction market", "event contract", "Kalshi", 
        "Polymarket", "binary option", "designated contract market"
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
                data = response.json()
                for doc in data.get("results", []):
                    items.append({
                        "title": doc.get("title", ""),
                        "source": "Federal Register",
                        "url": doc.get("html_url", ""),
                        "date": doc.get("publication_date", ""),
                        "category": "federal",
                        "tier": 1,
                        "priority": determine_priority(doc.get("title", "")),
                        "state": None,
                        "pdf_url": doc.get("pdf_url", ""),
                    })
        except Exception as e:
            print(f"Error fetching Federal Register for '{term}': {e}")
    
    return deduplicate(items)


def fetch_cftc_rss() -> List[Dict]:
    """Fetch from CFTC RSS feeds"""
    items = []
    
    feeds = [
        ("https://www.cftc.gov/rss/pressreleases.xml", "CFTC Press Release"),
        ("https://www.cftc.gov/rss/speechesandtestimony.xml", "CFTC Speech"),
    ]
    
    for feed_url, source_name in feeds:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:20]:
                title = entry.get("title", "")
                if is_relevant(title):
                    items.append({
                        "title": title,
                        "source": source_name,
                        "url": entry.get("link", ""),
                        "date": parse_date(entry),
                        "category": "federal",
                        "tier": 1,
                        "priority": determine_priority(title),
                        "state": None,
                    })
        except Exception as e:
            print(f"Error fetching CFTC RSS: {e}")
    
    return items


def fetch_sec_rss() -> List[Dict]:
    """Fetch from SEC RSS feeds"""
    items = []
    
    feeds = [
        ("https://www.sec.gov/news/pressreleases.rss", "SEC Press Release"),
        ("https://www.sec.gov/news/statements.rss", "SEC Statement"),
    ]
    
    for feed_url, source_name in feeds:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:20]:
                title = entry.get("title", "")
                if is_relevant(title):
                    items.append({
                        "title": title,
                        "source": source_name,
                        "url": entry.get("link", ""),
                        "date": parse_date(entry),
                        "category": "federal",
                        "tier": 1,
                        "priority": determine_priority(title),
                        "state": None,
                    })
        except Exception as e:
            print(f"Error fetching SEC RSS: {e}")
    
    return items


def fetch_google_news() -> List[Dict]:
    """Fetch from Google News RSS for specific searches"""
    items = []
    
    searches = [
        ("Kalshi CFTC", "federal"),
        ("Polymarket regulation", "federal"),
        ("prediction market lawsuit", "courts"),
        ("event contract regulation", "federal"),
        ("sports betting state attorney general", "enforcement"),
        ("prediction market state gaming", "state"),
        ('"designated contract market"', "federal"),
    ]
    
    for query, category in searches:
        try:
            # Google News RSS URL
            encoded_query = requests.utils.quote(query)
            feed_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
            
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:10]:
                title = entry.get("title", "")
                link = entry.get("link", "")
                
                # Skip excluded domains
                if is_excluded(link):
                    continue
                
                # Determine tier based on source
                tier = determine_tier(link)
                
                items.append({
                    "title": clean_google_title(title),
                    "source": extract_source(title),
                    "url": link,
                    "date": parse_date(entry),
                    "category": category,
                    "tier": tier,
                    "priority": determine_priority(title),
                    "state": extract_state(title),
                })
        except Exception as e:
            print(f"Error fetching Google News for '{query}': {e}")
    
    return deduplicate(items)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def is_relevant(text: str) -> bool:
    """Check if text contains relevant keywords"""
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in KEYWORDS)


def is_excluded(url: str) -> bool:
    """Check if URL should be excluded"""
    url_lower = url.lower()
    return any(domain in url_lower for domain in EXCLUDED_DOMAINS)


def determine_priority(text: str) -> str:
    """Determine priority based on keywords"""
    text_lower = text.lower()
    
    if any(kw.lower() in text_lower for kw in HIGH_PRIORITY_KEYWORDS):
        return "high"
    elif any(kw.lower() in text_lower for kw in MEDIUM_PRIORITY_KEYWORDS):
        return "medium"
    return "low"


def determine_tier(url: str) -> int:
    """Determine source tier based on URL"""
    url_lower = url.lower()
    
    if any(domain in url_lower for domain in TIER_1_SOURCES):
        return 1
    elif any(domain in url_lower for domain in TIER_2_SOURCES):
        return 2
    return 3


def extract_state(text: str) -> Optional[str]:
    """Extract state abbreviation from text"""
    state_patterns = {
        "nevada": "NV", "massachusetts": "MA", "new york": "NY",
        "new jersey": "NJ", "california": "CA", "texas": "TX",
        "pennsylvania": "PA", "michigan": "MI", "connecticut": "CT",
        "florida": "FL", "illinois": "IL", "ohio": "OH",
    }
    
    text_lower = text.lower()
    for state_name, abbrev in state_patterns.items():
        if state_name in text_lower:
            return abbrev
    return None


def parse_date(entry) -> str:
    """Parse date from feed entry"""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime(*entry.published_parsed[:3]).strftime("%Y-%m-%d")
    elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
        return datetime(*entry.updated_parsed[:3]).strftime("%Y-%m-%d")
    return datetime.now().strftime("%Y-%m-%d")


def clean_google_title(title: str) -> str:
    """Remove source suffix from Google News title"""
    # Google News format: "Article Title - Source Name"
    if " - " in title:
        return title.rsplit(" - ", 1)[0].strip()
    return title


def extract_source(title: str) -> str:
    """Extract source name from Google News title"""
    if " - " in title:
        return title.rsplit(" - ", 1)[1].strip()
    return "News"


def deduplicate(items: List[Dict]) -> List[Dict]:
    """Remove duplicate items based on title similarity"""
    seen = set()
    unique = []
    
    for item in items:
        # Create a simplified key from title
        key = re.sub(r'[^a-z0-9]', '', item["title"].lower())[:50]
        if key not in seen:
            seen.add(key)
            unique.append(item)
    
    return unique


def generate_id(item: Dict) -> str:
    """Generate unique ID for an item"""
    content = f"{item['title']}{item['url']}"
    return hashlib.md5(content.encode()).hexdigest()[:8]


# =============================================================================
# MAIN
# =============================================================================

def main():
    print(f"EDM Monitor - Fetching data at {datetime.now()}")
    print("=" * 60)
    
    all_items = []
    
    # Fetch from all sources
    print("Fetching Federal Register...")
    all_items.extend(fetch_federal_register(days_back=14))
    
    print("Fetching CFTC RSS...")
    all_items.extend(fetch_cftc_rss())
    
    print("Fetching SEC RSS...")
    all_items.extend(fetch_sec_rss())
    
    print("Fetching Google News...")
    all_items.extend(fetch_google_news())
    
    # Deduplicate across all sources
    all_items = deduplicate(all_items)
    
    # Sort by date (newest first), then by tier, then by priority
    priority_order = {"high": 0, "medium": 1, "low": 2}
    all_items.sort(key=lambda x: (
        x["date"] if x["date"] else "1900-01-01",
        x["tier"],
        priority_order.get(x["priority"], 2)
    ), reverse=True)
    
    # Add IDs
    for item in all_items:
        item["id"] = generate_id(item)
    
    print(f"\nTotal items found: {len(all_items)}")
    print(f"  Tier 1 (Primary): {len([i for i in all_items if i['tier'] == 1])}")
    print(f"  Tier 2 (Industry): {len([i for i in all_items if i['tier'] == 2])}")
    print(f"  Tier 3 (News): {len([i for i in all_items if i['tier'] == 3])}")
    print(f"  High Priority: {len([i for i in all_items if i['priority'] == 'high'])}")
    
    # Save to CSV
    output_path = "data_draft.csv"
    
    fieldnames = ["id", "date", "tier", "priority", "category", "title", "source", "state", "url"]
    
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_items)
    
    print(f"\nSaved to {output_path}")
    
    # Also save as JSON for the dashboard
    json_path = "data_draft.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "last_updated": datetime.now().isoformat(),
            "total_items": len(all_items),
            "items": all_items
        }, f, indent=2)
    
    print(f"Saved to {json_path}")
    
    # Generate summary for email
    summary = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total": len(all_items),
        "high_priority": len([i for i in all_items if i["priority"] == "high"]),
        "tier_1": len([i for i in all_items if i["tier"] == 1]),
        "new_items": all_items[:10],  # Top 10 newest
    }
    
    with open("fetch_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    
    print("\nTop 5 items:")
    for item in all_items[:5]:
        print(f"  [{item['tier']}] [{item['priority'].upper()}] {item['title'][:60]}...")
    
    return all_items


if __name__ == "__main__":
    main()
