import os
import json
import requests
from pathlib import Path
from dotenv import load_dotenv


# Load API key from .env
load_dotenv()

API_KEY = os.getenv("OPENFDA_API_KEY")


# Create raw data folder
raw_folder = Path("data/raw")
raw_folder.mkdir(parents=True, exist_ok=True)


# OpenFDA endpoints
datasets = {
    "drug_event": "https://api.fda.gov/drug/event.json",
    "drug_label": "https://api.fda.gov/drug/label.json",
    "drug_ndc": "https://api.fda.gov/drug/ndc.json"
}


# Number of records to download for testing
LIMIT = 1


def download_data(name, url):
    print(f"Downloading {name}...")

    params = {
        "api_key": API_KEY,
        "limit": LIMIT
    }

    response = requests.get(url, params=params)

    response.raise_for_status()

    data = response.json()

    file_path = raw_folder / f"One_{name}.json"

    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)

    print(f"Saved: {file_path}")
    print(f"Records downloaded: {len(data.get('results', []))}")
    print("-" * 40)


# Download all datasets
for name, url in datasets.items():
    download_data(name, url)


print("All downloads completed!")