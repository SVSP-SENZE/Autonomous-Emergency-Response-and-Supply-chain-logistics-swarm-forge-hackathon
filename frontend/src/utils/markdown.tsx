import React from 'react';

interface Block {
  kind: 'h1' | 'h2' | 'h3' | 'p' | 'ul' | 'ol' | 'table' | 'hr';
  lines: string[];
}

/**
 * Minimal, dependency-free Markdown renderer for AI assistant messages.
 * Supports headings, bold/inline-code/links, lists, tables and paragraphs —
 * enough for structured operational summaries. Never uses dangerouslySetInnerHTML.
 */
export function renderMarkdown(source: string): React.ReactNode {
  const blocks = parseBlocks(source);
  return blocks.map((block, index) => (
    <React.Fragment key={index}>{renderBlock(block)}</React.Fragment>
  ));
}

function parseBlocks(source: string): Block[] {
  const lines = source.replace(/\r\n/g, '\n').split('\n');
  const blocks: Block[] = [];
  let current: Block | null = null;

  const push = () => {
    if (current) {
      blocks.push(current);
      current = null;
    }
  };

  for (const line of lines) {
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    const ordered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    const bullet = /^\s*[-*]\s+(.*)$/.exec(line);
    const table = /^\s*\|.*\|\s*$/.test(line);
    const hr = /^\s*(---+|\*\*\*+)\s*$/.test(line);

    if (heading) {
      push();
      current = { kind: (`h${heading[1].length}` as 'h1' | 'h2' | 'h3'), lines: [heading[2]] };
      push();
    } else if (hr) {
      push();
      blocks.push({ kind: 'hr', lines: [] });
    } else if (table) {
      if (current?.kind !== 'table') push();
      current = current ?? { kind: 'table', lines: [] };
      current.lines.push(line);
    } else if (bullet) {
      if (current?.kind !== 'ul') push();
      current = current ?? { kind: 'ul', lines: [] };
      current.lines.push(bullet[1]);
    } else if (ordered) {
      if (current?.kind !== 'ol') push();
      current = current ?? { kind: 'ol', lines: [] };
      current.lines.push(ordered[1]);
    } else if (line.trim() === '') {
      push();
    } else {
      if (current?.kind !== 'p') push();
      current = current ?? { kind: 'p', lines: [] };
      current.lines.push(line.trim());
    }
  }
  push();
  return blocks;
}

function renderBlock(block: Block): React.ReactNode {
  switch (block.kind) {
    case 'h1':
      return <h3 key="h">{inline(block.lines.join(' '))}</h3>;
    case 'h2':
      return <h4 key="h">{inline(block.lines.join(' '))}</h4>;
    case 'h3':
      return <h5 key="h">{inline(block.lines.join(' '))}</h5>;
    case 'hr':
      return <hr key="h" />;
    case 'p':
      return <p key="p">{block.lines.map((line, i) => <React.Fragment key={i}>{inline(line)}{i < block.lines.length - 1 ? ' ' : ''}</React.Fragment>)}</p>;
    case 'ul':
      return <ul key="u">{block.lines.map((l, i) => <li key={i}>{inline(l)}</li>)}</ul>;
    case 'ol':
      return <ol key="o">{block.lines.map((l, i) => <li key={i}>{inline(l)}</li>)}</ol>;
    case 'table':
      return <Table key="t" lines={block.lines} />;
    default:
      return null;
  }
}

function Table({ lines }: { lines: string[] }): React.ReactNode {
  const isSeparator = (l: string) => /^[\s|:-]+$/.test(l);
  const parse = (l: string) =>
    l
      .trim()
      .replace(/^\||\|$/g, '')
      .split('|')
      .map((c) => c.trim());

  const body = lines.filter((l) => !isSeparator(l));
  if (body.length === 0) return null;
  const header = parse(body[0]);
  const dataRows = body.slice(1).map(parse);

  return (
    <table className="md-table">
      <thead>
        <tr>{header.map((cell, i) => <th key={i}>{inline(cell)}</th>)}</tr>
      </thead>
      <tbody>
        {dataRows.map((row, r) => (
          <tr key={r}>{row.map((cell, c) => <td key={c}>{inline(cell)}</td>)}</tr>
        ))}
      </tbody>
    </table>
  );
}

/** Inline formatting: **bold**, `code`, [text](url). Text only — no raw HTML. */
function inline(text: string): React.ReactNode {
  const nodes: React.ReactNode[] = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) nodes.push(text.slice(lastIndex, match.index));
    const token = match[0];
    if (token.startsWith('**')) {
      nodes.push(<strong key={key++}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith('`')) {
      nodes.push(<code key={key++}>{token.slice(1, -1)}</code>);
    } else {
      const linkMatch = /\[([^\]]+)\]\(([^)]+)\)/.exec(token);
      if (linkMatch) {
        nodes.push(
          <a key={key++} href={linkMatch[2]} target="_blank" rel="noreferrer">
            {linkMatch[1]}
          </a>,
        );
      } else {
        nodes.push(token);
      }
    }
    lastIndex = match.index + token.length;
  }
  if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
  return nodes;
}
