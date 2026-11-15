# Security

## Run it locally, not on the open internet

Smriti is built to run on your own machine. The API (`app.api`, FastAPI on port 8010) has **no login and no rate limiting**, and the frontend dev server is not a production server. Don't expose either one to the internet as they are. If you host Smriti for others, put it behind authentication and a proper reverse proxy first.

Keep secrets in `.env` (git-ignored). Never commit it.

## Reporting a vulnerability

Please don't open a public issue for security problems. Use GitHub's private reporting instead: the **Security** tab of this repository, then **Report a vulnerability**. You'll get a reply as soon as possible.
