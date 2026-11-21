# The Model Desk (hosted)

Every morning around 6:30, a GitHub Action reports a fresh edition of The Model Desk: two stories each in
Architectures, Training, Theory, In Practice, Robotics, and Discoveries (scientific advances made with AI), the
day's catch-up primer, a Throwback to a landmark
idea in ML history, and a deeper explainer for every story. It publishes the edition as a website. At 7:00 you get an email with the headlines, and each
headline opens straight to its story.

## Setup (about 20 minutes)

1. **Create a public GitHub repository** (free GitHub Pages sites need a public repo) and upload everything in
   this folder, including the hidden `.github` folder and `docs/.nojekyll`.
2. **Turn on Pages:** Settings > Pages > Source: **GitHub Actions**.
3. **Add secrets** under Settings > Secrets and variables > Actions > Secrets:
   - `ANTHROPIC_API_KEY` from https://platform.claude.com
   - `SMTP_USER`: your Gmail address
   - `SMTP_PASSWORD`: a Gmail app password (Google Account > Security > 2-Step Verification > App passwords)
   - `MAIL_TO`: where the reminder should go
4. **Add variables** on the Variables tab of the same page:
   - `SITE_URL`: `https://<your-username>.github.io/<repo-name>/`
   - `TIMEZONE` (optional): defaults to `America/New_York`. Use any IANA name, like `America/Chicago`.
5. **Print the first edition:** Actions tab > "Print The Model Desk" > Run workflow. It takes a few minutes.
   Then open your `SITE_URL`.
6. **Test the email:** Actions tab > "Morning reminder email" > Run workflow.

## House style

Every piece follows one style, set in `STYLE` in `build_edition.py`: acronyms are spelled out on first use,
every term is defined when it appears, every symbol is explained after each equation, and intuition comes
before math. Each story ends with three "Remember" sentences. Both fact-check passes also enforce the style.
To adjust it, edit that one block.

## Discoveries

Each Discoveries story opens with the backstory (the problem or theorem stated precisely, who posed it and when,
and the best earlier results), then explains what the AI system did, then gives a verification status: peer
reviewed, formally verified, independently reproduced, or only claimed. A second pass searches the web to check
every name, date, and number. The first story each day rotates through mathematics, protein science, formal
verification, biology and medicine, chemistry and materials, and physics and weather.

## Adding a section

Add an entry to `SECTIONS` in `build_edition.py` with an `id`, `name`, and `brief` describing what it covers.
Optional settings: `days` (how far back to search), `focus` (topics to rotate through), `backstory` (write the
history first), and `fact_check` (verify claims with a second search). The site and email pick it up the next
morning.

## Reprinting one section

To redo part of today's edition, run the "Print The Model Desk" workflow with **force** checked and **only** set
to the sections you want, such as `primer` or `primer,throwback`. From the terminal:
`gh workflow run print.yml -f force=true -f only=primer`. Everything else in the edition stays as it was.

## How the Throwback stays accurate

Throwback topics live in `THROWBACKS` in `build_edition.py`, each with a curated list of the original papers
(authors, year, venue, and an arXiv link where one exists). Claude may cite only those papers, a second
fact-checking pass removes anything the references don't support, and the "Key publications" list on each
story comes straight from the curated list rather than from the model. To add a topic, add an entry there.

## Time zones

The schedules are set for US Eastern and cover both daylight and standard time. If you set a different
`TIMEZONE`, change the `cron` lines (they're in UTC) so one print run falls between 6:00 and 6:59 local time and
one reminder run falls between 7:00 and 7:59. GitHub can start scheduled runs several minutes late, which is why
printing starts around 6:30.

## Cost and adjustments

Each edition makes about 27 requests: one web search per section, a web-search fact-check of each Discoveries
story, a fact-check pass on the primer and Throwback, and a deeper explainer for every story. Check your usage
on the Claude Console after the first few days. To trim the cost, add `DEEPER: "0"` to the print step's `env` to
skip the explainers, or set `MODEL` to a smaller model.

If you'd rather get the reminder from Google Calendar, delete `.github/workflows/remind.yml` and skip the
SMTP secrets.

GitHub pauses scheduled workflows in a public repo after 60 days without activity. If the emails stop, open
the Actions tab and re-enable the workflow.
