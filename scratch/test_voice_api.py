import httpx
import time

def test_api():
    url = "http://localhost:8000/api/voice/listen_once"
    print(f"Testing Javris Voice API at {url}...")
    print("When you see 'START SPEAKING', say 'What time is it?' clearly.")
    
    try:
        # We give the user 2 seconds to prepare
        time.sleep(1)
        print("\n>>> START SPEAKING NOW! <<<\n")
        
        # This will block until the server's VAD finishes
        resp = httpx.post(url, timeout=60)
        
        if resp.status_code == 200:
            print("Response Received:")
            data = resp.json()
            print(f"Transcript: {data.get('transcript')}")
            print(f"Server Msg: {data.get('reply')}")
        else:
            print(f"Error: Server returned {resp.status_code}")
            print(resp.text)
            
    except Exception as e:
        print(f"Failed to connect to server: {e}")

if __name__ == "__main__":
    test_api()
