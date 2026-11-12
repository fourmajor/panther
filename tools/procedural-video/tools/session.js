// Resolves the session directory: SESSION env var or --session <dir> (relative to the project root or absolute).
const fs = require('fs'), path = require('path');
exports.session = function () {
  const root = path.join(__dirname, '..'), i = process.argv.indexOf('--session');
  const s = (i >= 0 && process.argv[i + 1]) || process.env.SESSION;
  if (!s) { console.error('No session given. Use: SESSION=sessions/<name> npm run render   (or --session <dir>)'); process.exit(2); }
  const dir = path.resolve(root, s);
  if (!fs.existsSync(path.join(dir, 'timeline.json'))) { console.error(`Session "${s}" has no timeline.json (looked in ${dir})`); process.exit(2); }
  return { root, dir, rel: path.relative(root, dir).split(path.sep).join('/'), name: path.basename(dir) };
};
