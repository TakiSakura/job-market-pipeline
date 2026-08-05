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
    return {
        "job_id": str(job["id"]) if job.get("id") is not None else None,
        "title": job.get("title"),
        "company": nested_display_name(job, "company"),
        "location": nested_display_name(job, "location"),
        "posted_date": job.get("created"),
        "salary_min": job.get("salary_min"),
        "salary_max": job.get("salary_max"),
        "description": job.get("description"),
        "category": category.get("label") if isinstance(category, dict) else None,
        "contract_type": job.get("contract_type"),
        "source": "Adzuna",
        "job_url": sanitize_job_url(job.get("redirect_url")),
    }


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
    url = f"{ADZUNA_API_BASE_URL}/{country_code(country)}/search/1"
    params = {
        "app_id": app_id,
        "app_key": app_key,
        "what": role,
        "where": location,
        "results_per_page": 50,
        "content-type": "application/json",
    }

    print("Requesting jobs from Adzuna...")
    print(f"Country: {country}")
    print(f"Role: {role}")
    print(f"Location: {location}")

    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.Timeout as error:
        raise RuntimeError(
            f"Adzuna request timed out after {REQUEST_TIMEOUT_SECONDS} seconds."
        ) from error
    except requests.RequestException as error:
        # Request exception text can contain the prepared URL and its credentials.
        raise RuntimeError("Adzuna request failed due to a network error.") from error

    if response.status_code != 200:
        raise RuntimeError(
            f"Adzuna API returned HTTP {response.status_code}. "
            "Check the credentials, configuration, and API availability."
        )

    try:
        payload = response.json()
    except requests.JSONDecodeError as error:
        raise RuntimeError("Adzuna API returned an invalid JSON response.") from error

    results = payload.get("results", [])
    if not results:
        raise RuntimeError(
            f"Adzuna returned no jobs for role '{role}' in '{location}, {country}'."
        )

    jobs = [normalize_job(job) for job in results]
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
