const fs = require("fs");
const path = require("path");

const srcDir = path.join(__dirname, "src");
const coreApiFile = path.join(srcDir, "core", "api.js");
const utilsDir = path.join(srcDir, "utils");
const requestFile = path.join(utilsDir, "request.js");

if (!fs.existsSync(utilsDir)) {
  fs.mkdirSync(utilsDir, { recursive: true });
}

if (fs.existsSync(coreApiFile)) {
  fs.renameSync(coreApiFile, requestFile);
  console.log("Moved core/api.js to utils/request.js");
}

function processFiles(dir) {
  const files = fs.readdirSync(dir);
  for (const file of files) {
    const filePath = path.join(dir, file);
    const stat = fs.statSync(filePath);
    if (stat.isDirectory()) {
      processFiles(filePath);
    } else if (filePath.endsWith(".vue") || filePath.endsWith(".js")) {
      let content = fs.readFileSync(filePath, "utf8");
      const original = content;
      // Replacements
      content = content.replace(/['"](.*?)core\/api['"]/g, "'@/utils/request'");
      content = content.replace(/['"]@\/core\/api['"]/g, "'@/utils/request'");

      if (content !== original) {
        fs.writeFileSync(filePath, content);
        console.log("Updated imports in", filePath);
      }
    }
  }
}

processFiles(srcDir);
console.log("Migration complete.");
