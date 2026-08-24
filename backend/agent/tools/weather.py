"""天气查询工具。"""
from __future__ import annotations

import httpx
from langchain_core.tools import tool

# Open-Meteo 使用的 WMO 天气代码
WMO_WEATHER = {
    0: "晴",
    1: "大部晴朗",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "中毛毛雨",
    55: "大毛毛雨",
    56: "冻毛毛雨",
    57: "强冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "雪粒",
    80: "小阵雨",
    81: "中阵雨",
    82: "大阵雨",
    85: "小阵雪",
    86: "大阵雪",
    95: "雷暴",
    96: "雷暴伴小冰雹",
    99: "雷暴伴大冰雹",
}


@tool
def get_weather(city: str) -> str:
    """查询指定城市的当前天气。用户问天气、气温、是否下雨时必须调用本工具，不要凭记忆编造。

    Args:
        city: 城市名称，中文或英文均可，例如「北京」「Shanghai」。
    """
    with httpx.Client(timeout=15.0) as client:
        geo_resp = client.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "zh"},
        )
        geo_resp.raise_for_status()
        results = geo_resp.json().get("results")
        if not results:
            return f"未找到城市「{city}」，请提供更准确的城市名。"

        loc = results[0]
        weather_resp = client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": loc["latitude"],
                "longitude": loc["longitude"],
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
                "timezone": "auto",
            },
        )
        weather_resp.raise_for_status()
        current = weather_resp.json()["current"]

    place = " ".join(
        part for part in (loc.get("name"), loc.get("admin1"), loc.get("country")) if part
    )
    code = current["weather_code"]
    desc = WMO_WEATHER[code]
    return (
        f"地点: {place}\n"
        f"观测时间: {current['time']}\n"
        f"天气: {desc}\n"
        f"气温: {current['temperature_2m']}°C（体感 {current['apparent_temperature']}°C）\n"
        f"相对湿度: {current['relative_humidity_2m']}%\n"
        f"风速: {current['wind_speed_10m']} km/h"
    )
