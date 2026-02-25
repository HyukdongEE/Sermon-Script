import argparse
from app.main import _run_jobs

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=10)
    args = ap.parse_args()
    n = _run_jobs(batch=args.batch)
    print(f"[OK] processed {n} jobs")

if __name__ == "__main__":
    main()
