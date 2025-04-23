import os
from dataclasses import dataclass
from datetime import date
from typing import Any

import requests
import tomllib
from bs4 import BeautifulSoup

_MARKDOWN_FORMAT = """
# {title}

**Score**: {score}

[View Link]({url})

{description}
"""

class Config:
    url_format = "https://github.com/trending/{language}?since=daily"
    summary_index_s3_key_format = "github_trending/{date}.md"

    @classmethod
    def load_languages(cls) -> list[str]:
        languages_toml_path = os.path.join(os.path.dirname(__file__), "languages.toml")
        with open(languages_toml_path, "rb") as f:
            languages_data = tomllib.load(f)
        return [language["name"] for language in languages_data.get("languages", [])]

@dataclass
class Repository:
    name: str
    description: str | None
    link: str
    stars: int

class GithubTrending:
    def __init__(self):
        self._languages = Config.load_languages()

    def __call__(self) -> None:
        markdowns = []
        for language in self._languages:
            new_repositories = self._retrieve_repositories(
                Config.url_format.format(language=language)
            )
            markdowns += [self._stylize_repository_info(repository) for repository in new_repositories]
        self._store_summaries(markdowns)

    def _retrieve_repositories(self, url: str) -> list[Repository]:
        response = requests.get(url)
        soup = BeautifulSoup(response.text, "html.parser")
        repositories = []
        for repo in soup.find_all("h2", class_="h3 lh-condensed"):
            name = repo.a.text.strip().replace("\n", "").replace(" ", "")
            description = (
                p.text.strip()
                if (p := repo.parent.find("p", class_="col-9 color-fg-muted my-1 pr-4"))
                else None
            )
            stars = int(
                repo.parent.find("a", href=lambda href: href and "stargazers" in href)
                .text.strip()
                .replace(",", "")
            )
            repositories.append(
                Repository(name=name, link=f"https://github.com/{name}", description=description, stars=stars)
            )
        return repositories

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

    def _stylize_repository_info(self, repository: Repository) -> str:
        return _MARKDOWN_FORMAT.format(
            title=repository.name,
            score=repository.stars,
            url=repository.link,
            description=repository.description or "No description",
        )


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    pprint(event)

    try:
        if event.get("source") == "aws.events":
            github_trending_ = GithubTrending()
            github_trending_()

        return {"statusCode": 200}
    except Exception as e:
        pprint(traceback.format_exc())
        pprint(e)
        return {"statusCode": 500}
