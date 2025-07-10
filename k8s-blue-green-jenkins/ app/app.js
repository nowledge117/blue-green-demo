const http = require('http');

const port = 3000;
// Change this version for new deployments
const APP_VERSION = "1.0 (BLUE)";

const server = http.createServer((req, res) => {
  res.statusCode = 200;
  res.setHeader('Content-Type', 'text/plain');
  res.end(`Hello, Kubernetes! Version: ${APP_VERSION}\n`);
});

server.listen(port, () => {
  console.log(`Server running on port ${port}, version ${APP_VERSION}`);
});