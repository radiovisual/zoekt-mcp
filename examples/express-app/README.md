# express-app

A tiny Express app (~40 lines) used as part of the zoekt-mcp verification
corpus. Paired with `../flask-app/` — both expose the same three routes
(`/`, `/users`, `/users/:id`) so cross-language Zoekt queries like
`sym:users` should find matches in both.

## Run it standalone

```bash
npm install
npm start
```

Then `curl http://127.0.0.1:5002/users`.

## How it's indexed

The `deploy/docker-compose.yml` stack mounts this directory into the
zoekt indexer and builds a searchable index at startup. You do **not**
need to run the Express app for Zoekt to index its source.
