name: WakaTime Readme

on:
  push:
    branches:
      - master
  schedule:
    - cron: '0 19 * * *'

jobs:
  update-readme:
    runs-on: ubuntu-latest
    steps:
      - uses: athul/waka-readme@master
        with:
          WAKATIME_API_KEY: ${{ secrets.WAKATIME_API_KEY }}
