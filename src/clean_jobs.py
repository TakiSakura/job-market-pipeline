import json
import re
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]

RAW_PATH = ROOT_DIR / "data" / "raw_jobs.json"
CLEAN_PATH = ROOT_DIR / "data" / "clean_jobs.json"
CONFIG_PATH = ROOT_DIR / "config" / "search_config.json"

TORONTO_LOCATION_COMPONENTS = {"toronto", "city of toronto"}


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


def normalized_components(values):
    return {
        str(value).strip().casefold()
        for value in values
        if str(value).strip()
    }


def is_toronto_location(location, location_area):
    """Recognize Toronto using exact structured or display-name components."""
    area_components = normalized_components(location_area or [])
    if area_components & TORONTO_LOCATION_COMPONENTS:
        return True

    display_components = normalized_components(
        str(location or "").split(",")
    )
    return bool(display_components & TORONTO_LOCATION_COMPONENTS)


def find_component(location_area, expected_values):
    expected = {value.casefold() for value in expected_values}
    for value in location_area or []:
        if str(value).strip().casefold() in expected:
            return str(value).strip()
    return None


def normalize_job_location(job, config):
    location = job.get("location")
    location_area = job.get("location_area") or []
    target_location = config["location"].strip()
    default_country = config["country"].strip()

    if (
        target_location.casefold() == "toronto"
        and is_toronto_location(location, location_area)
    ):
        country = find_component(location_area, {"Canada"}) or default_country
        province = find_component(location_area, {"Ontario", "ON"}) or "Ontario"
        if province.casefold() == "on":
            province = "Ontario"

        return {
            "city": "Toronto",
            "province": province,
            "country": country,
        }

    return parse_location(location, default_country)


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

        parsed_location = normalize_job_location(job, config)

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
