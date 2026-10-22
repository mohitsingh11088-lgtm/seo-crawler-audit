
import asyncio
import io
import os
import re
import zipfile

import pandas as pd
import streamlit as st

from crawler import crawl_website


st.set_page_config(
    page_title="SEO Crawler & Link Auditor",
    page_icon="🔎",
    layout="wide",
)

st.title("🔎 SEO Crawler & Internal Link Auditor")
st.caption(
    "Audit redirects, broken internal links, anchor text and "
    "on-page SEO across large websites."
)

with st.sidebar:
    st.header("Crawl Settings")

    website_url = st.text_input(
        "Website URL",
        placeholder="https://www.example.com",
    )

    max_urls = st.number_input(
        "Maximum URLs to fetch",
        min_value=100,
        max_value=1000000,
        value=10000,
        step=1000,
    )

    concurrency = st.slider(
        "Concurrent requests",
        min_value=1,
        max_value=30,
        value=10,
    )

    delay = st.slider(
        "Delay per request (seconds)",
        min_value=0.0,
        max_value=2.0,
        value=0.1,
        step=0.1,
    )

    use_sitemap = st.checkbox(
        "Discover URLs from XML sitemaps",
        value=True,
    )

    respect_robots = st.checkbox(
        "Respect robots.txt",
        value=True,
    )

    include_subdomains = st.checkbox(
        "Include subdomains",
        value=False,
    )

    start_crawl = st.button(
        "🚀 Start SEO Audit",
        type="primary",
        use_container_width=True,
    )

st.info(
    "Only crawl websites you own or have permission to audit. "
    "Start with a conservative request rate."
)

if start_crawl:
    if not website_url.strip():
        st.error("Enter a website URL first.")
        st.stop()

    output_dir = "reports"
    os.makedirs(output_dir, exist_ok=True)

    progress_bar = st.progress(0)
    progress_text = st.empty()
    current_url_text = st.empty()

    def update_progress(done, total, current_url):
        progress_bar.progress(
            min(int(done / total * 100), 100)
        )
        progress_text.write(f"URLs fetched: {done:,} / {total:,}")
        current_url_text.caption(f"Currently checking: {current_url}")

    try:
        with st.spinner("Crawling the website..."):
            results = asyncio.run(
                crawl_website(
                    start_url=website_url,
                    output_dir=output_dir,
                    max_urls=int(max_urls),
                    concurrency=int(concurrency),
                    delay=float(delay),
                    include_subdomains=include_subdomains,
                    use_sitemap=use_sitemap,
                    respect_robots=respect_robots,
                    progress_callback=update_progress,
                )
            )

        st.session_state["seo_results"] = results
        st.session_state["seo_output_dir"] = output_dir

        progress_bar.progress(100)
        progress_text.success("Crawl completed.")

    except Exception as exc:
        st.error(f"Audit failed: {exc}")


results = st.session_state.get("seo_results")

if results:
    pages = pd.DataFrame(results["pages"])
    links = pd.DataFrame(results["links"])
    redirects = pd.DataFrame(results["redirects"])
    broken = pd.DataFrame(results["broken_links"])
    errors = pd.DataFrame(results["errors"])

    total_pages = len(pages)
    total_links = len(links)

    if not pages.empty and "status_code" in pages:
        status = pd.to_numeric(
            pages["status_code"], errors="coerce"
        )
        page_404s = int((status == 404).sum())
        page_errors = int((status >= 400).sum())
    else:
        page_404s = 0
        page_errors = 0

    st.divider()
    st.subheader("Audit Summary")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("URLs fetched", f"{results['checked_urls']:,}")
    c2.metric("Internal links", f"{total_links:,}")
    c3.metric("Redirect hops", f"{len(redirects):,}")
    c4.metric("Broken / redirected links", f"{len(broken):,}")

    c5, c6, c7 = st.columns(3)
    c5.metric("404 pages", f"{page_404s:,}")
    c6.metric("HTTP error pages", f"{page_errors:,}")
    c7.metric("Request errors", f"{len(errors):,}")

    st.subheader("Audit Reports")

    tabs = st.tabs([
        "Broken Links",
        "Redirects",
        "All Internal Links",
        "Pages & SEO",
        "Request Errors",
    ])

    with tabs[0]:
        st.caption(
            "Each row identifies the source page, anchor text, "
            "original linked URL, status and final destination."
        )
        st.dataframe(broken, use_container_width=True, hide_index=True)

    with tabs[1]:
        st.dataframe(
            redirects,
            use_container_width=True,
            hide_index=True,
        )

    with tabs[2]:
        st.dataframe(
            links,
            use_container_width=True,
            hide_index=True,
        )

    with tabs[3]:
        st.dataframe(
            pages,
            use_container_width=True,
            hide_index=True,
        )

    with tabs[4]:
        st.dataframe(
            errors,
            use_container_width=True,
            hide_index=True,
        )

    # Build an Excel workbook containing separate worksheets.
    workbook = io.BytesIO()

    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        pages.to_excel(writer, sheet_name="Pages SEO", index=False)
        redirects.to_excel(writer, sheet_name="Redirects", index=False)
        broken.to_excel(writer, sheet_name="Broken Links", index=False)
        links.to_excel(writer, sheet_name="Internal Links", index=False)
        errors.to_excel(writer, sheet_name="Request Errors", index=False)

    st.download_button(
        "⬇️ Download Complete Excel Report",
        data=workbook.getvalue(),
        file_name="seo_audit_report.xlsx",
        mime=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        use_container_width=True,
    )

    # Provide all individual CSV reports in a ZIP archive.
    zip_buffer = io.BytesIO()
    report_dir = results["output_dir"]

    with zipfile.ZipFile(
        zip_buffer, "w", zipfile.ZIP_DEFLATED
    ) as archive:
        for filename in os.listdir(report_dir):
            if filename.endswith(".csv"):
                path = os.path.join(report_dir, filename)
                archive.write(path, arcname=filename)

    st.download_button(
        "⬇️ Download All CSV Reports (ZIP)",
        data=zip_buffer.getvalue(),
        file_name="seo_audit_csv_reports.zip",
        mime="application/zip",
        use_container_width=True,
    )
