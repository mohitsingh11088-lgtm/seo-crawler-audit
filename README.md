
# SEO Crawler & Internal Link Auditor

A Python and Streamlit application for crawling websites and
auditing internal links, redirects, HTTP errors, and basic SEO data.

## Features

- Concurrent website crawling
- XML sitemap discovery
- Internal link extraction with anchor text
- Redirect and redirect-chain reporting
- 404, 4xx, 5xx, and request-error reporting
- Page titles, meta descriptions, H1s, and canonical URLs
- Excel and CSV report exports
- Configurable crawl limits and concurrency
- Optional robots.txt compliance

## Installation

Python 3.11 or newer is recommended.

```bash
git clone https://github.com/YOUR_USERNAME/seo-crawler-audit.git
cd seo-crawler-audit

python -m venv .venv
```

Activate the virtual environment.

Windows:

```bash
.venv\Scripts\activate
```

macOS / Linux:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Start Streamlit:

```bash
streamlit run app.py
```

## Deployment

Push the project to GitHub and deploy the repository using
Streamlit Community Cloud.

Set the application entry point to `app.py`.

## Responsible crawling

Only crawl sites you own or have permission to audit.
Respect robots.txt, configure conservative request rates,
and avoid unnecessary requests to production servers.
