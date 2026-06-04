import subprocess
import argparse
import sys


STEPS = [
    ["python", "motion_vote_backfill.py"],
]


def run_step(command, limit):
    cmd = command + ["--limit", str(limit)]

    print(f"\n=== Running: {' '.join(cmd)} ===")
    result = subprocess.run(cmd)

    if result.returncode != 0:
        print(f"FAILED: {' '.join(cmd)}")
        sys.exit(result.returncode)

    print(f"Completed: {' '.join(cmd)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--loops", type=int, default=1)
    args = parser.parse_args()

    for i in range(args.loops):
        print(f"\nVote backfill loop {i + 1} of {args.loops}")
        for step in STEPS:
            run_step(step, args.limit)

    print("\nVote backfill complete.")


if __name__ == "__main__":
    main()
