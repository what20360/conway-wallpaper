const styles = `body{margin:0;background:#f1f3eb;color:#243b35;font:16px/1.9 system-ui,sans-serif}main{max-width:940px;margin:60px auto;padding:0 28px 80px}h1{font-size:36px;line-height:1.4}h2{margin-top:55px;padding-top:22px;border-top:1px solid #b9c9bc;font-size:25px}h3{font-size:19px;margin-top:30px}strong{color:#214e3b}code{background:#dde5d9;padding:2px 5px;border-radius:3px;font:14px monospace}table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:11px 14px;border-bottom:1px solid #c7d3c6;text-align:left;vertical-align:top}th{background:#dce5d7}tr:nth-child(even){background:#e9eee4}.table{overflow:auto;margin:20px 0}li{margin:8px 0}@media(prefers-color-scheme:dark){body{background:#0c171c;color:#bfcdc6}h2{border-color:#304943}strong{color:#a4dfbe}code,th{background:#1c312c}td,th{border-color:#30443c}tr:nth-child(even){background:#10221e}}@media print{body{background:white;color:black}main{margin:0;max-width:none;padding:0;font-size:11pt}h2{break-after:avoid}tr{break-inside:avoid}code,th{background:#eee}}`;

// Render the headings, tables, lists and inline notation used by MANUAL.md.
const inline = text => text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
  .replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

export function renderManual(markdown) {
  const lines = markdown.split(/\r?\n/), blocks = [];
  const separator = line => /^\|[\s:|\-]+\|$/.test(line.trim());
  let i = 0;
  while (i < lines.length) {
    const line = lines[i].trim();
    if (!line) { i++; continue; }
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      blocks.push(`<h${level}>${inline(heading[2])}</h${level}>`); i++; continue;
    }
    if (line.startsWith('|') && i + 1 < lines.length && separator(lines[i + 1])) {
      const rows = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        const row = lines[i++].trim();
        if (!separator(row)) rows.push(row.slice(1, -1).split('|').map(s => inline(s.trim())));
      }
      blocks.push('<div class="table"><table><thead><tr>' + rows[0].map(c => `<th>${c}</th>`).join('') + '</tr></thead><tbody>' + rows.slice(1).map(row => '<tr>' + row.map(c => `<td>${c}</td>`).join('') + '</tr>').join('') + '</tbody></table></div>'); continue;
    }
    const ordered = /^\d+\. /.test(line);
    if (ordered || line.startsWith('- ')) {
      const rows = [], pattern = ordered ? /^\d+\. / : /^- /;
      while (i < lines.length && pattern.test(lines[i].trim())) rows.push(`<li>${inline(lines[i++].trim().replace(pattern, ''))}</li>`);
      blocks.push(`<${ordered ? 'ol' : 'ul'}>${rows.join('')}</${ordered ? 'ol' : 'ul'}>`); continue;
    }
    const paragraph = [];
    while (i < lines.length && lines[i].trim() && !/^(#|\||- |\d+\. )/.test(lines[i].trim())) paragraph.push(lines[i++].trim());
    if (!paragraph.length) paragraph.push(lines[i++].trim());
    blocks.push(`<p>${inline(paragraph.join(' '))}</p>`);
  }
  return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>生命场 256 使用手册</title><style>' + styles + '</style></head><body><main>' + blocks.join('') + '</main></body></html>\n';
}
