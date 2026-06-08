"""Diagnose DuckDuckGo HTML parsing — run once to see the raw HTML structure."""
import sys, re, urllib.parse
sys.path.insert(0, "src")
from competitive_intel_agents.runtime.web_tools import HttpClient

client = HttpClient()
q = urllib.parse.quote_plus("test search python")

print("=== HTML endpoint ===")
try:
    html = client.get_text(f"https://html.duckduckgo.com/html/?q={q}", timeout=10)
    print(f"Length: {len(html)}")
    # Find all <a> tags
    links = re.findall(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html)
    print(f"Total <a> tags: {len(links)}")
    for href, text in links[:15]:
        clean = re.sub(r"<[^>]+>", "", text).strip()[:100]
        print(f"  {clean}")
        print(f"    -> {href[:120]}")
    # Show result-like sections
    for marker in ["result__a", "result-link", "result__url", "result__snippet",
                    "web-result", "result-title", "links_main", "snippet"]:
        idx = html.lower().find(marker)
        if idx >= 0:
            print(f"\n--- Found '{marker}' at pos {idx} ---")
            print(html[max(0,idx-30):idx+200])
except Exception as e:
    print(f"Error: {e}")

print("\n=== LITE endpoint ===")
try:
    html = client.get_text(f"https://lite.duckduckgo.com/lite/?q={q}", timeout=10)
    print(f"Length: {len(html)}")
    links = re.findall(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html)
    print(f"Total <a> tags: {len(links)}")
    for href, text in links[:15]:
        clean = re.sub(r"<[^>]+>", "", text).strip()[:100]
        print(f"  {clean}")
        print(f"    -> {href[:120]}")
except Exception as e:
    print(f"Error: {e}")
