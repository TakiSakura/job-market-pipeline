import json
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT_DIR / "config" / "search_config.json"
OUTPUT_PATH = ROOT_DIR / "data" / "raw_jobs.json"

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = json.load(f)

role = config["role"]
location = config["location"]

BASE_URL = "https://www.jobbank.gc.ca"
SEARCH_URL = f"{BASE_URL}/jobsearch/jobsearch"

params = {
    "searchstring": role,
    "locationstring": location
}

headers = {
    "User-Agent": "Mozilla/5.0"
}

print("Requesting Job Bank...")
print(f"Role: {role}")
print(f"Location: {location}")

response = requests.get(
    SEARCH_URL,
    params=params,
    headers=headers,
    timeout=30
)

print(f"Status code: {response.status_code}")

response.raise_for_status()

soup = BeautifulSoup(response.text, "html.parser")

job_cards = soup.select("a.resultJobItem")

print(f"Found {len(job_cards)} job posting cards.")

jobs = []

for card in job_cards:

    title_element = card.select_one(".noctitle")
    company_element = card.select_one("li.business")
    location_element = card.select_one("li.location")
    date_element = card.select_one("li.date")
    salary_element = card.select_one("li.salary")
    source_element = card.select_one("li.source .wb-inv")

    title = (
        title_element.get_text(" ", strip=True)
        if title_element
        else None
    )

    company = (
        company_element.get_text(" ", strip=True)
        if company_element
        else None
    )

    job_location = (
        location_element.get_text(" ", strip=True)
        .replace("Location", "")
        .strip()
        if location_element
        else None
    )

    posted_date = (
        date_element.get_text(" ", strip=True)
        if date_element
        else None
    )

    salary = (
        salary_element.get_text(" ", strip=True)
        .replace("Salary", "")
        .strip()
        if salary_element
        else None
    )

    source = (
        source_element.get_text(" ", strip=True)
        if source_element
        else None
    )

    relative_url = card.get("href")

    job_url = (
        urljoin(BASE_URL, relative_url)
        if relative_url
        else None
    )

    job = {
        "title": title,
        "company": company,
        "location": job_location,
        "posted_date": posted_date,
        "salary": salary,
        "source": source,
        "job_url": job_url
    }

    jobs.append(job)


with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(
        jobs,
        f,
        ensure_ascii=False,
        indent=2
    )

print(f"\nSaved {len(jobs)} jobs to:")
print(OUTPUT_PATH)

print("\nFirst 3 records:")

for job in jobs[:3]:
    print(json.dumps(job, indent=2, ensure_ascii=False))