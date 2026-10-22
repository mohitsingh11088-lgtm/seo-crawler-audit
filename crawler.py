
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
