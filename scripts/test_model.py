"""Quick test: verify model runtime connects to DeepSeek, then run pipeline."""
import os
import sys

# Set these in your shell before running:
#   export CIA_MODEL_API_KEY=...
# Or edit below:
API_KEY = os.environ.get("CIA_MODEL_API_KEY", "")
MODEL_NAME = os.environ.get("CIA_MODEL_NAME", "deepseek-v4-flash")
ENDPOINT = os.environ.get("CIA_MODEL_ENDPOINT", "https://api.deepseek.com/v1/chat/completions")
PROVIDER = os.environ.get("CIA_MODEL_PROVIDER", "openai-compatible")

os.environ["CIA_MODEL_PROVIDER"] = PROVIDER
os.environ["CIA_MODEL_ENDPOINT"] = ENDPOINT
os.environ["CIA_MODEL_API_KEY"] = API_KEY
os.environ["CIA_MODEL_NAME"] = MODEL_NAME

# Fix Homebrew SSL
for cert_path in ["/etc/ssl/cert.pem", "/opt/homebrew/etc/openssl@3/cert.pem"]:
    if os.path.exists(cert_path):
        os.environ["SSL_CERT_FILE"] = cert_path
        break

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from competitive_intel_agents.runtime.model_runtime import ConfiguredProviderFactory, ModelRuntime
from competitive_intel_agents.models import ModelRequest

def test_connection():
    factory = ConfiguredProviderFactory()
    provider = factory.create()
    runtime = ModelRuntime(provider=provider)
    req = ModelRequest(
        agent="analyst",
        messages=[{"role": "user", "content": "Reply with exactly one word: OK"}],
        temperature=0.0,
    )
    resp = runtime.complete(req)
    print(f"Model: {MODEL_NAME}")
    print(f"OK: {resp.ok}")
    if resp.ok:
        print(f"Response: {resp.content[:200]}")
        print(f"Usage: {resp.usage}")
        return True
    else:
        print(f"Error: {resp.error}")
        return False


if __name__ == "__main__":
    test_connection()
    if len(sys.argv) > 1 and sys.argv[1] == "--run":
        print("\n--- Running full pipeline ---")
        from competitive_intel_agents.cli import main
        main([
            "run",
            "--input", "tests/fixtures/request.json",
            "--config", "config/agent_profiles.yaml",
            "--real-web", "--real-model",
            "--show-dashboard",
        ])
