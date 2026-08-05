import json
import re
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]

RAW_PATH = ROOT_DIR / "data" / "raw_jobs.json"
CLEAN_PATH = ROOT_DIR / "data" / "clean_jobs.json"
CONFIG_PATH = ROOT_DIR / "config" / "search_config.json"


def clean_job_url(url):
    """
    Convert a session-based Job Bank URL into a stable URL.

    Example:
    https://www.jobbank.gc.ca/jobsearch/jobposting/50000609;jsessionid=...?source=searchresults

    becomes:

    https://www.jobbank.gc.ca/jobsearch/jobposting/50000609
    """
    if not url:
        return None

    match = re.search(r"/jobposting/(\d+)", url)

    if match:
        job_id = match.group(1)
        return f"https://www.jobbank.gc.ca/jobsearch/jobposting/{job_id}"

    return url


def extract_job_id(url):
    """
    Extract the Job Bank job ID from the cleaned job URL.

    Example:
    https://www.jobbank.gc.ca/jobsearch/jobposting/50000609

    returns:

    50000609
    """
    if not url:
        return None

    match = re.search(r"/jobposting/(\d+)", url)

    if match:
        return match.group(1)

    return None


def parse_location(location):
    """
    Normalize Job Bank location strings.

    Examples:

    Toronto (ON)
    ->
    city = Toronto
    province = ON
    country = Canada

    Vancouver, BC
    ->
    city = Vancouver
    province = BC
    country = Canada
    """

    if not location:
        return {
            "city": None,
            "province": None,
            "country": "Canada"
        }

    location = location.strip()

    if location.lower() == "various locations":
        return {
            "city": None,
            "province": None,
            "country": "Canada"
        }

    # Format: Toronto (ON)
    match = re.match(r"(.+?)\s*\(([A-Z]{2})\)$", location)

    if match:
        city = match.group(1).strip()
        province = match.group(2)

        return {
            "city": city,
            "province": province,
            "country": "Canada"
        }

    # Format: Vancouver, BC
    match = re.match(r"(.+?),\s*([A-Z]{2})$", location)

    if match:
        city = match.group(1).strip()
        province = match.group(2)

        return {
            "city": city,
            "province": province,
            "country": "Canada"
        }

    # Fallback
    return {
        "city": location,
        "province": None,
        "country": "Canada"
    }


def load_json(path):
    """
    Load a JSON file.
    """
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    """
    Save Python data as formatted JSON.
    """
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


def main():

    raw_jobs = load_json(RAW_PATH)
    config = load_json(CONFIG_PATH)

    target_location = config["location"].strip().lower()

    clean_jobs = []

    for job in raw_jobs:

        parsed_location = parse_location(job.get("location"))

        clean_url = clean_job_url(
            job.get("job_url")
        )

        clean_job = {
            "job_id": extract_job_id(clean_url),
            "title": job.get("title"),
            "company": job.get("company"),
            "city": parsed_location["city"],
            "province": parsed_location["province"],
            "country": parsed_location["country"],
            "posted_date": job.get("posted_date"),
            "salary": job.get("salary"),
            "source": job.get("source"),
            "job_url": clean_url
        }

        city = clean_job["city"]

        # Keep only jobs matching the configured target location
        if city and city.lower() == target_location:
            clean_jobs.append(clean_job)

    save_json(
        CLEAN_PATH,
        clean_jobs
    )

    print(f"Raw jobs: {len(raw_jobs)}")
    print(
        f"Clean jobs matching "
        f"'{config['location']}': {len(clean_jobs)}"
    )

    print(f"Saved to: {CLEAN_PATH}")

    print("\nClean records:")

    for job in clean_jobs:
        print(
            json.dumps(
                job,
                indent=2,
                ensure_ascii=False
            )
        )


if __name__ == "__main__":
    main()