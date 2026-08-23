from __future__ import annotations

import asyncio

import aiohttp

URL = "https://r.jina.ai/https://linux.do/raw/2045356/1"
PROXY = "http://127.0.0.1:7890"
BROWSER_HEADERS = {
    "Accept": "text/plain, text/markdown;q=0.9, */*;q=0.1",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
    ),
}


async def probe(name: str, headers: dict[str, str] | None) -> None:
    timeout = aiohttp.ClientTimeout(total=45)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(URL, proxy=PROXY, headers=headers) as response:
            body = await response.text()
            prefix = " ".join(body[:160].split())
            print(
                f"{name}|status={response.status}|"
                f"content_type={response.headers.get('Content-Type', '')}|"
                f"cf_mitigated={response.headers.get('Cf-Mitigated', '')}|"
                f"prefix={prefix}"
            )


async def main() -> None:
    await probe("default", None)
    await probe("browser", BROWSER_HEADERS)


if __name__ == "__main__":
    asyncio.run(main())
