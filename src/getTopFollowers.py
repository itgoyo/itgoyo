import requests
import sys
import re

if __name__ == "__main__":
    assert(len(sys.argv) == 4)
    handle = sys.argv[1]
    token = sys.argv[2]
    readmePath = sys.argv[3]

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {token}"
    }

    followers = []

    for i in range(1, 100000):
        page = requests.get(f"https://api.github.com/users/{handle}/followers?page={i}&per_page=100", headers = headers).json()
        if len(page) == 0:
            break
        for follower in page:
            info = requests.get(follower["url"], headers = headers).json()
            if info["following"] > 10000:
                continue
            followers.append((info["followers"], info["login"], info["id"], info["name"] if info["name"] else info["login"]))
            print(followers[-1])

    followers.sort(reverse = True)

    html = "<table>\n"

    for i in range(min(len(followers), 14)):
        login = followers[i][1]
        id = followers[i][2]
        name = followers[i][3]
        if i % 7 == 0:
            if i != 0:
                html += "  </tr>\n"
            html += "  <tr>\n"
        html += f'''    <td align="center">
      <a href="https://github.com/{login}">
        <img src="https://avatars2.githubusercontent.com/u/{id}" width="100px;" alt="{login}"/>
      </a>
      <br />
      <a href="https://github.com/{login}">{name}</a>
    </td>
'''

    html += "  </tr>\n</table>"

    with open(readmePath, "r") as readme:
        content = readme.read()

    newContent = re.sub(r"(?<=<!\-\-START_SECTION:top\-followers\-\->)[\s\S]*(?=<!\-\-END_SECTION:top\-followers\-\->)", f"\n{html}\n", content)

    with open(readmePath, "w") as readme:
        readme.write(newContent)