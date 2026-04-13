import requests, json
r = requests.get('http://localhost:5000/api/agentic/approval-chains')
data = r.json()
chains = data.get('chains', data.get('data', []))
for c in chains[:12]:
    dept = c.get('department', '?')
    level = c.get('approval_level', '?')
    email = c.get('approver_email', '?')
    thresh = c.get('budget_threshold', '?')
    print(f"Dept: {dept:15} Level: {level} Email: {email:40} Threshold: {thresh}")
