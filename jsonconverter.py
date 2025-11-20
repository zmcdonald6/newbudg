import json
with open("service_account.json") as f:
    data = json.load(f)
data["private_key"] = data["private_key"].replace("\n", "\\n")
print("[GOOGLE]")
for k, v in data.items():
    print(f'{k} = "{v}"')
