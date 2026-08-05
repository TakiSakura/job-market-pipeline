import json
import re
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]

RAW_PATH = ROOT_DIR / "data" / "raw_jobs.json"
CLEAN_PATH = ROOT_DIR / "data" / "clean_jobs.json"
CONFIG_PATH = ROOT_DIR / "config" / "search_config.json"


def parse_location(location, default_country):
    """
    Normalize location strings returned by Adzuna.

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
            "country": default_country
        }

    location = location.strip()

    if location.lower() == "various locations":
        return {
            "city": None,
            "province": None,
            "country": default_country
        }

    # Format: Toronto (ON)
    match = re.match(r"(.+?)\s*\(([A-Z]{2})\)$", location)

    if match:
        city = match.group(1).strip()
        province = match.group(2)

        return {
            "city": city,
            "province": province,
            "country": default_country
        }

    # Format: Vancouver, BC
    match = re.match(r"(.+?),\s*([A-Z]{2})$", location)

    if match:
        city = match.group(1).strip()
        province = match.group(2)

        return {
            "city": city,
            "province": province,
            "country": default_country
        }

    # Adzuna commonly returns locations such as Toronto, Ontario, Canada.
    parts = [part.strip() for part in location.split(",") if part.strip()]
    if len(parts) >= 2:
        return {
            "city": parts[0],
            "province": parts[1],
            "country": parts[2] if len(parts) >= 3 else default_country
        }

    # Fallback
    return {
        "city": location,
        "province": None,
        "country": default_country
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

        parsed_location = parse_location(
            job.get("location"),
            config["country"]
        )

        clean_job = {
            "job_id": job.get("job_id"),
            "title": job.get("title"),
            "company": job.get("company"),
            "city": parsed_location["city"],
            "province": parsed_location["province"],
            "country": parsed_location["country"],
            "posted_date": job.get("posted_date"),
            "salary_min": job.get("salary_min"),
            "salary_max": job.get("salary_max"),
            "description": job.get("description"),
            "category": job.get("category"),
            "contract_type": job.get("contract_type"),
            "source": job.get("source"),
            "job_url": job.get("job_url")
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

if __name__ == "__main__":
    main()
