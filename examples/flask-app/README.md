# flask-app

A tiny Flask app (~40 lines) used as part of the zoekt-mcp verification
corpus. Paired with `../express-app/` — both expose the same three routes
(`/`, `/users`, `/users/<id>`) so cross-language Zoekt queries like
`sym:users` should find matches in both.

## Run it standalone

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Then `curl http://127.0.0.1:5001/users`.

## How it's indexed

The `deploy/docker-compose.yml` stack mounts this directory into the
zoekt indexer and builds a searchable index at startup. You do **not**
need to run the Flask app for Zoekt to index its source.
