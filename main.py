# main.py
import os
from datetime import date

#from nook.functions.tech_feed.tech_feed import TechFeed
from dotenv import load_dotenv

from nook.functions.github_trending.github_trending import GithubTrending
from nook.functions.hacker_news.hacker_news import HackerNewsRetriever
from nook.functions.paper_summarizer.paper_summarizer import PaperSummarizer
from nook.functions.reddit_explorer.reddit_explorer import RedditExplorer


def run_all():
    load_dotenv()
    
    OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "./output")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.environ["OUTPUT_DIR"] = OUTPUT_DIR

    handlers = [
        PaperSummarizer(),
        HackerNewsRetriever(),
        RedditExplorer(),
        GithubTrending(),
#     TechFeed(),
    ]
    
    for handler in handlers:
        print(f"Running {handler.__class__.__name__}...")
        handler()
        print(f"Completed {handler.__class__.__name__}")

if __name__ == "__main__":
    run_all()