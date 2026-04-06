"""Seed the registry with example skills."""
import json
import time
import sqlite3
import hashlib
import os
from pathlib import Path

DB_PATH = os.getenv("REGISTRY_DB", str(Path.home() / ".theora" / "registry.db"))

SEED_SKILLS = [
    {
        "skill_id": "web_search",
        "version": "1.0.0",
        "author": "theora-team",
        "brand": {"name": "Web Search", "icon": "search"},
        "description": "Search the web using Tavily, DuckDuckGo, or Brave Search API.",
        "categories": ["search", "web"],
        "endpoints": [
            {"id": "search", "method": "POST", "url": "https://api.tavily.com/search",
             "params": [{"name": "query", "type": "string", "required": True}]}
        ],
    },
    {
        "skill_id": "weather_forecast",
        "version": "1.0.0",
        "author": "theora-team",
        "brand": {"name": "Weather", "icon": "cloud-sun"},
        "description": "Get current weather and forecasts using Open-Meteo (free, no API key).",
        "categories": ["weather", "utility"],
        "endpoints": [
            {"id": "current", "method": "GET", "url": "https://api.open-meteo.com/v1/forecast",
             "params": [
                 {"name": "latitude", "type": "number", "required": True},
                 {"name": "longitude", "type": "number", "required": True},
             ]}
        ],
    },
    {
        "skill_id": "hacker_news",
        "version": "1.0.0",
        "author": "theora-team",
        "brand": {"name": "Hacker News", "icon": "newspaper"},
        "description": "Fetch top stories, new stories, and comments from Hacker News.",
        "categories": ["news", "tech"],
        "endpoints": [
            {"id": "top_stories", "method": "GET",
             "url": "https://hacker-news.firebaseio.com/v0/topstories.json", "params": []},
            {"id": "story", "method": "GET",
             "url": "https://hacker-news.firebaseio.com/v0/item/{id}.json",
             "params": [{"name": "id", "type": "integer", "required": True}]},
        ],
    },
    {
        "skill_id": "github_repos",
        "version": "1.0.0",
        "author": "theora-team",
        "brand": {"name": "GitHub", "icon": "github"},
        "description": "Search GitHub repositories, list issues, and check repo stats.",
        "categories": ["development", "github"],
        "endpoints": [
            {"id": "search", "method": "GET", "url": "https://api.github.com/search/repositories",
             "params": [{"name": "q", "type": "string", "required": True}]},
        ],
    },
    {
        "skill_id": "calculator",
        "version": "1.0.0",
        "author": "theora-team",
        "brand": {"name": "Calculator", "icon": "calculator"},
        "description": "Evaluate mathematical expressions safely using Python ast.",
        "categories": ["utility", "math"],
        "endpoints": [
            {"id": "evaluate", "method": "PYTHON", "url": "",
             "params": [{"name": "expression", "type": "string", "required": True}]},
        ],
    },
]


def seed():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS skills (
            skill_id TEXT PRIMARY KEY, version TEXT NOT NULL, author TEXT NOT NULL,
            name TEXT NOT NULL, description TEXT NOT NULL, manifest TEXT NOT NULL,
            downloads INTEGER DEFAULT 0, published_at REAL NOT NULL, updated_at REAL NOT NULL,
            checksum TEXT NOT NULL, tags TEXT DEFAULT '[]'
        )
    """)
    conn.commit()

    now = time.time()
    for skill in SEED_SKILLS:
        manifest_json = json.dumps(skill, sort_keys=True)
        checksum = hashlib.sha256(manifest_json.encode()).hexdigest()[:16]
        name = skill.get("brand", {}).get("name", skill["skill_id"])
        tags = json.dumps(skill.get("categories", []))

        conn.execute("""
            INSERT OR REPLACE INTO skills
            (skill_id, version, author, name, description, manifest, published_at, updated_at, checksum, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (skill["skill_id"], skill["version"], skill["author"], name,
              skill["description"], manifest_json, now, now, checksum, tags))

    conn.commit()
    conn.close()
    print(f"Seeded {len(SEED_SKILLS)} skills into {DB_PATH}")


if __name__ == "__main__":
    seed()
