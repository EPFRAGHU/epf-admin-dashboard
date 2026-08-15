import os
import json
from pathlib import Path

from webapp.database import SessionLocal, ProjectData, DATABASE_URL

def sync():
    if not DATABASE_URL or not SessionLocal:
        print("No Supabase connection configured. Skipping sync.")
        return

    print("Syncing local JSON files to Supabase...")
    base_dir = Path(__file__).resolve().parent
    db = SessionLocal()
    try:
        count = 0
        for f in base_dir.iterdir():
            if f.name.endswith(".epfproj.json"):
                with open(f, 'r', encoding='utf-8') as file:
                    try:
                        data = json.load(file)
                    except json.JSONDecodeError:
                        print(f"Skipping {f.name} - Invalid JSON")
                        continue
                
                # Check if exists
                existing = db.query(ProjectData).filter(ProjectData.filename == f.name).first()
                if existing:
                    print(f"Updating {f.name} in Supabase")
                    existing.data = json.dumps(data, ensure_ascii=False)
                else:
                    print(f"Adding {f.name} to Supabase")
                    new_proj = ProjectData(filename=f.name, data=json.dumps(data, ensure_ascii=False))
                    db.add(new_proj)
                count += 1
        db.commit()
        print(f"Sync complete. Processed {count} project files.")
    except Exception as e:
        print(f"Error during sync: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    sync()
