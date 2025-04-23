import inspect
import os
from dataclasses import dataclass
from datetime import date
from typing import Any

import requests
from bs4 import BeautifulSoup

from ..common.python.gemini_client import create_client

_MARKDOWN_FORMAT = """
# {title}

**Score**: {score}

{url_or_text}
"""

class Config:
    hacker_news_top_stories_url = "https://hacker-news.firebaseio.com/v0/topstories.json"
    hacker_news_item_url = "https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
    hacker_news_num_top_stories = 30
    summary_index_s3_key_format = "hacker_news/{date}.md"

@dataclass
class Story:
    title: str
    score: int
    url: str | None = None
    text: str | None = None

class HackerNewsRetriever:
    def __init__(self):
        self._client = create_client()

    def __call__(self) -> None:
        stories = self._get_top_stories()
        styled_attachments = [self._stylize_story(story) for story in stories]
        self._store_summaries(styled_attachments)

    def _get_top_stories(self) -> list[Story]:
        top_stories = self._get_top_storie_ids()[:Config.hacker_news_num_top_stories]
        stories = []
        for story_id in top_stories:
            story = self._get_story(story_id)
            if story["score"] < 20:
                continue
            summary = None
            if story.get("text"):
                if 100 < len(story["text"]) < 10000:
                    summary = self._summarize_story(story)
                else:
                    summary = self._cleanse_text(story["text"])
            stories.append(
                Story(
                    title=story["title"],
                    score=story["score"],
                    url=story.get("url"),
                    text=story.get("text") if summary is None else summary,
                )
            )
        return stories

    def _summarize_story(self, story: dict[str, str | int]) -> str:
        return self._client.generate_content(
            contents=self._contents_format.format(
                title=story["title"], text=self._cleanse_text(story["text"])
            ),
            system_instruction=self._system_instruction,
        )

    def _get_top_storie_ids(self) -> list[int]:
        return requests.get(
            Config.hacker_news_top_stories_url,
            headers={"Content-Type": "application/json"},
        ).json()

    def _get_story(self, story_id: int) -> dict[str, str]:
        return requests.get(
            Config.hacker_news_item_url.format(story_id=story_id),
            headers={"Content-Type": "application/json"},
        ).json()

    def _cleanse_text(self, text: str) -> str:
        return BeautifulSoup(text, "html.parser").get_text()

    def _store_summaries(self, summaries: list[str]) -> None:
        date_str = date.today().strftime("%Y-%m-%d")
        key = Config.summary_index_s3_key_format.format(date=date_str)
        output_dir = os.environ.get("OUTPUT_DIR", "./output")
        os.makedirs(output_dir, exist_ok=True)
        file_path = os.path.join(output_dir, key)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n---\n".join(summaries))
        print(f"Saved summaries to {file_path}")

    def _stylize_story(self, story: Story) -> str:
        url_or_text = f"[View Link]({story.url})" if story.url else story.text
        return _MARKDOWN_FORMAT.format(
            title=story.title,
            score=story.score,
            url_or_text=url_or_text,
        )

    @property
    def _system_instruction(self) -> str:
        return inspect.cleandoc(
            """
            You are an assistant who summarizes the latest articles from Hacker News.
            Given the title and content of an article, you are to summarize it in English.
            No output other than the summary is required.
            """
        )

    @property
    def _contents_format(self) -> str:
        return inspect.cleandoc(
            """
            Title
            ```
            {title}
            ```

            Content
            ```
            {text}
            ```
            """
        )


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    pprint(event)

    try:
        # if the lambda is invoked by a cron job,
        # call the paper summarizer without any incoming text
        if event.get("source") == "aws.events":
            retriever = HackerNewsRetriever()
            retriever()

        return {"statusCode": 200}
    except Exception as e:
        pprint(traceback.format_exc())
        pprint(e)
        return {"statusCode": 500}
