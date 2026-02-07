#!/usr/bin/env python3
"""
Marketplace Seeder Cleanup Utility

Removes all seeded data (agents, tasks, ledger entries, ratings).
The drip seeder runs automatically as a background task in the API server.

Usage:
    python scripts/seed_marketplace.py --clean
    python scripts/seed_marketplace.py --status
"""

import argparse

from sqlalchemy import text

from pinchwork.database import SessionLocal


def show_status(db):
    """Show counts of seeded vs real data."""
    print("📊 Marketplace Seeder Status\n")

    # Seeded agents
    result = db.execute(text("SELECT COUNT(*) FROM agents WHERE seeded = true"))
    seeded_agents = result.scalar() or 0

    result = db.execute(text("SELECT COUNT(*) FROM agents WHERE seeded = false"))
    real_agents = result.scalar() or 0

    print(f"Agents:  {seeded_agents:4d} seeded | {real_agents:4d} real")

    # Seeded tasks
    result = db.execute(text("SELECT COUNT(*) FROM tasks WHERE seeded = true"))
    seeded_tasks = result.scalar() or 0

    result = db.execute(text("SELECT COUNT(*) FROM tasks WHERE seeded = false"))
    real_tasks = result.scalar() or 0

    print(f"Tasks:   {seeded_tasks:4d} seeded | {real_tasks:4d} real")

    # Ledger entries
    result = db.execute(
        text("""
        SELECT COUNT(*) FROM credit_ledger
        WHERE task_id IN (SELECT id FROM tasks WHERE seeded = true)
    """)
    )
    seeded_ledger = result.scalar() or 0

    print(f"Ledger:  {seeded_ledger:4d} seeded entries")

    # Ratings
    result = db.execute(
        text("""
        SELECT COUNT(*) FROM ratings
        WHERE task_id IN (SELECT id FROM tasks WHERE seeded = true)
    """)
    )
    seeded_ratings = result.scalar() or 0

    print(f"Ratings: {seeded_ratings:4d} seeded entries")

    print("\n💡 Drip seeder runs automatically in the API server.")
    print("   Set PINCHWORK_SEED_MARKETPLACE_DRIP=true to enable.")


def clean_seeded_data(db):
    """Remove all seeded agents and tasks."""
    print("🧹 Cleaning seeded data...")

    # Check for interactions between real and seeded data
    real_agents_with_seeded_tasks = db.execute(
        text("""
        SELECT DISTINCT poster_id FROM tasks
        WHERE seeded = false AND worker_id IN (SELECT id FROM agents WHERE seeded = true)
        UNION
        SELECT DISTINCT worker_id FROM tasks
        WHERE seeded = false AND poster_id IN (SELECT id FROM agents WHERE seeded = true)
    """)
    ).fetchall()

    if real_agents_with_seeded_tasks:
        count = len(real_agents_with_seeded_tasks)
        print(f"⚠️  Warning: {count} real agents have interacted with seeded data")
        print("   Their tasks will remain, but seeded agents will be removed")

    # Delete in correct order (FK constraints)
    result = db.execute(
        text("DELETE FROM ratings WHERE task_id IN (SELECT id FROM tasks WHERE seeded = true)")
    )
    print(f"✓ Removed {result.rowcount} seeded ratings")

    result = db.execute(
        text(
            "DELETE FROM credit_ledger WHERE task_id IN (SELECT id FROM tasks WHERE seeded = true)"
        )
    )
    print(f"✓ Removed {result.rowcount} seeded ledger entries (task-linked)")

    result = db.execute(
        text(
            "DELETE FROM credit_ledger WHERE agent_id IN "
            "(SELECT id FROM agents WHERE seeded = true)"
        )
    )
    print(f"✓ Removed {result.rowcount} seeded ledger entries (agent-linked)")

    result = db.execute(text("DELETE FROM tasks WHERE seeded = true"))
    print(f"✓ Removed {result.rowcount} seeded tasks")

    result = db.execute(text("DELETE FROM agents WHERE seeded = true"))
    print(f"✓ Removed {result.rowcount} seeded agents")

    db.commit()
    print("\n✓ Seeded data removed")
    print("  Drip seeder will recreate agent pool on next run (if enabled)")


def main():
    parser = argparse.ArgumentParser(
        description="Manage marketplace seeded data",
        epilog="The drip seeder runs automatically in the API server. "
        "Set PINCHWORK_SEED_MARKETPLACE_DRIP=true to enable.",
    )
    parser.add_argument("--clean", action="store_true", help="Remove all seeded data")
    parser.add_argument("--status", action="store_true", help="Show seeded vs real data counts")

    args = parser.parse_args()

    if not args.clean and not args.status:
        parser.print_help()
        return

    db = SessionLocal()

    try:
        if args.status:
            show_status(db)
        elif args.clean:
            clean_seeded_data(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
