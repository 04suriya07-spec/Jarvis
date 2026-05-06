import httpx
import sys

def list_models(key):
    try:
        url = f"https://generativelanguage.googleapis.com/v1/models?key={key}"
        r = httpx.get(url)
        if r.status_code == 200:
            models = r.json().get('models', [])
            print("Available Models:")
            for m in models:
                if 'generateContent' in m.get('supportedGenerationMethods', []):
                    print(f"- {m['name']}")
        else:
            print(f"Error {r.status_code}: {r.text}")
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        list_models(sys.argv[1])
    else:
        print("Usage: python list_models.py YOUR_API_KEY")
