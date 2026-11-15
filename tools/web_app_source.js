// The web app is one program in several classic scripts (serve/web/app-01-util.js ... app.js, loaded in this order by
// index.html).  Tests and tools that read its source go through here.
const fs = require("fs");
const path = require("path");
const WEB = path.join(__dirname, "..", "serve", "web");
function appJsPaths() {
  const parts = fs.readdirSync(WEB).filter((f) => /^app-\d\d-.*\.js$/.test(f)).sort().map((f) => path.join(WEB, f));
  return parts.concat([path.join(WEB, "app.js")]);
}
function appJsText() { return appJsPaths().map((p) => fs.readFileSync(p, "utf8")).join("\n"); }
module.exports = { appJsPaths, appJsText };
