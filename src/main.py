import json
import os
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT_DIR / "config" / "search_config.json"
OUTPUT_PATH = ROOT_DIR / "data" / "raw_jobs.json"
ADZUNA_API_BASE_URL = "https://api.adzuna.com/v1/api/jobs"
REQUEST_TIMEOUT_SECONDS = 30
DEFAULT_RESULTS_PER_PAGE = 50
DEFAULT_MAX_PAGES = 1

COUNTRY_CODES = {
    "australia": "au", "austria": "at", "belgium": "be", "brazil": "br",
    "canada": "ca", "france": "fr", "germany": "de", "india": "in",
    "italy": "it", "mexico": "mx", "netherlands": "nl", "new zealand": "nz",
    "poland": "pl", "singapore": "sg", "south africa": "za", "spain": "es",
    "switzerland": "ch", "united kingdom": "gb", "uk": "gb",
    "united states": "us", "usa": "us",
}


def country_code(country):
    value = country.strip().lower()
    if len(value) == 2:
        return value
    if value not in COUNTRY_CODES:
        raise ValueError(
            f"Unsupported country '{country}'. Use a supported country name "
            "or its two-letter Adzuna country code."
        )
    return COUNTRY_CODES[value]


def nested_display_name(record, field):
    value = record.get(field)
    return value.get("display_name") if isinstance(value, dict) else None


def sanitize_job_url(url):
    """Remove API-client attribution values from Adzuna redirect URLs."""
    if not url:
        return None

    parsed = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() != "utm_source"
    ]
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


def normalize_job(job):
    category = job.get("category")
    location = job.get("location")
    location_area = location.get("area", []) if isinstance(location, dict) else []
    return {
        "job_id": str(job["id"]) if job.get("id") is not None else None,
        "title": job.get("title"),
        "company": nested_display_name(job, "company"),
        "location": nested_display_name(job, "location"),
        "location_area": [str(item) for item in location_area if item],
        "posted_date": job.get("created"),
        "salary_min": job.get("salary_min"),
        "salary_max": job.get("salary_max"),
        "description": job.get("description"),
        "category": category.get("label") if isinstance(category, dict) else None,
        "contract_type": job.get("contract_type"),
        "source": "Adzuna",
        "job_url": sanitize_job_url(job.get("redirect_url")),
    }


def sanitize_raw_payload(job):
    """Copy the source ad while removing credential-linked URL attribution."""
    payload = json.loads(json.dumps(job))
    if payload.get("redirect_url"):
        payload["redirect_url"] = sanitize_job_url(payload["redirect_url"])
    return payload


def build_raw_record(fetched_job, config):
    payload = fetched_job["payload"]
    normalized = normalize_job(payload)
    return {
        **normalized,
        "source_job_id": normalized["job_id"],
        "page_number": fetched_job["page_number"],
        "position_in_page": fetched_job["position_in_page"],
        "search_role": config["role"],
        "search_location": config["location"],
        "raw_payload": sanitize_raw_payload(payload),
    }


def positive_integer(config, field, default):
    value = config.get(field, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"Configuration field '{field}' must be a positive integer.")
    return value


def request_page(country, page, params, request_get=None):
    request_get = request_get or requests.get
    url = f"{ADZUNA_API_BASE_URL}/{country_code(country)}/search/{page}"

    print(f"Requesting Adzuna page {page}...")

    try:
        response = request_get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.Timeout as error:
        raise RuntimeError(
            f"Adzuna page {page} timed out after "
            f"{REQUEST_TIMEOUT_SECONDS} seconds."
        ) from error
    except requests.RequestException as error:
        # Exception text can include the prepared URL and credentials.
        raise RuntimeError(
            f"Adzuna page {page} failed due to a network error."
        ) from error

    if response.status_code != 200:
        raise RuntimeError(
            f"Adzuna page {page} returned HTTP {response.status_code}. "
            "Check the credentials, configuration, and API availability."
        )

    try:
        payload = response.json()
    except requests.JSONDecodeError as error:
        raise RuntimeError(
            f"Adzuna page {page} returned invalid JSON."
        ) from error

    results = payload.get("results", [])
    if not isinstance(results, list):
        raise RuntimeError(
            f"Adzuna page {page} returned an invalid results payload."
        )

    print(f"Received {len(results)} jobs.")
    return results


def fetch_all_job_records(config, app_id, app_key, request_get=None):
    results_per_page = positive_integer(
        config,
        "results_per_page",
        DEFAULT_RESULTS_PER_PAGE,
    )
    max_pages = positive_integer(config, "max_pages", DEFAULT_MAX_PAGES)
    params = {
        "app_id": app_id,
        "app_key": app_key,
        "what": config["role"],
        "where": config["location"],
        "results_per_page": results_per_page,
        "content-type": "application/json",
    }

    all_results = []
    pages_fetched = 0

    for page in range(1, max_pages + 1):
        page_results = request_page(
            config["country"],
            page,
            params,
            request_get=request_get,
        )
        pages_fetched += 1

        if not page_results:
            if page == 1:
                raise RuntimeError(
                    f"Adzuna returned no jobs for role '{config['role']}' "
                    f"in '{config['location']}, {config['country']}'."
                )
            print(f"Page {page} was empty; pagination complete.")
            break

        all_results.extend(
            {
                "payload": job,
                "page_number": page,
                "position_in_page": position,
            }
            for position, job in enumerate(page_results, start=1)
        )

        if len(page_results) < results_per_page:
            print(
                f"Page {page} returned fewer than {results_per_page} jobs; "
                "pagination complete."
            )
            break

    return all_results, pages_fetched


def fetch_all_jobs(config, app_id, app_key, request_get=None):
    """Backward-compatible payload-only pagination helper for ETL comparison."""
    records, pages_fetched = fetch_all_job_records(
        config,
        app_id,
        app_key,
        request_get=request_get,
    )
    return [record["payload"] for record in records], pages_fetched


def deduplicate_jobs(jobs):
    unique_jobs = []
    seen_job_ids = set()

    for job in jobs:
        job_id = job.get("job_id")
        if job_id and job_id in seen_job_ids:
            continue
        if job_id:
            seen_job_ids.add(job_id)
        unique_jobs.append(job)

    return unique_jobs


def main():
    load_dotenv(ROOT_DIR / ".env")

    app_id = os.getenv("ADZUNA_APP_ID")
    app_key = os.getenv("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        raise RuntimeError(
            "Missing Adzuna credentials. Set ADZUNA_APP_ID and "
            "ADZUNA_APP_KEY in the environment or in a local .env file."
        )

    with open(CONFIG_PATH, "r", encoding="utf-8") as file:
        config = json.load(file)

    country = config["country"]
    location = config["location"]
    role = config["role"]
    results_per_page = positive_integer(
        config, "results_per_page", DEFAULT_RESULTS_PER_PAGE
    )
    max_pages = positive_integer(config, "max_pages", DEFAULT_MAX_PAGES)

    print("Requesting jobs from Adzuna...")
    print(f"Country: {country}")
    print(f"Role: {role}")
    print(f"Location: {location}")
    print(f"Results per page: {results_per_page}")
    print(f"Maximum pages: {max_pages}")

    fetched_jobs, pages_fetched = fetch_all_job_records(config, app_id, app_key)
    jobs = [build_raw_record(job, config) for job in fetched_jobs]
    source_job_ids = [job["source_job_id"] for job in jobs if job["source_job_id"]]
    unique_source_jobs = len(set(source_job_ids))
    duplicate_source_rows = len(source_job_ids) - unique_source_jobs

    print(f"Pages fetched: {pages_fetched}")
    print(f"Raw source rows: {len(jobs)}")
    print(f"Unique source job IDs: {unique_source_jobs}")
    print(f"Duplicate source rows preserved: {duplicate_source_rows}")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as file:
        json.dump(jobs, file, ensure_ascii=False, indent=2)

    print(f"Saved {len(jobs)} jobs to: {OUTPUT_PATH}")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, OSError, ValueError, RuntimeError) as error:
        print(f"Extraction failed: {error}", file=sys.stderr)
        sys.exit(1)
