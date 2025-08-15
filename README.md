# Ted Pro — Cuddleheroes (Private)

Smart FAQ + fuzzy/typo matching + GPT fallback (OpenRouter/DeepSeek). Streamlit front end, deployable from a **private** GitHub repo.

## Local Run

1. Python 3.10+ recommended.
2. `pip install -r requirements.txt`
3. Set environment variable:
   - macOS/Linux: `export OPENROUTER_API_KEY=sk-xxxx`
   - Windows (CMD): `set OPENROUTER_API_KEY=sk-xxxx`
4. `streamlit run tedpro_front.py`

## Files
- `tedpro_front.py`: Streamlit app entry
- `hybrid_engine.py`: FAQ + LLM hybrid logic (OpenRouter)
- `faqs.json`, `client_faq.json`: FAQs (merged)
- `api_integrations.py`: Optional Twilio hooks (safe if no creds)
- `requirements.txt`: No local modules here
- `.gitignore`: Ignores `.env` and `secrets/`

## Deployment (Streamlit Community Cloud, Private Repo)
- Ensure Streamlit OAuth has **access to private repos** in GitHub (Authorized OAuth Apps → Streamlit → repo access).
- App URL: point to repo `https://github.com/<you>/Ted-Pro` and main file `tedpro_front.py`.
- Add `OPENROUTER_API_KEY` in **Streamlit Secrets** or GitHub Repository Secrets.

## Tips
- Keep repo private; never commit `.env` or keys.
- Add/modify FAQs in `client_faq.json` to tailor answers.
- Change model via sidebar (DeepSeek free model works to start).

