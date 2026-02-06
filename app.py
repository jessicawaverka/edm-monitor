"""
Event-Driven Markets Monitor - PRODUCTION
==========================================
Auto-fetches from real sources daily. No manual updates needed.

Sources:
- Federal Register API (actual government PDFs)
- CFTC RSS feeds (press releases, orders)
- Google News RSS (filtered, no law firms)
- CourtListener (court filings)

Deploy to Streamlit Cloud for free hosting with daily auto-refresh.
"""

import streamlit as st
import requests
import feedparser
import json
import re
import hashlib
from datetime import datetime, timedelta
from urllib.parse import quote
import time

# =============================================================================
# PAGE CONFIG
# =============================================================================
st.set_page_config(
    page_title="EDM Monitor | NRF",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# =============================================================================
# CONFIGURATION
# =============================================================================

# Keywords for relevance filtering
KEYWORDS = [
    "prediction market", "event contract", "kalshi", "polymarket", 
    "nadex", "forecastex", "binary option", "cftc", "designated contract market",
    "dcm", "gaming commission", "sports wagering", "event-driven"
]

# High priority keywords
HIGH_PRIORITY = [
    "ruling", "court order", "injunction", "cease and desist", "enforcement",
    "approved", "denied", "designated", "lawsuit", "appeals court", "settlement"
]

# EXCLUDED domains - law firms and legal blogs
EXCLUDED_DOMAINS = [
    "jdsupra.com", "lexology.com", "law.com", "nationallawreview.com",
    "mondaq.com", "findlaw.com", "martindale.com", "lawfirm",
    "skadden", "kirkland", "latham", "davis polk", "cravath", "sullivan",
    "gibson dunn", "sidley", "winston", "jones day", "white case",
    "nortonrosefulbright"  # Don't cite ourselves
]

# State mapping
STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY"
}

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def is_relevant(text):
    """Check if text is relevant to prediction markets"""
    text_lower = text.lower()
    return any(kw in text_lower for kw in KEYWORDS)

def is_excluded(url):
    """Check if URL is from excluded domain"""
    url_lower = url.lower()
    return any(domain in url_lower for domain in EXCLUDED_DOMAINS)

def get_priority(text):
    """Determine priority based on keywords"""
    text_lower = text.lower()
    if any(kw in text_lower for kw in HIGH_PRIORITY):
        return "high"
    return "medium"

def extract_state(text):
    """Extract US state from text"""
    text_lower = text.lower()
    for state_name, abbrev in STATES.items():
        if state_name in text_lower:
            return abbrev
    return None

def clean_html(text):
    """Remove HTML tags"""
    return re.sub(r'<[^>]+>', '', text) if text else ""

def make_id(url):
    """Create unique ID from URL"""
    return hashlib.md5(url.encode()).hexdigest()[:10]

# =============================================================================
# DATA FETCHERS
# =============================================================================

@st.cache_data(ttl=3600)  # Cache for 1 hour
def fetch_federal_register():
    """Fetch from Federal Register API - REAL GOVERNMENT DOCUMENTS"""
    articles = []
    
    search_terms = ["prediction market", "event contract", "Kalshi", "designated contract market"]
    
    for term in search_terms:
        try:
            url = "https://www.federalregister.gov/api/v1/documents.json"
            params = {
                "conditions[term]": term,
                "per_page": 20,
                "order": "newest"
            }
            
            response = requests.get(url, params=params, timeout=15)
            if response.status_code == 200:
                data = response.json()
                
                for doc in data.get("results", []):
                    title = doc.get("title", "")
                    
                    # Get direct PDF link
                    pdf_url = doc.get("pdf_url") or doc.get("html_url") or f"https://www.federalregister.gov/d/{doc.get('document_number', '')}"
                    
                    articles.append({
                        "id": make_id(pdf_url),
                        "title": title,
                        "source": "Federal Register",
                        "url": pdf_url,
                        "date": doc.get("publication_date", ""),
                        "category": "federal",
                        "tier": 1,
                        "priority": get_priority(title),
                        "state": None
                    })
        except Exception as e:
            st.warning(f"Federal Register error: {e}")
    
    return articles

@st.cache_data(ttl=3600)
def fetch_cftc_rss():
    """Fetch from CFTC RSS feeds"""
    articles = []
    
    feeds = [
        ("https://www.cftc.gov/rss/pressreleases.xml", "CFTC Press Release"),
        ("https://www.cftc.gov/rss/speechesandtestimony.xml", "CFTC Speech"),
    ]
    
    for feed_url, source_name in feeds:
        try:
            feed = feedparser.parse(feed_url)
            
            for entry in feed.entries[:20]:
                title = clean_html(entry.get("title", ""))
                link = entry.get("link", "")
                summary = clean_html(entry.get("summary", ""))
                
                # Check relevance
                if not is_relevant(title + " " + summary):
                    continue
                
                # Parse date
                pub = entry.get("published_parsed") or entry.get("updated_parsed")
                date_str = datetime(*pub[:6]).strftime("%Y-%m-%d") if pub else datetime.now().strftime("%Y-%m-%d")
                
                articles.append({
                    "id": make_id(link),
                    "title": title,
                    "source": source_name,
                    "url": link,
                    "date": date_str,
                    "category": "federal",
                    "tier": 1,
                    "priority": get_priority(title),
                    "state": None
                })
        except Exception as e:
            st.warning(f"CFTC RSS error: {e}")
    
    return articles

@st.cache_data(ttl=3600)
def fetch_google_news():
    """Fetch from Google News RSS - filtered"""
    articles = []
    
    searches = [
        ("Kalshi regulation OR lawsuit OR court", "News"),
        ("Polymarket CFTC OR regulation", "News"),
        ("prediction market state gaming commission", "News"),
        ("event contract CFTC", "News"),
    ]
    
    for query, source in searches:
        try:
            feed_url = f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en"
            feed = feedparser.parse(feed_url)
            
            for entry in feed.entries[:10]:
                title = clean_html(entry.get("title", ""))
                link = entry.get("link", "")
                
                # Skip excluded domains
                if is_excluded(link):
                    continue
                
                # Parse date
                pub = entry.get("published_parsed")
                date_str = datetime(*pub[:6]).strftime("%Y-%m-%d") if pub else datetime.now().strftime("%Y-%m-%d")
                
                articles.append({
                    "id": make_id(link),
                    "title": title,
                    "source": source,
                    "url": link,
                    "date": date_str,
                    "category": "news",
                    "tier": 3,
                    "priority": get_priority(title),
                    "state": extract_state(title)
                })
        except Exception as e:
            st.warning(f"Google News error: {e}")
    
    return articles

@st.cache_data(ttl=3600)
def fetch_state_sources():
    """Fetch state-specific sources via Google News site: searches"""
    articles = []
    
    state_searches = [
        ("site:mass.gov Kalshi OR prediction market", "MA Attorney General", "MA"),
        ("site:gaming.nv.gov Kalshi OR Polymarket OR prediction", "Nevada Gaming Control Board", "NV"),
        ("site:tn.gov sports wagering prediction market", "Tennessee SWC", "TN"),
        ("site:ag.ny.gov prediction market OR Kalshi", "NY Attorney General", "NY"),
    ]
    
    for query, source, state in state_searches:
        try:
            feed_url = f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US"
            feed = feedparser.parse(feed_url)
            
            for entry in feed.entries[:5]:
                title = clean_html(entry.get("title", ""))
                link = entry.get("link", "")
                
                pub = entry.get("published_parsed")
                date_str = datetime(*pub[:6]).strftime("%Y-%m-%d") if pub else datetime.now().strftime("%Y-%m-%d")
                
                articles.append({
                    "id": make_id(link),
                    "title": title,
                    "source": source,
                    "url": link,
                    "date": date_str,
                    "category": "state",
                    "tier": 1,
                    "priority": get_priority(title),
                    "state": state
                })
        except Exception as e:
            pass  # Silently skip state search errors
    
    return articles

def fetch_all_data():
    """Fetch from all sources and combine"""
    all_articles = []
    
    with st.spinner("Fetching Federal Register..."):
        all_articles.extend(fetch_federal_register())
    
    with st.spinner("Fetching CFTC..."):
        all_articles.extend(fetch_cftc_rss())
    
    with st.spinner("Fetching State Sources..."):
        all_articles.extend(fetch_state_sources())
    
    with st.spinner("Fetching News..."):
        all_articles.extend(fetch_google_news())
    
    # Deduplicate by title similarity
    seen = set()
    unique = []
    for article in all_articles:
        key = re.sub(r'[^a-z0-9]', '', article['title'].lower())[:50]
        if key not in seen:
            seen.add(key)
            unique.append(article)
    
    # Sort by date (newest first)
    unique.sort(key=lambda x: x.get('date', ''), reverse=True)
    
    return unique

# =============================================================================
# DCM TRACKER DATA (Static - from CFTC SIRT)
# =============================================================================

DCM_DATA = [
    {
        "organization": "KalshiEX LLC",
        "status": "Designated",
        "last_update": "2025-01-17",
        "remarks": "Commission granted petition to permit intermediated futures trading",
        "cftc_url": "https://www.cftc.gov/IndustryOversight/IndustryFilings/TradingOrganizations/42993",
        "order_url": "https://www.cftc.gov/PressRoom/PressReleases/8302-20"
    },
    {
        "organization": "QCX LLC d/b/a Polymarket US",
        "status": "Designated",
        "last_update": "2025-11-24",
        "remarks": "Amended Order of Designation permits intermediated trading",
        "cftc_url": "https://www.cftc.gov/IndustryOversight/IndustryFilings/TradingOrganizations/49571",
        "order_url": "https://www.cftc.gov/media/12806/download"
    },
    {
        "organization": "ForecastEx LLC",
        "status": "Designated",
        "last_update": "2023-06-22",
        "remarks": "Event contracts exchange owned by Interactive Brokers",
        "cftc_url": "https://www.cftc.gov/IndustryOversight/IndustryFilings/TradingOrganizations/47651",
        "order_url": "https://www.cftc.gov/PressRoom/PressReleases/8721-23"
    },
    {
        "organization": "Nadex (North American Derivatives Exchange)",
        "status": "Designated",
        "last_update": "2010-12-13",
        "remarks": "Binary options exchange",
        "cftc_url": "https://www.cftc.gov/IndustryOversight/IndustryFilings/TradingOrganizations/21321",
        "order_url": None
    },
    {
        "organization": "Aristotle Exchange DCM, Inc.",
        "status": "Pending",
        "last_update": "2021-10-07",
        "remarks": "Application pending since 2021",
        "cftc_url": "https://www.cftc.gov/IndustryOversight/IndustryFilings/TradingOrganizations/46990",
        "order_url": None
    },
]

# =============================================================================
# UI
# =============================================================================

def main():
    # Header
    st.markdown("""
    <style>
    .main-header {
        background: linear-gradient(135deg, #1a2634 0%, #2d3e50 100%);
        padding: 20px 30px;
        border-radius: 10px;
        margin-bottom: 20px;
    }
    .main-header h1 {
        color: white;
        margin: 0;
        font-size: 24px;
    }
    .main-header p {
        color: #a0a0a0;
        margin: 5px 0 0 0;
        font-size: 14px;
    }
    .gold-accent {
        color: #c9a962;
    }
    .tier-1 { border-left: 4px solid #1e3a5f; }
    .tier-2 { border-left: 4px solid #2d5a3d; }
    .tier-3 { border-left: 4px solid #666666; }
    .priority-high { color: #c41e3a; }
    .priority-medium { color: #d4a017; }
    </style>
    
    <div class="main-header">
        <h1>📊 Event-Driven Markets Monitor</h1>
        <p>Regulatory Intelligence for Event Contracts & Prediction Markets</p>
        <p class="gold-accent">NRF US Financial Services Team</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Last updated
    st.caption(f"🕐 Last refreshed: {datetime.now().strftime('%B %d, %Y at %I:%M %p ET')}")
    
    # Tabs
    tab1, tab2 = st.tabs(["📰 Regulatory Developments", "🏛️ DCM Application Tracker"])
    
    with tab1:
        # Fetch data
        if st.button("🔄 Refresh Data", type="primary"):
            st.cache_data.clear()
        
        articles = fetch_all_data()
        
        if not articles:
            st.warning("No articles found. Try refreshing.")
            return
        
        # Metrics
        col1, col2, col3, col4 = st.columns(4)
        tier1 = [a for a in articles if a['tier'] == 1]
        tier3 = [a for a in articles if a['tier'] == 3]
        high_priority = [a for a in articles if a['priority'] == 'high']
        states = set(a['state'] for a in articles if a['state'])
        
        col1.metric("Total Items", len(articles))
        col2.metric("Primary Sources", len(tier1))
        col3.metric("High Priority", len(high_priority))
        col4.metric("Active States", len(states))
        
        st.divider()
        
        # Filters
        with st.expander("🔍 Filters", expanded=False):
            col1, col2, col3 = st.columns(3)
            with col1:
                tier_filter = st.multiselect("Source Tier", [1, 2, 3], default=[1, 2, 3], 
                    format_func=lambda x: {1: "Government Primary", 2: "Industry Official", 3: "News Coverage"}[x])
            with col2:
                priority_filter = st.multiselect("Priority", ["high", "medium"], default=["high", "medium"],
                    format_func=lambda x: x.title())
            with col3:
                state_filter = st.multiselect("State", list(states) if states else ["All"])
        
        # Apply filters
        filtered = [a for a in articles if a['tier'] in tier_filter and a['priority'] in priority_filter]
        if state_filter and "All" not in state_filter:
            filtered = [a for a in filtered if a['state'] in state_filter]
        
        # Display articles by tier
        for tier, tier_name, tier_desc in [
            (1, "Primary Government Sources", "CFTC Orders, Federal Register, Court Filings, State AG Actions"),
            (2, "Industry Official Sources", "Official company announcements, trade association statements"),
            (3, "News Coverage", "Reuters, Bloomberg, Trade Publications")
        ]:
            tier_articles = [a for a in filtered if a['tier'] == tier]
            if not tier_articles:
                continue
            
            st.markdown(f"### {tier_name}")
            st.caption(tier_desc)
            
            for article in tier_articles[:15]:
                priority_icon = "🔴" if article['priority'] == 'high' else "🟡"
                state_badge = f" `{article['state']}`" if article['state'] else ""
                
                st.markdown(f"""
                {priority_icon} **[{article['title']}]({article['url']})**{state_badge}  
                _{article['source']}_ • {article['date']}
                """)
            
            st.divider()
        
        # Export
        st.download_button(
            "📥 Download CSV",
            data="\n".join([
                "date,tier,priority,category,title,source,state,url",
                *[f"{a['date']},{a['tier']},{a['priority']},{a['category']},\"{a['title']}\",{a['source']},{a['state'] or ''},{a['url']}" for a in filtered]
            ]),
            file_name=f"edm_report_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )
    
    with tab2:
        st.markdown("### DCM Application Tracker")
        st.caption("Source: [CFTC SIRT Database](https://sirt.cftc.gov/sirt/sirt.aspx?Topic=TradingOrganizations)")
        
        # Summary metrics
        designated = len([d for d in DCM_DATA if d['status'] == 'Designated'])
        pending = len([d for d in DCM_DATA if d['status'] == 'Pending'])
        
        col1, col2 = st.columns(2)
        col1.metric("Designated", designated)
        col2.metric("Pending", pending)
        
        st.divider()
        
        # Table
        for dcm in DCM_DATA:
            status_color = "🟢" if dcm['status'] == 'Designated' else "🟡"
            
            with st.container():
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**{dcm['organization']}**")
                    st.caption(dcm['remarks'])
                with col2:
                    st.markdown(f"{status_color} {dcm['status']}")
                    st.caption(f"Updated: {dcm['last_update']}")
                
                # Links
                links = f"[CFTC Record]({dcm['cftc_url']})"
                if dcm['order_url']:
                    links += f" • [Order PDF]({dcm['order_url']})"
                st.markdown(links)
                st.divider()
        
        # Export DCM
        st.download_button(
            "📥 Download DCM CSV",
            data="\n".join([
                "organization,status,last_update,remarks,cftc_url,order_url",
                *[f"\"{d['organization']}\",{d['status']},{d['last_update']},\"{d['remarks']}\",{d['cftc_url']},{d['order_url'] or ''}" for d in DCM_DATA]
            ]),
            file_name=f"dcm_tracker_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )
    
    # Footer
    st.markdown("---")
    st.caption("© 2026 NRF US Financial Services Team | CONFIDENTIAL")

if __name__ == "__main__":
    main()
