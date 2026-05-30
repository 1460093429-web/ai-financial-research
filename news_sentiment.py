import requests
import json
from datetime import datetime, timedelta
from config import get_openai_client

client = get_openai_client()

WATCHLIST = {
    "NVIDIA": "NVDA",
    "Micron": "MU",
    "SanDisk": "SNDK",
}

RSS_FEEDS = {
    "NVDA": [
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=NVDA&region=US&lang=en-US",
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=NVDA&region=US&lang=en-US",
    ],
    "MU": [
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=MU&region=US&lang=en-US",
    ],
    "SNDK": [
        "https://feeds.finance.yahoo.com/rss/2.0/headline?s=SNDK&region=US&lang=en-US",
    ],
}

def fetch_news(ticker, max_items=10):
    """Fetch news from Yahoo Finance RSS."""
    import feedparser
    news_items = []
    
    feeds = RSS_FEEDS.get(ticker, [])
    for feed_url in feeds:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:max_items]:
                news_items.append({
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", ""),
                    "published": entry.get("published", ""),
                    "link": entry.get("link", ""),
                })
        except Exception as e:
            print(f"Error fetching news for {ticker}: {e}")
    
    return news_items[:max_items]

def analyze_sentiment(ticker, news_items):
    """Use AI to analyze news sentiment."""
    if not news_items:
        return None
    
    # Prepare news text
    news_text = ""
    for i, item in enumerate(news_items[:8]):
        news_text += f"{i+1}. {item['title']}\n"
        if item['summary']:
            news_text += f"   {item['summary'][:200]}\n"
    
    prompt = f"""
You are a financial analyst. Analyze the sentiment of these recent news headlines for {ticker}:

{news_text}

Provide:
1. Overall Sentiment: BULLISH / BEARISH / NEUTRAL (one word)
2. Sentiment Score: -10 (very bearish) to +10 (very bullish)
3. Key Themes: Top 3 themes in the news
4. Risk Factors: Any mentioned risks
5. One-line Summary: Brief overall assessment

Format your response as JSON:
{{
    "sentiment": "BULLISH/BEARISH/NEUTRAL",
    "score": 0,
    "themes": ["theme1", "theme2", "theme3"],
    "risks": ["risk1", "risk2"],
    "summary": "one line summary"
}}
"""
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        
        result = json.loads(response.choices[0].message.content)
        return result
    except Exception as e:
        print(f"AI analysis error: {e}")
        return None

def run_news_sentiment():
    print(f"\n{'='*60}")
    print(f"News Sentiment Analysis - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")
    
    results = {}
    
    for company, ticker in WATCHLIST.items():
        print(f"\n--- {company} ({ticker}) ---")
        
        # Fetch news
        news = fetch_news(ticker)
        print(f"Found {len(news)} news items")
        
        if not news:
            print("No news available")
            continue
        
        # Print headlines
        print("\nLatest Headlines:")
        for item in news[:5]:
            print(f"  • {item['title']}")
        
        # AI sentiment analysis
        sentiment = analyze_sentiment(ticker, news)
        
        if sentiment:
            score = sentiment.get("score", 0)
            if score >= 3:
                emoji = "🟢"
            elif score <= -3:
                emoji = "🔴"
            else:
                emoji = "🟡"
            
            print(f"\n{emoji} Sentiment: {sentiment.get('sentiment')} (Score: {score}/10)")
            print(f"Summary: {sentiment.get('summary')}")
            print(f"Key Themes: {', '.join(sentiment.get('themes', []))}")
            if sentiment.get('risks'):
                print(f"Risks: {', '.join(sentiment.get('risks', []))}")
            
            results[ticker] = sentiment
    
    return results

if __name__ == "__main__":
    run_news_sentiment()
