from dotenv import load_dotenv
import os

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
FMP_API_KEY = os.getenv("FMP_API_KEY")