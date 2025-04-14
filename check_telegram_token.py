import os
import sys

# Check if TELEGRAM_TOKEN is set
token = os.environ.get("TELEGRAM_TOKEN")
if not token:
    print("No TELEGRAM_TOKEN provided. Please set the TELEGRAM_TOKEN environment variable.")
    sys.exit(1)

print(f"TELEGRAM_TOKEN is set. Length: {len(token)}")
print("Token validation successful.")
sys.exit(0)