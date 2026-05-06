"""
Javris Music Skill — Multi-Source
──────────────────────────────────
Flow:
  User: "Play Eminem" or "Find jazz radio"
  1. MusicBrainz → artist/track metadata (free)
  2. TasteDive   → similar artists & recommendations
  3. Last.fm     → (no key needed, free tier) top tracks
  4. LRCLIB      → lyrics fetch
  5. Radio Browser → find live radio streams

All read-only — Javris reports what's available, then
the system-control skill can open the stream in VLC/browser.
"""

from __future__ import annotations

import asyncio
import urllib.parse

import httpx

from skills.base import BaseSkill
from core.config import get_config
from core.logger import get_logger
from core.retry import resilient, with_retry, cached

logger = get_logger("javris.skill.music")
cfg = get_config()

LASTFM_API = "https://ws.audioscrobbler.com/2.0/"


class MusicSkill(BaseSkill):
    name = "music"
    aliases = ["play_music", "find_music"]
    description = "Find music, radio stations, lyrics, and artist recommendations"

    tool_definition = {
        "name": "music",
        "description": (
            "Find music recommendations, radio streams, lyrics, and artist info. "
            "Can search radio stations and return playable stream URLs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["search", "artist", "lyrics", "radio", "recommend", "top_tracks"],
                    "description": "What to look up",
                    "default": "search",
                },
                "query": {
                    "type": "string",
                    "description": "Artist, song, or genre to search for",
                },
                "artist": {
                    "type": "string",
                    "description": "Artist name for lyrics/top-tracks lookup",
                },
                "song": {
                    "type": "string",
                    "description": "Song title for lyrics lookup",
                },
                "genre": {
                    "type": "string",
                    "description": "Genre for radio station search (e.g. jazz, rock, lofi)",
                },
            },
            "required": [],
        },
    }

    @resilient(ttl=1800, max_retries=2, base_delay=1.0)
    async def run(
        self,
        action: str = "search",
        query: str = "",
        artist: str = "",
        song: str = "",
        genre: str = "",
        **_,
    ) -> dict:
        if action == "search":
            return await self._search(query or artist or genre)
        elif action == "artist":
            return await self._artist_info(artist or query)
        elif action == "lyrics":
            return await self._lyrics(artist or query, song)
        elif action == "radio":
            return await self._radio(genre or query)
        elif action == "recommend":
            return await self._recommend(artist or query)
        elif action == "top_tracks":
            return await self._top_tracks(artist or query)
        else:
            return {"error": f"Unknown action: {action}"}

    # ── MusicBrainz search ──────────────────────────────────────

    @with_retry(max_retries=2, base_delay=1.0)
    async def _search(self, query: str) -> dict:
        if not query:
            return {"error": "Query required"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{cfg.musicbrainz_base_url}/artist/",
                    params={"query": query, "fmt": "json", "limit": 5},
                    headers={"User-Agent": "Javris/3.0 (contact@javris.ai)"},
                )
                if r.status_code == 200:
                    artists = r.json().get("artists", [])
                    results = []
                    for a in artists:
                        results.append({
                            "name":        a.get("name", ""),
                            "type":        a.get("type", ""),
                            "country":     a.get("country", ""),
                            "tags":        [t["name"] for t in a.get("tags", [])[:5]],
                            "score":       a.get("score", 0),
                            "mbid":        a.get("id", ""),
                        })
                    return {"query": query, "artists": results}
        except Exception as e:
            logger.debug(f"MusicBrainz search error: {e}")
        return {"error": f"No results for '{query}'"}

    # ── Artist info + top tracks via Last.fm ────────────────────

    @with_retry(max_retries=2, base_delay=1.0)
    async def _artist_info(self, artist: str) -> dict:
        if not artist:
            return {"error": "Artist name required"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                # Last.fm artist info (no key for basic info)
                r = await client.get(
                    LASTFM_API,
                    params={"method": "artist.getinfo", "artist": artist,
                            "format": "json", "autocorrect": 1},
                )
                if r.status_code == 200:
                    a = r.json().get("artist", {})
                    if a:
                        return {
                            "name":       a.get("name", artist),
                            "bio":        a.get("bio", {}).get("summary", "")[:500],
                            "listeners":  a.get("stats", {}).get("listeners", 0),
                            "playcount":  a.get("stats", {}).get("playcount", 0),
                            "tags":       [t["name"] for t in a.get("tags", {}).get("tag", [])[:5]],
                            "similar":    [s["name"] for s in a.get("similar", {}).get("artist", [])[:5]],
                            "url":        a.get("url", ""),
                            "source":     "Last.fm",
                        }
        except Exception as e:
            logger.debug(f"Last.fm artist info error: {e}")
        return {"error": f"No info for '{artist}'"}

    # ── Top tracks ───────────────────────────────────────────────

    @with_retry(max_retries=2, base_delay=1.0)
    async def _top_tracks(self, artist: str) -> dict:
        if not artist:
            return {"error": "Artist name required"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    LASTFM_API,
                    params={"method": "artist.gettoptracks", "artist": artist,
                            "format": "json", "autocorrect": 1, "limit": 10},
                )
                if r.status_code == 200:
                    tracks = r.json().get("toptracks", {}).get("track", [])
                    return {
                        "artist": artist,
                        "tracks": [
                            {"name": t["name"], "playcount": t.get("playcount", 0),
                             "url": t.get("url", "")}
                            for t in tracks
                        ],
                        "source": "Last.fm",
                    }
        except Exception as e:
            logger.debug(f"Last.fm top tracks error: {e}")
        return {"error": f"No tracks for '{artist}'"}

    # ── Lyrics via LRCLIB ────────────────────────────────────────

    @with_retry(max_retries=2, base_delay=1.0)
    async def _lyrics(self, artist: str, song: str) -> dict:
        if not song:
            return {"error": "Song title required for lyrics"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{cfg.lrclib_base_url}/get",
                    params={"artist_name": artist, "track_name": song},
                )
                if r.status_code == 200:
                    d = r.json()
                    return {
                        "artist":  d.get("artistName", artist),
                        "song":    d.get("trackName", song),
                        "album":   d.get("albumName", ""),
                        "lyrics":  d.get("plainLyrics", "")[:2000],
                        "synced":  bool(d.get("syncedLyrics")),
                        "source":  "LRCLIB",
                    }
                elif r.status_code == 404:
                    return {"error": f"Lyrics not found for '{song}' by {artist or 'unknown'}"}
        except Exception as e:
            logger.debug(f"Lyrics error: {e}")
        return {"error": f"Could not fetch lyrics for '{song}'"}

    # ── Radio Browser ────────────────────────────────────────────

    @with_retry(max_retries=2, base_delay=1.0)
    async def _radio(self, query: str) -> dict:
        if not query:
            return {"error": "Genre or name required for radio search"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{cfg.radio_browser_base_url}/stations/search",
                    params={
                        "name": query, "limit": 8, "order": "votes",
                        "reverse": True, "hidebroken": True,
                    },
                    headers={"User-Agent": "Javris/3.0"},
                )
                if r.status_code == 200:
                    stations = r.json()
                    return {
                        "query":    query,
                        "stations": [
                            {
                                "name":     s.get("name", ""),
                                "genre":    s.get("tags", ""),
                                "country":  s.get("country", ""),
                                "bitrate":  s.get("bitrate", 0),
                                "codec":    s.get("codec", ""),
                                "url":      s.get("url_resolved", s.get("url", "")),
                                "votes":    s.get("votes", 0),
                            }
                            for s in stations
                        ],
                        "source": "RadioBrowser",
                    }
        except Exception as e:
            logger.debug(f"Radio search error: {e}")
        return {"error": f"No radio stations found for '{query}'"}

    # ── TasteDive recommendations ────────────────────────────────

    @with_retry(max_retries=2, base_delay=1.0)
    async def _recommend(self, query: str) -> dict:
        if not query:
            return {"error": "Artist or song name required"}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    "https://tastedive.com/api/similar",
                    params={
                        "q": query, "type": "music", "limit": 8,
                        "k": cfg.tastedive_api_key, "info": 1,
                    },
                )
                if r.status_code == 200:
                    data = r.json().get("similar", {})
                    results = data.get("results", [])
                    return {
                        "query":   query,
                        "similar": [
                            {
                                "name":        r_item.get("name", ""),
                                "type":        r_item.get("type", ""),
                                "description": r_item.get("wTeaser", "")[:200],
                                "youtube":     r_item.get("yUrl", ""),
                            }
                            for r_item in results
                        ],
                        "source": "TasteDive",
                    }
        except Exception as e:
            logger.debug(f"TasteDive error: {e}")
        return {"error": f"No recommendations for '{query}'"}
