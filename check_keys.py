from core.config import get_config
cfg = get_config()
print("=== API KEY STATUS ===")
ok = lambda k: "OK" if k else "MISSING"
trunc = lambda k, n=12: (k[:n] + "...") if len(k) > n else k
print(f"Weather (OWM):       {ok(cfg.weather_api_key):8s} {trunc(cfg.weather_api_key)}")
print(f"Air Quality (AQICN): {ok(cfg.aqicn_api_key):8s} {trunc(cfg.aqicn_api_key)}")
print(f"News (GNews):        {ok(cfg.gnews_api_key):8s} {trunc(cfg.gnews_api_key)}")
print(f"News (MarketAux):    {ok(cfg.marketaux_api_key):8s} {trunc(cfg.marketaux_api_key)}")
print(f"News (NewsData):     {ok(cfg.newsdata_api_key):8s} {trunc(cfg.newsdata_api_key)}")
print(f"Finance (AV):        {ok(cfg.alpha_vantage_api_key):8s} {trunc(cfg.alpha_vantage_api_key)}")
print(f"Finance (Finnhub):   {ok(cfg.finnhub_api_key):8s} {trunc(cfg.finnhub_api_key)}")
print(f"Finance (FMP):       {ok(cfg.fmp_api_key):8s} {trunc(cfg.fmp_api_key)}")
print(f"Search  (SerpAPI):   {ok(cfg.serpapi_key):8s} {trunc(cfg.serpapi_key)}")
print(f"Music   (TasteDive): {ok(cfg.tastedive_api_key):8s} {trunc(cfg.tastedive_api_key)}")
print(f"Mail    (Disify):    {ok(cfg.disify_api_key):8s} {trunc(cfg.disify_api_key)}")
print()

from skills.finance import FinanceSkill
from skills.music import MusicSkill
from skills.weather import WeatherSkill
from skills.news import NewsSkill
print("=== SKILL IMPORTS ===")
print(f"WeatherSkill:  OK  name={WeatherSkill.name!r}  aliases={WeatherSkill.aliases}")
print(f"NewsSkill:     OK  name={NewsSkill.name!r}")
print(f"FinanceSkill:  OK  name={FinanceSkill.name!r}  aliases={FinanceSkill.aliases}")
print(f"MusicSkill:    OK  name={MusicSkill.name!r}    aliases={MusicSkill.aliases}")
