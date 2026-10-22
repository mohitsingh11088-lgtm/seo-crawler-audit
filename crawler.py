import asyncio
import csv
import gzip
import os
import xml.etree.ElementTree as ET

from collections import deque
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import aiohttp
from bs4 import BeautifulSoup


USER_AGENT = "SEOCrawlerAudit/1.0"
TIMEOUT = 20
MAX_SITEMAPS = 100
MAX_SITEMAP_BYTES = 50_000_000
MAX_PAGE_BYTES = 2_000_000


def normalize_url(url):
    try:
        parts = urlsplit(url.strip())

        if parts.scheme.lower() not in ("http", "https"):
            return None

        if not parts.hostname or parts.username or parts.password:
            return None

        scheme = parts.scheme.lower()
        host = parts.hostname.lower().rstrip(".")
        port = parts.port

        netloc = f"[{host}]" if ":" in host else host

        if port and not (
            (scheme == "http" and port == 80)
            or (scheme == "https" and port == 443)
        ):
            netloc = f"{netloc}:{port}"

        return urlunsplit((
            scheme,
            netloc,
            parts.path or "/",
            parts.query,
            "",
        ))

    except (ValueError, AttributeError):
        return None


def in_scope(url, root_host, include_subdomains=False):
    try:
        host = (urlsplit(url).hostname or "").lower().rstrip(".")
        root_host = root_host.lower().rstrip(".")

        host_base = host[4:] if host.startswith("www.") else host
        root_base = (
            root_host[4:]
            if root_host.startswith("www.")
            else root_host
        )

        if host_base == root_base:
            return True

        return (
            include_subdomains
            and host.endswith("." + root_base)
        )

    except (ValueError, AttributeError):
        return False


def extract_anchor(tag):
    text = tag.get_text(" ", strip=True)

    if text:
        return " ".join(text.split())

    return " ".join(
        img.get("alt", "").strip()
        for img in tag.find_all("img")
        if img.get("alt", "").strip()
    )


def write_csv(path, rows, columns):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=columns,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)

async def discover_sitemap(
    session,
    sitemap_url,
    root_host,
    include_subdomains=False,
):
    found = set()
    pending = deque([sitemap_url])
    visited = set()

    while pending and len(visited) < MAX_SITEMAPS:
        current = pending.popleft()

        if current in visited:
            continue

        visited.add(current)

        try:
            async with session.get(
                current,
                allow_redirects=True,
            ) as response:
                print(
                    f"[SITEMAP] {current} | "
                    f"HTTP {response.status} | "
                    f"Type: {response.headers.get('Content-Type', '')}"
                )

                if response.status >= 400:
                    print(
                        f"[SITEMAP ERROR] HTTP "
                        f"{response.status}: {current}"
                    )
                    continue

                content = await response.content.read(
                    MAX_SITEMAP_BYTES + 1
                )

            if len(content) > MAX_SITEMAP_BYTES:
                print(
                    f"[SITEMAP ERROR] File too large: {current}"
                )
                continue

            if (
                current.lower().endswith(".gz")
                or content.startswith(b"\x1f\x8b")
            ):
                content = gzip.decompress(content)

                if len(content) > MAX_SITEMAP_BYTES:
                    print(
                        f"[SITEMAP ERROR] Decompressed file too large: "
                        f"{current}"
                    )
                    continue

            root = ET.fromstring(content)
            root_kind = root.tag.split("}")[-1]

            print(f"[SITEMAP ROOT] {current} -> {root_kind}")

            if root_kind not in ("urlset", "sitemapindex"):
                print(
                    f"[SITEMAP ERROR] Unexpected XML root: {root_kind}"
                )
                continue

            expected_kind = (
                "url" if root_kind == "urlset" else "sitemap"
            )

            for entry in root:
                if entry.tag.split("}")[-1] != expected_kind:
                    continue

                loc = next(
                    (
                        element.text
                        for element in entry
                        if element.tag.split("}")[-1] == "loc"
                    ),
                    None,
                )

                url = normalize_url(loc or "")

                if not url:
                    continue

                if root_kind == "sitemapindex":
                    if url not in visited and url not in pending:
                        pending.append(url)

                elif in_scope(
                    url,
                    root_host,
                    include_subdomains,
                ):
                    found.add(url)

            print(
                f"[SITEMAP PROGRESS] URLs found: {len(found)} | "
                f"Sitemaps pending: {len(pending)}"
            )

        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            ET.ParseError,
            ValueError,
            OSError,
        ) as exc:
            print(f"[SITEMAP ERROR] {current}: {exc}")

    if pending:
        print(
            f"[SITEMAP WARNING] Sitemap limit "
            f"({MAX_SITEMAPS}) reached."
        )

    print(f"[SITEMAP COMPLETE] Total URLs: {len(found)}")

    return found


async def fetch(session, url):
    try:
        async with session.get(
            url,
            allow_redirects=True,
        ) as response:
            body = await response.content.read(MAX_PAGE_BYTES)

            content_type = response.headers.get("Content-Type", "")
            charset = response.charset or "utf-8"

            is_html = (
                "text/html" in content_type.lower()
                or "application/xhtml+xml" in content_type.lower()
            )

            return {
                "status": response.status,
                "final_url": str(response.url),
                "content_type": content_type,
                "history": [
                    {
                        "url": str(hop.url),
                        "status": hop.status,
                        "location": hop.headers.get("Location", ""),
                    }
                    for hop in response.history
                ],
                "text": (
                    body.decode(charset, errors="replace")
                    if is_html and response.status < 400
                    else ""
                ),
                "error": "",
            }

    except (
        aiohttp.ClientError,
        asyncio.TimeoutError,
        UnicodeError,
        ValueError,
    ) as exc:
        return {
            "status": "",
            "final_url": "",
            "content_type": "",
            "history": [],
            "text": "",
            "error": str(exc),
        }

async def crawl_website(
    start_url,
    output_dir="reports",
    max_urls=10000,
    concurrency=10,
    delay=0.1,
    include_subdomains=False,
    use_sitemap=True,
    respect_robots=True,
    progress_callback=None,
):
    start_url = normalize_url(start_url)

    if not start_url:
        raise ValueError("Enter a valid HTTP or HTTPS URL.")

    if max_urls < 1 or concurrency < 1:
        raise ValueError("Limits must be positive.")

    if delay < 0:
        raise ValueError("Delay cannot be negative.")

    root_host = (urlsplit(start_url).hostname or "").lower()

    os.makedirs(output_dir, exist_ok=True)

    timeout = aiohttp.ClientTimeout(total=TIMEOUT)
    connector = aiohttp.TCPConnector(
        limit=concurrency,
        limit_per_host=concurrency,
    )

    pages = []
    links = []
    redirects = []
    errors = []
    checked = {}

    async with aiohttp.ClientSession(
        timeout=timeout,
        connector=connector,
        headers={"User-Agent": USER_AGENT},
    ) as session:

        # Read robots.txt.
        robot_parser = None

        if respect_robots:
            try:
                robots_url = urljoin(start_url, "/robots.txt")

                async with session.get(robots_url) as response:
                    if response.status < 400:
                        robot_parser = RobotFileParser()
                        robot_parser.set_url(robots_url)
                        robot_parser.parse(
                            (await response.text()).splitlines()
                        )
                        print("[ROBOTS] robots.txt loaded.")
                    else:
                        print(
                            f"[ROBOTS] HTTP {response.status}; "
                            "rules could not be loaded."
                        )

            except (
                aiohttp.ClientError,
                asyncio.TimeoutError,
                UnicodeError,
            ) as exc:
                print(f"[ROBOTS] Could not read robots.txt: {exc}")

        # Discover sitemap URLs.
        discovered = {start_url}

        sitemap_candidates = [
            urljoin(start_url, "/sitemap.xml"),
            urljoin(start_url, "/sitemap_index.xml"),
            urljoin(start_url, "/sitemap-index.xml"),
            urljoin(start_url, "/wp-sitemap.xml"),
        ]

        if use_sitemap:
            declared_sitemaps = (
                robot_parser.site_maps()
                if robot_parser
                else None
            ) or []

            sitemap_candidates = list(dict.fromkeys(
                declared_sitemaps + sitemap_candidates
            ))

            for sitemap in sitemap_candidates:
                discovered.update(
                    await discover_sitemap(
                        session,
                        sitemap,
                        root_host,
                        include_subdomains,
                    )
                )

        queue = deque(sorted(discovered)[:max_urls])
        scheduled = set(queue)

        print(f"[CRAWL START] Initial URLs: {len(queue)}")

        semaphore = asyncio.Semaphore(concurrency)

        async def process(url):
            async with semaphore:
                if (
                    robot_parser
                    and respect_robots
                    and not robot_parser.can_fetch(USER_AGENT, url)
                ):
                    return url, None

                result = await fetch(session, url)

                if delay:
                    await asyncio.sleep(delay)

                return url, result

        # Crawl pages and discover internal links.
        while queue and len(checked) < max_urls:
            batch = []

            while queue and len(batch) < concurrency:
                url = queue.popleft()

                if url not in checked:
                    batch.append(url)

            if not batch:
                continue

            results = await asyncio.gather(
                *(process(url) for url in batch)
            )

            for url, result in results:
                if result is None:
                    checked[url] = {
                        "status": "",
                        "final_url": "",
                        "content_type": "",
                        "history": [],
                        "text": "",
                        "error": "Blocked by robots.txt",
                    }
                    print(f"[ROBOTS BLOCKED] {url}")
                    continue

                checked[url] = result

                print(
                    f"[PAGE] {len(checked)}/{max_urls} "
                    f"HTTP {result['status']} {url}"
                )

                for hop in result["history"]:
                    redirects.append({
                        "requested_url": url,
                        "redirect_url": hop["url"],
                        "status_code": hop["status"],
                        "location": hop["location"],
                        "final_url": result["final_url"],
                        "redirect_hops": len(result["history"]),
                    })

                if result["error"]:
                    errors.append({
                        "url": url,
                        "status_code": "",
                        "error": result["error"],
                    })

                soup = (
                    BeautifulSoup(result["text"], "html.parser")
                    if result["text"]
                    else None
                )

                title = (
                    soup.title.get_text(" ", strip=True)
                    if soup and soup.title
                    else ""
                )

                h1_tag = soup.find("h1") if soup else None

                h1 = (
                    h1_tag.get_text(" ", strip=True)
                    if h1_tag
                    else ""
                )

                meta = (
                    soup.find(
                        "meta",
                        attrs={"name": "description"},
                    )
                    if soup
                    else None
                )

                canonical_tag = (
                    soup.find("link", rel="canonical")
                    if soup
                    else None
                )

                canonical = ""

                if canonical_tag and canonical_tag.get("href"):
                    canonical = normalize_url(
                        urljoin(
                            result["final_url"],
                            canonical_tag["href"],
                        )
                    ) or ""

                pages.append({
                    "url": url,
                    "status_code": result["status"],
                    "final_url": result["final_url"],
                    "title": title,
                    "h1": h1,
                    "meta_description": (
                        meta.get("content", "") if meta else ""
                    ),
                    "canonical": canonical,
                    "error": result["error"],
                })

                if soup:
                    for tag in soup.find_all("a", href=True):
                        target = normalize_url(
                            urljoin(
                                result["final_url"],
                                tag["href"].strip(),
                            )
                        )

                        if not target or not in_scope(
                            target,
                            root_host,
                            include_subdomains,
                        ):
                            continue

                        links.append({
                            "source_url": url,
                            "anchor_text": extract_anchor(tag),
                            "target_url": target,
                        })

                        if (
                            target not in scheduled
                            and len(scheduled) < max_urls
                        ):
                            scheduled.add(target)
                            queue.append(target)

            if progress_callback and batch:
                progress_callback(
                    min(len(checked), max_urls),
                    max_urls,
                    batch[-1],
                )

        # Check linked URLs not fetched in the main crawl.
        targets = sorted({
            link["target_url"]
            for link in links
            if link["target_url"] not in checked
        })

        print(f"[LINK CHECK] Additional targets: {len(targets)}")

        for offset in range(0, len(targets), concurrency):
            batch = targets[offset:offset + concurrency]

            results = await asyncio.gather(
                *(fetch(session, target) for target in batch)
            )

            for target, result in zip(batch, results):
                checked[target] = result

                for hop in result["history"]:
                    redirects.append({
                        "requested_url": target,
                        "redirect_url": hop["url"],
                        "status_code": hop["status"],
                        "location": hop["location"],
                        "final_url": result["final_url"],
                        "redirect_hops": len(result["history"]),
                    })

                if result["error"]:
                    errors.append({
                        "url": target,
                        "status_code": "",
                        "error": result["error"],
                    })

            if delay:
                await asyncio.sleep(delay)

    # Classify internal links.
    broken_links = []

    for link in links:
        result = checked.get(link["target_url"])

        if not result:
            continue

        status = result["status"]
        issue = ""

        if result["error"]:
            issue = "Request error"
        elif status == 404:
            issue = "404 Not Found"
        elif isinstance(status, int) and status >= 400:
            issue = f"HTTP {status}"
        elif result["history"]:
            issue = "Redirected internal link"

        if issue:
            broken_links.append({
                "source_url": link["source_url"],
                "anchor_text": link["anchor_text"],
                "original_url": link["target_url"],
                "status_code": status,
                "final_url": result["final_url"],
                "issue": issue,
                "error": result["error"],
            })

    # Export CSV reports.
    reports = {
        "pages.csv": (
            pages,
            [
                "url",
                "status_code",
                "final_url",
                "title",
                "h1",
                "meta_description",
                "canonical",
                "error",
            ],
        ),
        "redirects.csv": (
            redirects,
            [
                "requested_url",
                "redirect_url",
                "status_code",
                "location",
                "final_url",
                "redirect_hops",
            ],
        ),
        "broken_links.csv": (
            broken_links,
            [
                "source_url",
                "anchor_text",
                "original_url",
                "status_code",
                "final_url",
                "issue",
                "error",
            ],
        ),
        "all_internal_links.csv": (
            links,
            [
                "source_url",
                "anchor_text",
                "target_url",
            ],
        ),
        "request_errors.csv": (
            errors,
            [
                "url",
                "status_code",
                "error",
            ],
        ),
    }

    for filename, (rows, columns) in reports.items():
        write_csv(
            os.path.join(output_dir, filename),
            rows,
            columns,
        )

    print("\n[CRAWL COMPLETE]")
    print(f"Pages processed: {len(pages)}")
    print(f"Internal links found: {len(links)}")
    print(f"Redirects found: {len(redirects)}")
    print(f"Broken links found: {len(broken_links)}")
    print(f"Request errors: {len(errors)}")
    print(f"Checked URLs: {len(checked)}")
    print(f"Reports saved to: {output_dir}")

    return {
        "pages": pages,
        "links": links,
        "redirects": redirects,
        "broken_links": broken_links,
        "errors": errors,
        "checked_urls": len(checked),
        "output_dir": output_dir,
    }


if __name__ == "__main__":
    asyncio.run(
        crawl_website(
            start_url="https://www.flyingvgroup.com/",
            output_dir="reports",
            max_urls=10000,
            concurrency=5,
            delay=0.5,
            include_subdomains=False,
            use_sitemap=True,
            respect_robots=True,
        )
    )
