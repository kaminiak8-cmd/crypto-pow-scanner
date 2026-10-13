name: daily-scan
on:
  schedule:
    - cron: "0 6 * * *"
  workflow_dispatch:

permissions:
  contents: write

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install requests pandas tabulate
      - run: python scanner.py
        env:
          GH_TOKEN: ${{ secrets.GH_PAT }}
          CG_KEY: ${{ secrets.CG_KEY }}
      - run: |
          git config user.name "bot"
          git config user.email "bot@users.noreply.github.com"
          git add -A
          git commit -m "daily scan" || echo "nothing to commit"
          git push
