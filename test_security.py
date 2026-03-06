import requests
import time
import pprint

BASE_URL = "http://localhost:9115"

def test_rate_limit():
    print("--- 1. Testing Rate Limiting on /login ---")
    session = requests.Session()
    responses = []
    
    # Send 7 requests (Should trigger 429 after 5)
    for i in range(7):
        # We need a dummy csrf_token for post requests, let's just GET to see if RL applies
        # If it applies to GET too, it works. If POST only, we first need to extract token.
        # But limiter is applied on route itself.
        r = session.get(f"{BASE_URL}/login")
        responses.append(r.status_code)
    
    print(f"Status codes for 7 rapid requests: {responses}")
    if 429 in responses:
        print("[Pass] Rate Limiter is working! Received 429 Too Many Requests.")
    else:
        print("[Fail] Did not receive 429 Too Many Requests.")

def test_csrf_missing():
    print("\n--- 2. Testing missing CSRF protection ---")
    session = requests.Session()
    # Try sending POST to login without CSRF token
    data = {'username': 'admin', 'password': 'wrongpassword'}
    r = session.post(f"{BASE_URL}/login", data=data)
    print(f"Response code without CSRF: {r.status_code}")
    if r.status_code == 400: # flask_wtf default for missing/invalid CSRF
        print("[Pass] CSRF protection blocked the request.")
    else:
        print("[Fail] CSRF did not block the request.")

if __name__ == "__main__":
    test_csrf_missing()
    time.sleep(1) # wait a bit
    test_rate_limit()

