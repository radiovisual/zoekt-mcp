// Tiny Express app used as a verification corpus for zoekt-mcp.
//
// Intentionally kept close in shape to examples/flask-app/app.py so
// cross-language Zoekt queries like `sym:users` should surface matches
// in both files.

const express = require("express");

const app = express();

const USERS = [
  { id: 1, name: "ada", role: "admin" },
  { id: 2, name: "grace", role: "editor" },
  { id: 3, name: "linus", role: "viewer" },
];

app.get("/", function hello(_req, res) {
  res.send("Hello from express-app!");
});

app.get("/users", function listUsers(_req, res) {
  res.json({ users: USERS, count: USERS.length });
});

app.get("/users/:id", function getUser(req, res) {
  const userId = Number(req.params.id);
  const user = USERS.find((u) => u.id === userId);
  if (!user) {
    res.status(404).json({ error: "not found" });
    return;
  }
  res.json(user);
});

if (require.main === module) {
  const port = 5002;
  app.listen(port, () => {
    console.log(`express-app listening on http://127.0.0.1:${port}`);
  });
}

module.exports = app;
