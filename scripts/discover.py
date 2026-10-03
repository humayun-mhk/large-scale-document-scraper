import argparse
import asyncio
from urllib.parse import urljoin

import httpx
from playwright.async_api import (
    async_playwright,
    TimeoutError as PlaywrightTimeoutError,
    Error as PlaywrightError,
)
from sqlalchemy.dialects.postgresql import insert

from app.database import SessionLocal
from app.models import Document


def classify(title, url):
    value = f"{title} {url}".lower()

    if "package" in value or "packet" in value:
        return "AGENDA_PACKAGE"
    if "minute" in value:
        return "MINUTES"
    if "agenda" in value:
        return "AGENDA"
    return "ATTACHMENT"


def save_document(organization, title, source_url, doc_type):
    with SessionLocal() as db:
        stmt = (
            insert(Document)
            .values(
                organization=organization,
                title=title or "CivicWeb document",
                document_type=doc_type,
                source_url=source_url,
                status="PENDING",
            )
            .on_conflict_do_nothing(index_elements=["source_url"])
            .returning(Document.id)
        )

        row_id = db.execute(stmt).scalar_one_or_none()
        db.commit()
        return row_id is not None


def get_meetings(host, from_date, to_date):
    url = f"{host.rstrip('/')}/Services/MeetingsService.svc/meetings"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/154 Safari/537.36"
        ),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": f"{host.rstrip('/')}/Portal/MeetingSchedule.aspx",
        "X-Requested-With": "XMLHttpRequest",
    }

    params = {
        "from": from_date,
        "to": to_date,
    }

    with httpx.Client(
        timeout=60,
        follow_redirects=True,
        headers=headers,
    ) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

    if not isinstance(data, list):
        raise RuntimeError(
            f"Unexpected meetings response type: {type(data).__name__}"
        )

    return data


async def safe_goto(page, url, retries=4):
    for attempt in range(1, retries + 1):
        try:
            response = await page.goto(
                url,
                wait_until="commit",
                timeout=30_000,
            )

            try:
                await page.wait_for_load_state(
                    "domcontentloaded",
                    timeout=15_000,
                )
            except PlaywrightTimeoutError:
                print("    DOMContentLoaded slow; continuing")

            await page.wait_for_timeout(1800)
            return response

        except (PlaywrightTimeoutError, PlaywrightError) as exc:
            print(
                f"    navigation error "
                f"({attempt}/{retries}): {exc}"
            )

            if attempt == retries:
                raise

            await page.wait_for_timeout(attempt * 3500)


async def extract_documents(page):
    found = {}

    anchors = page.locator('a[href*="/document/"]')

    for i in range(await anchors.count()):
        a = anchors.nth(i)

        href = await a.get_attribute("href")
        if not href:
            continue

        try:
            title = " ".join((await a.inner_text()).split())
        except Exception:
            title = ""

        full_url = urljoin(page.url, href)
        lower_url = full_url.lower()

        # UI viewer link, not a distinct document.
        if "splitscreen=true" in lower_url:
            continue

        # Avoid empty miscellaneous links unless it is clearly a PDF endpoint.
        if not title and "printpdf=true" not in lower_url:
            continue

        found[full_url] = title or "CivicWeb document"

    return list(found.items())


async def main(
    host,
    organization,
    from_date,
    to_date,
    target_docs,
):
    print("Fetching meeting index from CivicWeb service...")

    meetings = get_meetings(
        host,
        from_date,
        to_date,
    )

    print("Meetings returned:", len(meetings))

    published = [
        m for m in meetings
        if m.get("Published") is True and m.get("Id")
    ]

    # Oldest-first gives us historical coverage instead of
    # repeatedly revisiting the newest meetings already in Neon.
    published.sort(
        key=lambda m: (
            m.get("MeetingDate") or "",
            int(m.get("Id") or 0),
        )
    )

    print("Published meetings:", len(published))
    print(
        "Date span:",
        published[0].get("MeetingDate") if published else "n/a",
        "→",
        published[-1].get("MeetingDate") if published else "n/a",
    )

    inserted = 0
    visited = 0
    failed = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)

        page = await browser.new_page(
            viewport={"width": 1440, "height": 1000}
        )

        for meeting in published:
            if inserted >= target_docs:
                break

            meeting_id = meeting["Id"]
            meeting_name = meeting.get("Name") or f"Meeting {meeting_id}"
            meeting_date = meeting.get("MeetingDate") or ""

            meeting_url = (
                f"{host.rstrip('/')}"
                f"/Portal/MeetingInformation.aspx?Id={meeting_id}"
            )

            visited += 1

            print(
                f"\n[{visited}/{len(published)}] "
                f"new docs {inserted}/{target_docs}"
            )
            print(
                f"  {meeting_date} | {meeting_name}"
            )
            print(
                f"  {meeting_url}"
            )

            try:
                await safe_goto(page, meeting_url)
            except Exception as exc:
                failed += 1
                print(f"  FAILED after retries: {exc}")
                continue

            docs = await extract_documents(page)

            print("  usable document links:", len(docs))

            for source_url, title in docs:
                doc_type = classify(title, source_url)

                if save_document(
                    organization,
                    title,
                    source_url,
                    doc_type,
                ):
                    inserted += 1
                    print(
                        f"    + {inserted:04d}/{target_docs} "
                        f"{doc_type:15} {title[:60]}"
                    )

                if inserted >= target_docs:
                    break

            # Polite delay between rendered meeting pages.
            await asyncio.sleep(0.7)

        await browser.close()

    print("\n====================================")
    print("CivicWeb service discovery complete")
    print("Organization:", organization)
    print("Meetings returned:", len(meetings))
    print("Published meetings:", len(published))
    print("Meetings visited:", visited)
    print("Meeting-page failures:", failed)
    print("New documents inserted:", inserted)
    print("Target:", target_docs)
    print("====================================")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--host",
        required=True,
    )

    parser.add_argument(
        "--organization",
        required=True,
    )

    parser.add_argument(
        "--from-date",
        default="2015-01-01",
    )

    parser.add_argument(
        "--to-date",
        default="2026-12-31",
    )

    parser.add_argument(
        "--target-docs",
        type=int,
        default=250,
    )

    args = parser.parse_args()

    asyncio.run(
        main(
            args.host,
            args.organization,
            args.from_date,
            args.to_date,
            args.target_docs,
        )
    )
