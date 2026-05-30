import feedparser

rss_feeds = {

    "NVIDIA":
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=NVDA&region=US&lang=en-US",

    "AMD":
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=AMD&region=US&lang=en-US",

    "Micron":
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=MU&region=US&lang=en-US",

    "SanDisk":
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=SNDK&region=US&lang=en-US"

}

def collect_news():

    all_news = ""

    for company, url in rss_feeds.items():

        feed = feedparser.parse(url)

        all_news += f"\n\n{company} NEWS:\n"

        for entry in feed.entries[:3]:

            all_news += f"- {entry.title}\n"

    return all_news
