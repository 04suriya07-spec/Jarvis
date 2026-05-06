"""Live API test — confirms actual data flows from real endpoints."""
import asyncio, sys

def sp(text: str) -> str:
    """Safe print — strip chars Windows cp1252 can't handle."""
    return text.encode('ascii', 'replace').decode()

async def main():
    print("=== LIVE API TESTS ===\n")

    # 1. Weather
    from skills.weather import WeatherSkill
    ws = WeatherSkill()
    w = await ws.run(location="Mumbai", include_aqi=True)
    if "current" in w:
        cur = w["current"]
        print(f"[WEATHER] {cur['location']}: {cur['temp']} — {cur['description']}")
        if "air_quality" in w:
            aq = w["air_quality"]
            print(f"[AIR]     AQI={aq['aqi']} ({aq['level']})")
    else:
        print(f"[WEATHER] FAIL: {w}")
    print()

    # 2. News
    from skills.news import NewsSkill
    ns = NewsSkill()
    articles = await ns.run(topic="AI technology", count=3)
    print(f"[NEWS] {len(articles)} articles fetched")
    for a in articles[:2]:
        print(f"       [{a['_source']}] {sp(a['title'][:70])}")
    print()

    # 3. Finance — stock quote
    from skills.finance import FinanceSkill
    fs = FinanceSkill()
    q = await fs.run(action="quote", symbol="MSFT")
    if "price" in q:
        print(f"[FINANCE] MSFT: ${q['price']}  {q.get('change_percent','?')}  [{q['source']}]")
    else:
        print(f"[FINANCE] FAIL: {q}")
    print()

    # 4. Music — radio search
    from skills.music import MusicSkill
    ms = MusicSkill()
    radio = await ms.run(action="radio", genre="jazz")
    stations = radio.get("stations", [])
    print(f"[MUSIC] {len(stations)} radio stations for 'jazz'")
    for s in stations[:2]:
        print(f"        {s['name']} — {s['url'][:60]}")
    print()

    # 5. Music — lyrics
    lyrics = await ms.run(action="lyrics", artist="The Beatles", song="Let It Be")
    if "lyrics" in lyrics:
        print(f"[LYRICS] '{lyrics['song']}' by {lyrics['artist']}")
        print(f"         {lyrics['lyrics'][:120]}...")
    else:
        print(f"[LYRICS] FAIL: {lyrics}")

asyncio.run(main())
