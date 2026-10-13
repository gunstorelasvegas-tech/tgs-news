# Publishing TGS News on BizlyApp (via GitHub Pages)

BizlyApp can't run a scheduled Python job, so GitHub does the updating and hosting (free),
and your BizlyApp page shows it with one pasted code block.

```
GitHub Actions (every 30 min) -> rebuilds feed.json -> publishes to GitHub Pages
BizlyApp page  --(iframe)-->  https://YOUR-USERNAME.github.io/YOUR-REPO/
```

## One-time setup (~10 minutes)

1. **Create a GitHub repo** (github.com -> New). Make it **Public** (free GitHub Pages requires public
   unless you have a paid plan). Name it e.g. `tgs-news`.
2. **Upload this whole project folder** to the repo (keep the `.github/workflows/update.yml` file and the
   `public/` folder). Easiest: GitHub Desktop, or on the repo page "Add file -> Upload files".
   Make sure the default branch is called `main`.
3. In the repo: **Settings -> Pages -> Build and deployment -> Source: "GitHub Actions"**.
4. Go to the **Actions** tab -> "Update and publish TGS News" -> **Run workflow**. After ~1-2 minutes,
   your site is live at `https://YOUR-USERNAME.github.io/YOUR-REPO/`. Open it to confirm it works.
5. **In BizlyApp**, add a *Custom HTML / Embed* block on your page and paste the contents of
   `bizly-embed.html` (after replacing `YOUR-USERNAME` and `YOUR-REPO`). Publish.

From now on the feed refreshes every 30 minutes by itself; nothing to run on your computer.

## Notes

- If your BizlyApp block strips `<script>`, the iframe still works; it just uses a fixed height
  (change `min-height:900px` to something larger like `4000px`, or remove `scrolling="no"` for an inner scrollbar).
- GitHub pauses scheduled workflows after 60 days with no repo activity. If updates stop, open the Actions tab
  and click *Enable* / *Run workflow* (or make any small edit).
- Scheduled runs can lag a few minutes at busy times.
- Prefer your own domain? In Settings -> Pages you can add a custom domain (e.g. `news.yourstore.com`).
- Changing the design later: edit `public/index.html`, commit, and it redeploys automatically.

---

# Other hosting (own server / VPS)

The site is static: the `public/` folder. Upload it, and run the updater on a schedule:

```
*/30 * * * * python3 /home/you/tgs/update_feed.py --out /var/www/html/news      # Linux cron
python.exe C:\tgs\update_feed.py --out C:\inetpub\wwwroot\news                  # Windows Task Scheduler
```

Needs Python 3.8+ (no extra packages). Do not open `index.html` by double-clicking; serve it through a web server.
If a fetch fails the updater keeps the previous `feed.json`. `serve.py` is only for local testing.
