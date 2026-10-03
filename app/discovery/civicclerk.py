import asyncio
import re
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright
from sqlalchemy.dialects.postgresql import insert

from app.config import settings
from app.database import SessionLocal
from app.models import Document


DOCUMENT_EXTENSIONS = (
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"
)


def canonical_event_url(base_url: str, href: str) -> str | None:
    full = urljoin(base_url, href)
    match = re.search(r"/event/(\d+)", full)
    if not match:
        return None
    return f"{base_url.rstrip('/')}/event/{match.group(1)}"


def guess_document_type(text: str, url: str) -> str:
    value = f"{text} {url}".lower()
    if "agenda packet" in value or "packet" in value:
        return "AGENDA_PACKET"
    if "agenda" in value:
        return "AGENDA"
    if "minute" in value:
        return "MINUTES"
    if "attachment" in value:
        return "ATTACHMENT"
    return "DOCUMENT"


def save_document(*, title: str, source_url: str, document_type: str) -> bool:
    """Insert only if source_url has not already been discovered."""
    with SessionLocal() as db:
        stmt = (
            insert(Document)
            .values(
                organization="City of Post Falls",
                title=title[:2000] if title else None,
                document_type=document_type,
                source_url=source_url,
                status="PENDING",
            )
            .on_conflict_do_nothing(index_elements=["source_url"])
            .returning(Document.id)
        )
        inserted = db.execute(stmt).scalar_one_or_none()
        db.commit()
        return inserted is not None


async def collect_event_urls(page, max_events: int) -> list[str]:
    base_url = settings.target_base_url.rstrip("/")
    await page.goto(f"{base_url}/search", wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(3500)

    discovered: set[str] = set()

    # CivicClerk is a JS app. Collect event links while nudging dynamic/scrollable
    # event containers so more meeting records can render.
    for _ in range(20):
        anchors = page.locator('a[href*="/event/"]')
        count = await anchors.count()

        for i in range(count):
            href = await anchors.nth(i).get_attribute("href")
            if not href:
                continue
            event_url = canonical_event_url(base_url, href)
            if event_url:
                discovered.add(event_url)
            if len(discovered) >= max_events:
                return sorted(discovered)[:max_events]

        # Scroll any substantial scrollable containers and the page itself.
        await page.evaluate("""
        () => {
          const candidates = [...document.querySelectorAll('*')].filter(el => {
            const s = getComputedStyle(el);
            return (s.overflowY === 'auto' || s.overflowY === 'scroll')
              && el.scrollHeight > el.clientHeight + 200;
          });
          for (const el of candidates.slice(0, 5)) {
            el.scrollTop = Math.max(0, el.scrollTop - Math.max(500, el.clientHeight));
          }
          window.scrollBy(0, 900);
        }
        """)
        await page.wait_for_timeout(1200)

    return sorted(discovered)[:max_events]


async def collect_documents_from_event(context, event_url: str) -> list[dict]:
    page = await context.new_page()
    captured_network_docs: set[str] = set()

    async def capture_response(response):
        try:
            content_type = (response.headers.get("content-type") or "").lower()
            url = response.url
            if (
                "application/pdf" in content_type
                or "application/msword" in content_type
                or "officedocument" in content_type
                or urlparse(url).path.lower().endswith(DOCUMENT_EXTENSIONS)
            ):
                captured_network_docs.add(url)
        except Exception:
            pass

    page.on("response", capture_response)

    try:
        await page.goto(event_url, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(2500)

        # Open Meeting Files if the tab/button is present.
        meeting_files = page.get_by_text("Meeting Files", exact=True)
        if await meeting_files.count():
            try:
                await meeting_files.first.click(timeout=5000)
                await page.wait_for_timeout(1800)
            except Exception:
                pass

        event_title = (await page.title()) or event_url
        docs: dict[str, dict] = {}

        # Viewer/file routes and direct downloadable file links.
        anchors = page.locator("a[href]")
        count = await anchors.count()

        for i in range(count):
            anchor = anchors.nth(i)
            href = await anchor.get_attribute("href")
            if not href:
                continue

            full = urljoin(event_url, href)
            text = (await anchor.inner_text()).strip()

            path = urlparse(full).path.lower()
            is_doc = (
                "/files/" in path
                or path.endswith(DOCUMENT_EXTENSIONS)
                or any(word in text.lower() for word in ("agenda", "packet", "minutes", "attachment"))
            )

            if not is_doc:
                continue

            # Avoid treating the event root itself as a document.
            if re.fullmatch(r".*/event/\d+/?", full):
                continue

            docs[full] = {
                "title": text or event_title,
                "source_url": full,
                "document_type": guess_document_type(text, full),
            }

        # Some JS viewers request the actual PDF via XHR/fetch rather than expose
        # it as an <a>. Capture those network URLs too.
        for url in captured_network_docs:
            docs[url] = {
                "title": event_title,
                "source_url": url,
                "document_type": guess_document_type(event_title, url),
            }

        return list(docs.values())

    finally:
        await page.close()


async def discover(max_events: int = 5):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "LargeDocumentScraperDemo/1.0 "
                "(responsible public-record discovery; low request rate)"
            )
        )
        listing_page = await context.new_page()

        try:
            event_urls = await collect_event_urls(listing_page, max_events=max_events)
            print(f"Found {len(event_urls)} event(s).")

            total_found = 0
            total_inserted = 0

            for number, event_url in enumerate(event_urls, start=1):
                print(f"[{number}/{len(event_urls)}] {event_url}")
                docs = await collect_documents_from_event(context, event_url)
                total_found += len(docs)

                for doc in docs:
                    if save_document(**doc):
                        total_inserted += 1

                # Be intentionally gentle with the public portal.
                await asyncio.sleep(1.0)

            print(f"Document links found: {total_found}")
            print(f"New rows inserted into Neon: {total_inserted}")

        finally:
            await listing_page.close()
            await context.close()
            await browser.close()
