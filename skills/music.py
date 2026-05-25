import os
from pydantic import BaseModel, Field
from core.models import SkillResult
from skills.base import BaseSkill

class MusicSkill(BaseSkill):
    name = "music"
    description = "Control Spotify playback (play, pause, next, search, recommend)."

    tool_definition = {
        "name": "music",
        "description": "Control Spotify music playback. Actions: play, pause, next, search.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["play", "pause", "next", "search"],
                    "description": "Playback action",
                },
                "query": {
                    "type": "string",
                    "description": "Song or artist name for play/search",
                },
            },
            "required": ["action"],
        },
    }

    class InputSchema(BaseModel):
        action: str = Field(description="'play', 'pause', 'next', 'search', 'recommend'")
        query: str = Field(default="", description="Search query or recommendation seed")

    async def run(self, action: str, query: str = "") -> SkillResult:
        try:
            import spotipy
            from spotipy.oauth2 import SpotifyOAuth
        except ImportError:
            return SkillResult.fail("spotipy not installed. Run: pip install spotipy")
            
        client_id = os.getenv("SPOTIFY_CLIENT_ID")
        client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
        if not client_id or not client_secret:
            return SkillResult.fail("Spotify credentials not found in .env (SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET).")

        try:
            sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri="http://localhost:8000/callback",
                scope="user-modify-playback-state user-read-playback-state"
            ))
            
            if action == "play":
                if query:
                    results = sp.search(q=query, limit=1, type='track')
                    if results['tracks']['items']:
                        track_uri = results['tracks']['items'][0]['uri']
                        sp.start_playback(uris=[track_uri])
                        return SkillResult.success(f"Playing '{results['tracks']['items'][0]['name']}'")
                    return SkillResult.fail(f"Could not find track '{query}'")
                else:
                    sp.start_playback()
                    return SkillResult.success("Playback resumed.")
            elif action == "pause":
                sp.pause_playback()
                return SkillResult.success("Playback paused.")
            elif action == "next":
                sp.next_track()
                return SkillResult.success("Skipped to next track.")
            else:
                return SkillResult.fail(f"Action '{action}' not supported.")
        except Exception as e:
            return SkillResult.fail(f"Spotify API Error: {str(e)}")
