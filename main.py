"""
main.py
Single entry point for the whole EcoLoop pipeline.

Usage:
    python main.py            # runs baseline + all optimization cycles
    streamlit run dashboard/app.py   # then view results
"""
from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env file
from controller.pipeline import run_closed_loop

if __name__ == "__main__":
    run_closed_loop()
