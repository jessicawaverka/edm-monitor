"""
Event-Driven Markets Monitor - PRODUCTION
==========================================
Beautiful React UI + Live Data Fetching
Deploy to Streamlit Cloud - runs automatically

NRF US Financial Services Team
"""

import streamlit as st
import streamlit.components.v1 as components
import requests
import feedparser
import json
import re
import hashlib
from datetime import datetime, timedelta
from urllib.parse import quote

# =============================================================================
# PAGE CONFIG
# =============================================================================
st.set_page_config(
    page_title="Event-Driven Markets Monitor | NRF",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Hide Streamlit UI elements for clean look
st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .block-container {padding: 0 !important; max-width: 100% !important;}
</style>
""", unsafe_allow_html=True)

# =============================================================================
# DATA FETCHING FUNCTIONS
# =============================================================================

KEYWORDS = [
    "prediction market", "event contract", "kalshi", "polymarket", 
    "nadex", "forecastex", "binary option", "cftc", "designated contract market",
    "dcm", "gaming commission", "sports wagering", "event-driven"
]

HIGH_PRIORITY = [
    "ruling", "court order", "injunction", "cease and desist", "enforcement",
    "approved", "denied", "designated", "lawsuit", "appeals court", "settlement"
]

EXCLUDED_DOMAINS = [
    "jdsupra.com", "lexology.com", "law.com", "nationallawreview.com",
    "mondaq.com", "findlaw.com", "martindale.com", "lawfirm",
    "skadden", "kirkland", "latham", "davispolk", "cravath", "sullivan",
    "gibsondunn", "sidley", "winston", "jonesday", "whitecase",
    "nortonrosefulbright"
]

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

def is_relevant(text):
    text_lower = text.lower()
    return any(kw in text_lower for kw in KEYWORDS)

def is_excluded(url):
    url_lower = url.lower()
    return any(domain in url_lower for domain in EXCLUDED_DOMAINS)

def get_priority(text):
    text_lower = text.lower()
    return "high" if any(kw in text_lower for kw in HIGH_PRIORITY) else "medium"

def extract_state(text):
    text_lower = text.lower()
    for state_name, abbrev in STATES.items():
        if state_name in text_lower:
            return abbrev
    return None

def clean_html(text):
    return re.sub(r'<[^>]+>', '', text).strip() if text else ""

def make_id(url):
    return hashlib.md5(url.encode()).hexdigest()[:10]

@st.cache_data(ttl=1800)
def fetch_federal_register():
    articles = []
    search_terms = ["prediction market", "event contract", "Kalshi", "designated contract market", "CFTC binary"]
    
    for term in search_terms:
        try:
            url = "https://www.federalregister.gov/api/v1/documents.json"
            params = {"conditions[term]": term, "per_page": 15, "order": "newest"}
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                for doc in response.json().get("results", []):
                    title = doc.get("title", "")
                    pdf_url = doc.get("pdf_url") or doc.get("html_url") or "https://www.federalregister.gov/d/" + doc.get('document_number', '')
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
        except:
            pass
    return articles

@st.cache_data(ttl=1800)
def fetch_cftc_rss():
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
                
                if not is_relevant(title + " " + summary):
                    continue
                
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
        except:
            pass
    return articles

@st.cache_data(ttl=1800)
def fetch_google_news():
    articles = []
    searches = [
        "Kalshi regulation OR lawsuit OR CFTC",
        "Polymarket CFTC OR regulation OR approved",
        "prediction market gaming commission state",
        "event contract CFTC designated",
    ]
    
    for query in searches:
        try:
            feed_url = "https://news.google.com/rss/search?q=" + quote(query) + "&hl=en-US&gl=US&ceid=US:en"
            feed = feedparser.parse(feed_url)
            
            for entry in feed.entries[:8]:
                title = clean_html(entry.get("title", ""))
                link = entry.get("link", "")
                
                if is_excluded(link):
                    continue
                
                pub = entry.get("published_parsed")
                date_str = datetime(*pub[:6]).strftime("%Y-%m-%d") if pub else datetime.now().strftime("%Y-%m-%d")
                
                source = "News"
                if " - " in title:
                    parts = title.rsplit(" - ", 1)
                    if len(parts) == 2:
                        title = parts[0]
                        source = parts[1]
                
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
        except:
            pass
    return articles

@st.cache_data(ttl=1800)
def fetch_state_sources():
    articles = []
    state_searches = [
        ("site:mass.gov attorney general Kalshi OR prediction market", "MA Attorney General", "MA", "enforcement"),
        ("site:gaming.nv.gov Kalshi OR Polymarket OR prediction", "Nevada Gaming Control Board", "NV", "state"),
        ("site:tn.gov sports wagering Kalshi", "Tennessee SWC", "TN", "enforcement"),
        ("site:ag.ny.gov prediction market OR Kalshi OR Polymarket", "NY Attorney General", "NY", "enforcement"),
        ("site:oag.ca.gov prediction market OR Kalshi", "CA Attorney General", "CA", "enforcement"),
    ]
    
    for query, source, state, category in state_searches:
        try:
            feed_url = "https://news.google.com/rss/search?q=" + quote(query) + "&hl=en-US"
            feed = feedparser.parse(feed_url)
            
            for entry in feed.entries[:3]:
                title = clean_html(entry.get("title", ""))
                link = entry.get("link", "")
                
                if " - " in title:
                    title = title.rsplit(" - ", 1)[0]
                
                pub = entry.get("published_parsed")
                date_str = datetime(*pub[:6]).strftime("%Y-%m-%d") if pub else datetime.now().strftime("%Y-%m-%d")
                
                articles.append({
                    "id": make_id(link),
                    "title": title,
                    "source": source,
                    "url": link,
                    "date": date_str,
                    "category": category,
                    "tier": 1,
                    "priority": "high",
                    "state": state
                })
        except:
            pass
    return articles

def fetch_all_data():
    all_articles = []
    all_articles.extend(fetch_federal_register())
    all_articles.extend(fetch_cftc_rss())
    all_articles.extend(fetch_state_sources())
    all_articles.extend(fetch_google_news())
    
    # Deduplicate
    seen = set()
    unique = []
    for article in all_articles:
        key = re.sub(r'[^a-z0-9]', '', article['title'].lower())[:40]
        if key not in seen and len(key) > 10:
            seen.add(key)
            unique.append(article)
    
    # Sort by date
    unique.sort(key=lambda x: x.get('date', ''), reverse=True)
    return unique

# =============================================================================
# DCM DATA
# =============================================================================

DCM_DATA = [
    {
        "organization": "KalshiEX LLC",
        "status": "Designated",
        "statusDate": "2025-01-17",
        "remarks": "Commission granted petition to permit intermediated futures trading",
        "detailUrl": "https://www.cftc.gov/IndustryOversight/IndustryFilings/TradingOrganizations/42993",
        "orderPdfUrl": "https://www.cftc.gov/PressRoom/PressReleases/8302-20"
    },
    {
        "organization": "QCX LLC d/b/a Polymarket US",
        "status": "Designated",
        "statusDate": "2025-11-24",
        "remarks": "Amended Order of Designation permits intermediated trading",
        "detailUrl": "https://www.cftc.gov/IndustryOversight/IndustryFilings/TradingOrganizations/49571",
        "orderPdfUrl": "https://www.cftc.gov/media/12806/download"
    },
    {
        "organization": "ForecastEx LLC",
        "status": "Designated",
        "statusDate": "2023-06-22",
        "remarks": "Event contracts exchange owned by Interactive Brokers",
        "detailUrl": "https://www.cftc.gov/IndustryOversight/IndustryFilings/TradingOrganizations/47651",
        "orderPdfUrl": "https://www.cftc.gov/PressRoom/PressReleases/8721-23"
    },
    {
        "organization": "Nadex",
        "status": "Designated",
        "statusDate": "2010-12-13",
        "remarks": "Binary options exchange",
        "detailUrl": "https://www.cftc.gov/IndustryOversight/IndustryFilings/TradingOrganizations/21321",
        "orderPdfUrl": None
    },
    {
        "organization": "Bitnomial Exchange, LLC",
        "status": "Designated",
        "statusDate": "2020-04-17",
        "remarks": "Bitcoin derivatives exchange",
        "detailUrl": "https://www.cftc.gov/IndustryOversight/IndustryFilings/TradingOrganizations/35346",
        "orderPdfUrl": None
    },
    {
        "organization": "Aristotle Exchange DCM, Inc.",
        "status": "Pending",
        "statusDate": "2021-10-07",
        "remarks": "Application pending since 2021",
        "detailUrl": "https://www.cftc.gov/IndustryOversight/IndustryFilings/TradingOrganizations/46990",
        "orderPdfUrl": None
    },
]

# =============================================================================
# FETCH DATA
# =============================================================================

articles = fetch_all_data()
last_updated = datetime.now().strftime("%B %d, %Y at %I:%M %p ET")

# =============================================================================
# BUILD HTML (avoiding f-string issues)
# =============================================================================

articles_json = json.dumps(articles)
dcm_json = json.dumps(DCM_DATA)

html_template = '''
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Event-Driven Markets Monitor</title>
  <script src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
  <script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
  <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
  <link href="https://fonts.googleapis.com/css2?family=Crimson+Pro:wght@400;600;700&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: 'IBM Plex Sans', -apple-system, sans-serif; background: #f5f5f0; }
    ::-webkit-scrollbar { width: 8px; }
    ::-webkit-scrollbar-track { background: #f1f1f1; }
    ::-webkit-scrollbar-thumb { background: #ccc; border-radius: 4px; }
    a { color: #1e3a5f; text-decoration: none; }
    a:hover { text-decoration: underline; }
  </style>
</head>
<body>
  <div id="root"></div>
  
  <script type="text/babel">
    const { useState, useMemo } = React;
    
    // LIVE DATA FROM SERVER
    const ARTICLES = __ARTICLES_JSON__;
    const DCM_DATA = __DCM_JSON__;
    const LAST_UPDATED = "__LAST_UPDATED__";

    function App() {
      const [selectedState, setSelectedState] = useState(null);
      const [activeTab, setActiveTab] = useState('developments');
      const [dateRange, setDateRange] = useState({
        start: new Date(Date.now() - 90 * 24 * 60 * 60 * 1000).toISOString().split('T')[0],
        end: new Date().toISOString().split('T')[0]
      });

      const filteredData = useMemo(() => {
        return ARTICLES.filter(item => {
          if (dateRange.start && item.date < dateRange.start) return false;
          if (dateRange.end && item.date > dateRange.end) return false;
          if (selectedState && item.state !== selectedState) return false;
          return true;
        });
      }, [dateRange, selectedState]);

      const analytics = useMemo(() => {
        const byState = {};
        const byTier = { 1: 0, 2: 0, 3: 0 };
        const byPriority = { high: 0, medium: 0 };
        
        filteredData.forEach(item => {
          if (item.state) byState[item.state] = (byState[item.state] || 0) + 1;
          byTier[item.tier] = (byTier[item.tier] || 0) + 1;
          byPriority[item.priority] = (byPriority[item.priority] || 0) + 1;
        });
        
        return { byState, byTier, byPriority };
      }, [filteredData]);

      const exportCSV = () => {
        const headers = ['Date', 'Tier', 'Priority', 'Title', 'Source', 'State', 'URL'];
        const rows = filteredData.map(item => [
          item.date, item.tier, item.priority,
          '"' + item.title.replace(/"/g, '""') + '"',
          item.source, item.state || '', item.url
        ]);
        const csv = [headers.join(','), ...rows.map(r => r.join(','))].join('\\n');
        const blob = new Blob([csv], { type: 'text/csv' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'edm_report_' + new Date().toISOString().split('T')[0] + '.csv';
        a.click();
      };

      const tierInfo = {
        1: { label: 'Primary Government Sources', color: '#1e3a5f', desc: 'Federal Register, CFTC, State AG Actions' },
        3: { label: 'News Coverage', color: '#666666', desc: 'Reuters, Bloomberg, Trade Publications' }
      };

      return (
        <div style={{minHeight: '100vh'}}>
          {/* Header */}
          <header style={{
            background: 'linear-gradient(135deg, #1a2634 0%, #2d3e50 100%)',
            color: 'white', padding: '16px 24px',
            display: 'flex', justifyContent: 'space-between', alignItems: 'center'
          }}>
            <div style={{display: 'flex', alignItems: 'center', gap: '16px'}}>
              <div style={{
                width: '48px', height: '48px',
                background: 'linear-gradient(135deg, #c9a962 0%, #d4b97a 100%)',
                borderRadius: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontFamily: "'Crimson Pro', serif", fontSize: '24px', fontWeight: '700', color: '#1a2634'
              }}>E</div>
              <div>
                <h1 style={{fontSize: '20px', fontWeight: '600', margin: 0}}>Event-Driven Markets Monitor</h1>
                <p style={{fontSize: '12px', color: '#a0a0a0', margin: 0, letterSpacing: '1px', textTransform: 'uppercase'}}>
                  Regulatory Intelligence • Live Data
                </p>
              </div>
            </div>
            <div style={{textAlign: 'right'}}>
              <div style={{fontSize: '11px', color: '#a0a0a0', textTransform: 'uppercase', letterSpacing: '1px'}}>
                NRF US Financial Services Team
              </div>
              <div style={{fontSize: '13px', color: '#c9a962'}}>
                Last Updated: {LAST_UPDATED}
              </div>
            </div>
          </header>

          {/* Tabs */}
          <div style={{background: '#1a2634', padding: '0 24px', borderTop: '1px solid rgba(255,255,255,0.1)'}}>
            <div style={{display: 'flex', gap: '0'}}>
              <button onClick={() => setActiveTab('developments')} style={{
                background: activeTab === 'developments' ? '#f5f5f0' : 'transparent',
                color: activeTab === 'developments' ? '#1a2634' : '#a0a0a0',
                border: 'none', padding: '12px 24px', cursor: 'pointer',
                fontSize: '14px', fontWeight: '500',
                borderRadius: activeTab === 'developments' ? '6px 6px 0 0' : '0'
              }}>📰 Regulatory Developments</button>
              <button onClick={() => setActiveTab('dcm')} style={{
                background: activeTab === 'dcm' ? '#f5f5f0' : 'transparent',
                color: activeTab === 'dcm' ? '#1a2634' : '#a0a0a0',
                border: 'none', padding: '12px 24px', cursor: 'pointer',
                fontSize: '14px', fontWeight: '500',
                borderRadius: activeTab === 'dcm' ? '6px 6px 0 0' : '0'
              }}>🏛️ DCM Application Tracker</button>
            </div>
          </div>

          {/* Main */}
          <div style={{display: 'flex', minHeight: 'calc(100vh - 140px)'}}>
            {/* Sidebar */}
            <aside style={{width: '280px', background: 'white', borderRight: '1px solid #e0e0e0', padding: '20px', flexShrink: 0}}>
              {/* Date Range */}
              <div style={{marginBottom: '24px'}}>
                <h3 style={{fontSize: '11px', textTransform: 'uppercase', letterSpacing: '1px', color: '#666', marginBottom: '12px'}}>📅 Date Range</h3>
                <div style={{display: 'flex', gap: '8px'}}>
                  <input type="date" value={dateRange.start} onChange={(e) => setDateRange({...dateRange, start: e.target.value})}
                    style={{flex: 1, padding: '8px', border: '1px solid #ddd', borderRadius: '4px', fontSize: '12px'}} />
                  <input type="date" value={dateRange.end} onChange={(e) => setDateRange({...dateRange, end: e.target.value})}
                    style={{flex: 1, padding: '8px', border: '1px solid #ddd', borderRadius: '4px', fontSize: '12px'}} />
                </div>
              </div>

              {/* Stats */}
              <div style={{marginBottom: '24px'}}>
                <h3 style={{fontSize: '11px', textTransform: 'uppercase', letterSpacing: '1px', color: '#666', marginBottom: '12px'}}>📊 Summary</h3>
                <div style={{display: 'flex', flexDirection: 'column', gap: '8px'}}>
                  <div style={{display: 'flex', justifyContent: 'space-between', padding: '8px', background: '#f5f5f5', borderRadius: '4px'}}>
                    <span>Total Items</span>
                    <span style={{fontWeight: '600'}}>{filteredData.length}</span>
                  </div>
                  <div style={{display: 'flex', justifyContent: 'space-between', padding: '8px', background: '#f5f5f5', borderRadius: '4px'}}>
                    <span>Primary Sources</span>
                    <span style={{fontWeight: '600', color: '#1e3a5f'}}>{analytics.byTier[1]}</span>
                  </div>
                  <div style={{display: 'flex', justifyContent: 'space-between', padding: '8px', background: '#fff5f5', borderRadius: '4px'}}>
                    <span>🔴 High Priority</span>
                    <span style={{fontWeight: '600', color: '#c41e3a'}}>{analytics.byPriority.high}</span>
                  </div>
                </div>
              </div>

              {/* Export */}
              <button onClick={exportCSV} style={{
                width: '100%', padding: '12px', background: '#1e3a5f', color: 'white',
                border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '14px', fontWeight: '500'
              }}>📥 Export CSV</button>
              
              {/* State Filter */}
              {Object.keys(analytics.byState).length > 0 && (
                <div style={{marginTop: '24px'}}>
                  <h3 style={{fontSize: '11px', textTransform: 'uppercase', letterSpacing: '1px', color: '#666', marginBottom: '12px'}}>🗺️ Active States</h3>
                  <div style={{display: 'flex', flexWrap: 'wrap', gap: '6px'}}>
                    {Object.entries(analytics.byState).map(([state, count]) => (
                      <button key={state} onClick={() => setSelectedState(selectedState === state ? null : state)} style={{
                        padding: '4px 10px', borderRadius: '4px', cursor: 'pointer', fontSize: '12px',
                        background: selectedState === state ? '#c41e3a' : '#2d5a3d',
                        color: 'white', border: 'none'
                      }}>{state} ({count})</button>
                    ))}
                    {selectedState && (
                      <button onClick={() => setSelectedState(null)} style={{
                        padding: '4px 10px', borderRadius: '4px', cursor: 'pointer', fontSize: '12px',
                        background: '#666', color: 'white', border: 'none'
                      }}>Clear</button>
                    )}
                  </div>
                </div>
              )}
            </aside>

            {/* Content */}
            <main style={{flex: 1, padding: '20px', overflow: 'auto'}}>
              {activeTab === 'developments' && (
                <div>
                  {/* Executive Brief */}
                  <div style={{
                    background: 'linear-gradient(135deg, #1a2634 0%, #2d3e50 100%)',
                    borderRadius: '8px', padding: '20px 24px', marginBottom: '24px', color: 'white'
                  }}>
                    <h2 style={{fontSize: '12px', textTransform: 'uppercase', letterSpacing: '2px', color: '#c9a962', marginBottom: '16px'}}>
                      📈 Executive Intelligence Brief
                    </h2>
                    <div style={{display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '24px'}}>
                      <div>
                        <div style={{fontSize: '11px', color: '#a0a0a0', textTransform: 'uppercase'}}>Total Items</div>
                        <div style={{fontSize: '28px', fontWeight: '700', fontFamily: "'Crimson Pro', serif"}}>{filteredData.length}</div>
                      </div>
                      <div>
                        <div style={{fontSize: '11px', color: '#a0a0a0', textTransform: 'uppercase'}}>Primary Sources</div>
                        <div style={{fontSize: '28px', fontWeight: '700', fontFamily: "'Crimson Pro', serif"}}>{analytics.byTier[1]}</div>
                      </div>
                      <div>
                        <div style={{fontSize: '11px', color: '#a0a0a0', textTransform: 'uppercase'}}>High Priority</div>
                        <div style={{fontSize: '28px', fontWeight: '700', fontFamily: "'Crimson Pro', serif", color: '#c41e3a'}}>{analytics.byPriority.high}</div>
                      </div>
                    </div>
                  </div>

                  {/* Articles by Tier */}
                  {[1, 3].map(tier => {
                    const tierData = filteredData.filter(d => d.tier === tier);
                    if (tierData.length === 0) return null;
                    const info = tierInfo[tier];
                    
                    return (
                      <div key={tier} style={{marginBottom: '24px'}}>
                        <div style={{
                          display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '12px',
                          padding: '8px 12px', background: info.color + '15', borderRadius: '6px',
                          borderLeft: '3px solid ' + info.color
                        }}>
                          <span style={{background: info.color, color: 'white', padding: '2px 8px', borderRadius: '4px', fontSize: '11px', fontWeight: '600'}}>
                            {tierData.length}
                          </span>
                          <div>
                            <div style={{fontWeight: '600', fontSize: '14px'}}>{info.label}</div>
                            <div style={{fontSize: '12px', color: '#666'}}>{info.desc}</div>
                          </div>
                        </div>
                        
                        {tierData.slice(0, 20).map(item => (
                          <div key={item.id} style={{
                            background: 'white', borderRadius: '6px', padding: '16px', marginBottom: '8px',
                            borderLeft: '3px solid ' + (item.priority === 'high' ? '#c41e3a' : '#d4a017'),
                            boxShadow: '0 1px 3px rgba(0,0,0,0.08)'
                          }}>
                            <a href={item.url} target="_blank" rel="noopener noreferrer" style={{
                              fontSize: '15px', fontWeight: '500', color: '#1a2634',
                              textDecoration: 'none', display: 'block', marginBottom: '6px'
                            }}>
                              {item.priority === 'high' ? '🔴 ' : '🟡 '}{item.title} ↗
                            </a>
                            <div style={{fontSize: '13px', color: '#666'}}>
                              {item.source} • {item.date}
                              {item.state && <span style={{background: '#2d5a3d', color: 'white', padding: '1px 6px', borderRadius: '3px', fontSize: '11px', marginLeft: '8px'}}>{item.state}</span>}
                            </div>
                          </div>
                        ))}
                      </div>
                    );
                  })}
                </div>
              )}

              {activeTab === 'dcm' && (
                <div>
                  <div style={{
                    background: 'linear-gradient(135deg, #1a2634 0%, #2d3e50 100%)',
                    borderRadius: '8px', padding: '20px 24px', marginBottom: '24px', color: 'white'
                  }}>
                    <h2 style={{fontSize: '12px', textTransform: 'uppercase', letterSpacing: '2px', color: '#c9a962', marginBottom: '8px'}}>
                      🏛️ DCM Application Tracker
                    </h2>
                    <p style={{fontSize: '14px', color: '#a0a0a0', margin: 0}}>
                      Designated Contract Markets - Event Contracts & Prediction Markets
                    </p>
                  </div>

                  <div style={{background: 'white', borderRadius: '8px', overflow: 'hidden', boxShadow: '0 1px 3px rgba(0,0,0,0.1)'}}>
                    <table style={{width: '100%', borderCollapse: 'collapse'}}>
                      <thead>
                        <tr style={{background: '#f5f5f0'}}>
                          <th style={{padding: '12px 16px', textAlign: 'left', fontSize: '12px', textTransform: 'uppercase', color: '#666', borderBottom: '2px solid #e0e0e0'}}>Organization</th>
                          <th style={{padding: '12px 16px', textAlign: 'left', fontSize: '12px', textTransform: 'uppercase', color: '#666', borderBottom: '2px solid #e0e0e0'}}>Status</th>
                          <th style={{padding: '12px 16px', textAlign: 'left', fontSize: '12px', textTransform: 'uppercase', color: '#666', borderBottom: '2px solid #e0e0e0'}}>Last Update</th>
                          <th style={{padding: '12px 16px', textAlign: 'left', fontSize: '12px', textTransform: 'uppercase', color: '#666', borderBottom: '2px solid #e0e0e0'}}>Links</th>
                        </tr>
                      </thead>
                      <tbody>
                        {DCM_DATA.map((dcm, idx) => (
                          <tr key={idx} style={{borderBottom: '1px solid #eee'}}>
                            <td style={{padding: '14px 16px'}}>
                              <div style={{fontWeight: '500'}}>{dcm.organization}</div>
                              <div style={{fontSize: '12px', color: '#666', marginTop: '4px'}}>{dcm.remarks}</div>
                            </td>
                            <td style={{padding: '14px 16px'}}>
                              <span style={{
                                background: dcm.status === 'Designated' ? '#2d5a3d' : '#d4a017',
                                color: 'white', padding: '4px 10px', borderRadius: '4px', fontSize: '12px'
                              }}>{dcm.status}</span>
                            </td>
                            <td style={{padding: '14px 16px', fontSize: '13px', color: '#666'}}>{dcm.statusDate}</td>
                            <td style={{padding: '14px 16px'}}>
                              <a href={dcm.detailUrl} target="_blank" style={{color: '#1e3a5f', fontSize: '12px', marginRight: '12px'}}>CFTC Record ↗</a>
                              {dcm.orderPdfUrl && <a href={dcm.orderPdfUrl} target="_blank" style={{color: '#c41e3a', fontSize: '12px'}}>Order ↗</a>}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <div style={{marginTop: '16px', fontSize: '12px', color: '#666'}}>
                    Source: <a href="https://sirt.cftc.gov/sirt/sirt.aspx?Topic=TradingOrganizations" target="_blank" style={{color: '#1e3a5f'}}>CFTC SIRT Database</a>
                  </div>
                </div>
              )}
            </main>
          </div>

          {/* Footer */}
          <footer style={{
            background: '#1a2634', color: '#666', padding: '12px 24px', fontSize: '11px',
            display: 'flex', justifyContent: 'space-between', alignItems: 'center'
          }}>
            <span>© 2026 NRF US Financial Services Team • Data updates automatically</span>
            <span>CONFIDENTIAL</span>
          </footer>
        </div>
      );
    }

    ReactDOM.render(<App />, document.getElementById('root'));
  </script>
</body>
</html>
'''

# Replace placeholders with actual data
html_content = html_template.replace('__ARTICLES_JSON__', articles_json)
html_content = html_content.replace('__DCM_JSON__', dcm_json)
html_content = html_content.replace('__LAST_UPDATED__', last_updated)

# Render
components.html(html_content, height=900, scrolling=True)
