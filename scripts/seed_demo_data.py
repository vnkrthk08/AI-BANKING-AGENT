"""Isolated developer tool for seeding demonstration banking operations data.

Usage:
    python scripts/seed_demo_data.py --seed
    python scripts/seed_demo_data.py --clean
"""

import argparse
import sys
from kural.persistence.database import Database
from kural.services.campaign_service import CampaignService
from kural.services.customer_service import CustomerService
from kural.services.call_service import CallService


def seed_demo_data(db: Database) -> None:
    camp_svc = CampaignService(db)
    cust_svc = CustomerService(db)
    call_svc = CallService(db)

    print("Seeding demonstration banking campaigns and customer profiles...")
    c1 = camp_svc.create_campaign(
        name="App adoption · Q4",
        objective="App adoption",
        script_version="v2.4",
        segment_size=8200,
        max_attempts=3,
        retry_gap_hours=24,
        languages=["Hindi", "English", "Tamil"],
        region="All India",
        status="ACTIVE",
    )
    c2 = camp_svc.create_campaign(
        name="App update follow-up",
        objective="App update",
        script_version="v1.8",
        segment_size=3400,
        max_attempts=2,
        retry_gap_hours=36,
        languages=["English", "Kannada", "Telugu"],
        region="South",
        status="ACTIVE",
    )

    cust1 = cust_svc.create_customer("Rajesh Sharma", "9876543210", "CUST-00001", preferred_language="Hindi", branch="Delhi NCR", region="North", app_status="INSTALLED", app_version="4.9.2")
    cust2 = cust_svc.create_customer("Priya Sundaram", "9876543211", "CUST-00002", preferred_language="Tamil", branch="Chennai South", region="South", app_status="NOT_INSTALLED")
    cust3 = cust_svc.create_customer("Amit Patel", "9876543212", "CUST-00003", preferred_language="Hindi", branch="Mumbai Metro", region="West", app_status="OUTDATED", app_version="4.7.0")
    cust_svc.create_customer("Sneha Reddy", "9876543213", "CUST-00004", preferred_language="Telugu", branch="Hyderabad Central", region="South", app_status="INSTALLED", app_version="5.0.0")
    cust_svc.create_customer("Rahul Mukherjee", "9876543214", "CUST-00005", preferred_language="Bengali", branch="Kolkata East", region="East", app_status="NOT_INSTALLED")

    camp_svc.add_contact(c1["id"], cust1["customer_ref"], cust1["phone"])
    camp_svc.add_contact(c1["id"], cust2["customer_ref"], cust2["phone"])
    camp_svc.add_contact(c1["id"], cust3["customer_ref"], cust3["phone"])
    print(f"Successfully seeded 2 campaigns and 5 customers with enrolled contacts.")


def main():
    parser = argparse.ArgumentParser(description="KURAL AVA Demo Data Utility")
    parser.add_argument("--seed", action="store_true", help="Seed demonstration data into local database")
    args = parser.parse_args()

    if not args.seed:
        print("Explicit flag required. Run with --seed to populate demo fixtures.")
        sys.exit(1)

    db = Database()
    seed_demo_data(db)


if __name__ == "__main__":
    main()
