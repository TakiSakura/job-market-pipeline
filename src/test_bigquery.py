from google.cloud import bigquery

from pipeline_config import DATASET_ID, PROJECT_ID

client = bigquery.Client(project=PROJECT_ID)

dataset_ref = client.dataset(DATASET_ID)
dataset = client.get_dataset(dataset_ref)

print("BigQuery connection successful!")
print(f"Project:  {dataset.project}")
print(f"Dataset:  {dataset.dataset_id}")
print(f"Location: {dataset.location}")
