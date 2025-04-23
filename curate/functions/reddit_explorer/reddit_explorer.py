import inspect
import os
import tomllib
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

import praw

from ..common.python.gemini_client import create_client

_MARKDOWN_FORMAT = """
# {title}

**Upvotes**: {upvotes}

{image_or_video_or_none}

[View on Reddit]({permalink})

{summary}
"""

class Config:
    reddit_top_posts_limit = 10
    reddit_top_comments_limit = 3
    summary_index_s3_key_format = "reddit_explorer/{date}.md"

    @classmethod
    def load_subreddits(cls) -> list[str]:
        subreddits_toml_path = os.path.join(os.path.dirname(__file__), "subreddits.toml")
        with open(subreddits_toml_path, "rb") as f:
            subreddits_data = tomllib.load(f)
        return [subreddit["name"] for subreddit in subreddits_data.get("subreddits", [])]

@dataclass
class RedditPost:
    type: Literal["image", "gallery", "video", "poll", "crosspost", "text", "link"]
    id: str
    title: str
    url: str | None
    upvotes: int
    text: str
    permalink: str = ""
    comments: list[dict[str, str | int]] = field(init=False)
    summary: str = field(init=False)
    thumbnail: str = "self"

class RedditExplorer:
    def __init__(self):
        self._reddit = praw.Reddit(
            client_id=os.environ.get("REDDIT_CLIENT_ID"),
            client_secret=os.environ.get("REDDIT_CLIENT_SECRET"),
            user_agent=os.environ.get("REDDIT_USER_AGENT"),
        )
        self._client = create_client()
        self._subreddits = Config.load_subreddits()

    def __call__(self) -> None:
        markdowns = []
        for subreddit in self._subreddits:
            posts = self._retrieve_hot_posts(subreddit)
            for post in posts:
                post.comments = self._retrieve_top_comments_of_post(post.id)
                post.summary = self._summarize_reddit_post(post)
                markdowns.append(self._stylize_post(post))
        self._store_summaries(markdowns)

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

    def _retrieve_hot_posts(
        self, subreddit: str, limit: int = None
    ) -> list[RedditPost]:
        if limit is None:
            limit = Config.reddit_top_posts_limit

        posts = []
        for post in self._reddit.subreddit(subreddit).hot(limit=limit):
            post_type = self.__judge_post_type(post)

            url = self._get_video_url(post) if post_type == "video" else post.url

            # filter out undesired posts
            if post.author.name == "AutoModerator":
                continue
            if "megathread" in post.title.lower():
                continue
            if post.upvote_ratio < 0.7:
                continue
            if ["gallery", "poll", "crosspost"].__contains__(post_type):
                continue
            posts.append(
                RedditPost(
                    type=post_type,
                    id=post.id,
                    title=post.title,
                    url=url,
                    upvotes=post.ups,
                    text=post.selftext,
                    thumbnail=post.thumbnail,
                )
            )
            posts[-1].permalink = f"https://www.reddit.com{post.permalink}"
        return posts

    def _retrieve_top_comments_of_post(
        self,
        post_id: str,
        limit: int = None,
    ) -> list[dict[str, str | int]]:
        if limit is None:
            limit = Config.reddit_top_comments_limit

        submission = self._reddit.submission(id=post_id)
        submission.comments.replace_more(limit=0)
        return [
            {
                "text": comment.body,
                "upvotes": comment.ups,
            }
            for comment in submission.comments.list()[:limit]
        ]

    def _summarize_reddit_post(self, post: RedditPost) -> str:
        comments_text = "\n".join(
            [
                f"{comment['upvotes']} upvotes: {comment['text']}"
                for comment in post.comments
            ]
        )

        return self._client.generate_content(
            contents=self._contents,
            system_instruction=self._system_instruction_format(
                title=post.title,
                comments=comments_text,
                selftext=post.text,
            ),
        )

    def __judge_post_type(
        self, post: praw.models.Submission
    ) -> Literal["image", "gallery", "video", "poll", "crosspost", "text", "link"]:
        if getattr(post, "post_hint", "") == "image":
            return "image"
        elif getattr(post, "is_gallery", False):
            return "gallery"
        elif getattr(post, "is_video", False):
            return "video"
        elif hasattr(post, "poll_data"):
            return "poll"
        elif hasattr(post, "crosspost_parent"):
            return "crosspost"
        elif post.is_self:
            return "text"
        return "link"

    def _get_video_url(self, post: praw.models.Submission) -> str | None:
        if hasattr(post, "media"):
            return post.media.get("reddit_video", {}).get("fallback_url", None)
        elif hasattr(post, "secure_media"):
            return post.secure_media.get("reddit_video", {}).get("fallback_url", None)
        else:
            return None

    def _stylize_post(self, post: RedditPost) -> str:
        return _MARKDOWN_FORMAT.format(
            title=post.title,
            upvotes=post.upvotes,
            image_or_video_or_none=(
                f"![Image]({post.url})"
                if post.type == "image"
                else f'<video src="{post.url}" controls controls style="width: 100%; height: auto; max-height: 500px;"></video>'
                if post.type == "video" and post.url is not None
                else ""
            ),
            permalink=post.permalink,
            summary=post.summary,
        )

    def _system_instruction_format(
        self, title: str, comments: str, selftext: str
    ) -> str:
        self_text = inspect.cleandoc(
            f"""
            Post Text
            '''
            {selftext}
            '''
            """
        )
        return inspect.cleandoc(
            f"""
            The following text contains the title of a Reddit post, {"the post text, and" if selftext else ""} and the main comments for the post.
            Please read it carefully and answer the user's question.

            Title
            '''
            {title}
            '''

            {self_text if selftext else ""}

            Comments
            '''
            {comments}
            '''
            """
        )

    @property
    def _contents(self) -> str:
        return inspect.cleandoc(
            """
            Please answer the following two questions in detail and clearly.

            1. Describe the content of this post.
            2. Among the comments on this post, which ones are particularly interesting?

            Do not output anything other than the answers to these questions.
            """
        )


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    print(event)

    try:
        if event.get("source") == "aws.events":
            reddit_explorer_ = RedditExplorer()
            reddit_explorer_()
        return {"statusCode": 200}
    except Exception as e:
        print(traceback.format_exc())
        print(e)
        return {"statusCode": 500}
