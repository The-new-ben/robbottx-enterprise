import fs from 'node:fs';
import * as csstree from 'css-tree';

const css = fs.readFileSync(0, 'utf8');
const parseErrors = [];
let denialComment = false;

function normalizedWords(value) {
  return value
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[^a-z0-9]+/gi, ' ')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, ' ');
}

function hasDenialSemantics(value) {
  const normalized = normalizedWords(value);
  if (
    /\baccess (?:is )?denied\b/.test(normalized) ||
    /\baccessdenied\b/.test(normalized) ||
    /\bpermission denied\b/.test(normalized) ||
    /\bforbidden\b/.test(normalized) ||
    /\bunauthori[sz]ed\b/.test(normalized) ||
    /\brequest (?:was )?(?:blocked|denied|rejected)\b/.test(normalized) ||
    /\bweb application firewall\b/.test(normalized) ||
    /\bcloudflare ray id\b/.test(normalized) ||
    /\b(?:error(?: code)?|http|response code|status(?: code)?) (?:401|403)\b/.test(normalized) ||
    /\b(?:401|403) (?:access denied|error|forbidden|unauthori[sz]ed)\b/.test(normalized)
  ) {
    return true;
  }
  const tokens = new Set(normalized.split(' ').filter(Boolean));
  return (
    (tokens.has('401') || tokens.has('403')) &&
    [...tokens].every((token) => [
      '401',
      '403',
      'code',
      'error',
      'http',
      'message',
      'response',
      'status'
    ].includes(token))
  );
}

try {
  csstree.tokenize(css, (type, start, end) => {
    if (
      csstree.tokenNames[type] === 'comment-token' &&
      hasDenialSemantics(css.slice(start + 2, end - 2))
    ) {
      denialComment = true;
    }
  });
} catch {
  process.exit(1);
}

let ast;
try {
  ast = csstree.parse(css, {
    context: 'stylesheet',
    positions: true,
    onParseError(error) {
      parseErrors.push({
        message: error.message,
        offset: error.offset
      });
    }
  });
} catch {
  process.exit(1);
}

function validateAst(reviewedAst, reviewedParseErrors) {
  let denialContent = false;
  let invalidRawNode = false;
  let hasUsableDeclaration = false;
  let invalidSelector = false;
  const allowedRawRanges = [];

  function allowRaw(node) {
    if (node.loc) {
      allowedRawRanges.push([
        node.loc.start.offset,
        node.loc.end.offset
      ]);
    }
  }

  csstree.walk(reviewedAst, {
    enter(node) {
      if (node.type === 'Raw') {
        const declaration = this.declaration;
        const cssFunction = this.function;
        if (
          declaration?.type === 'Declaration' &&
          declaration.property.startsWith('--') &&
          declaration.value === node
        ) {
          allowRaw(node);
          return;
        }
        if (
          declaration?.type === 'Declaration' &&
          cssFunction?.type === 'Function' &&
          ['env', 'var'].includes(cssFunction.name.toLowerCase())
        ) {
          allowRaw(node);
          return;
        }
        if (
          declaration?.type === 'Declaration' &&
          declaration.property.toLowerCase() === 'filter' &&
          declaration.value === node &&
          /^alpha\(\s*opacity\s*=\s*(?:100|[0-9]{1,2})(?:\.0+)?\s*\)$/i
            .test(node.value.trim())
        ) {
          allowRaw(node);
          return;
        }
        if (
          cssFunction?.type === 'PseudoElementSelector' &&
          [
            'view-transition-group',
            'view-transition-new',
            'view-transition-old'
          ].includes(cssFunction.name.toLowerCase()) &&
          /^(?:\*|-?[_a-z][-_a-z0-9]*)$/i.test(node.value.trim())
        ) {
          allowRaw(node);
          return;
        }
        if (
          this.rule?.type === 'Rule' &&
          (declaration === null || declaration === undefined) &&
          !this.atrule?.name?.toLowerCase().endsWith('keyframes') &&
          node.value.includes('{')
        ) {
          try {
            const nestedParseErrors = [];
            const nestedAst = csstree.parse(node.value, {
              context: 'stylesheet',
              positions: true,
              onParseError(error) {
                nestedParseErrors.push({
                  message: error.message,
                  offset: error.offset
                });
              }
            });
            const nestedChildren = nestedAst.children.toArray();
            const nestedValidation = validateAst(
              nestedAst,
              nestedParseErrors
            );
            if (
              nestedChildren.length > 0 &&
              nestedChildren.every((child) => child.type === 'Rule') &&
              nestedValidation.valid &&
              nestedValidation.hasUsableDeclaration
            ) {
              hasUsableDeclaration = true;
              allowRaw(node);
              return;
            }
          } catch {
            // The Raw node remains invalid.
          }
        }
        invalidRawNode = true;
        return;
      }
      if (node.type === 'Rule') {
        const keyframes = this.atrule?.name
          ?.toLowerCase()
          .endsWith('keyframes');
        if (keyframes) {
          let keyframeCount = 0;
          if (!node.prelude?.children) {
            invalidSelector = true;
            return;
          }
          node.prelude.children.forEach((selector) => {
            keyframeCount += 1;
            if (
              !csstree.lexer.matchType(
                'keyframe-selector',
                selector
              ).matched
            ) {
              invalidSelector = true;
            }
          });
          if (keyframeCount === 0) {
            invalidSelector = true;
          }
        } else if (!node.prelude) {
          invalidSelector = true;
        }
        return;
      }
      if (node.type !== 'Declaration') {
        return;
      }
      if (
        node.property.toLowerCase() === 'content' &&
        hasDenialSemantics(csstree.generate(node.value))
      ) {
        denialContent = true;
      }
      if (csstree.generate(node.value).trim() !== '') {
        hasUsableDeclaration = true;
      }
    }
  });

  const unownedParseError = reviewedParseErrors.some((error) => (
    !Number.isInteger(error.offset) ||
    !allowedRawRanges.some(([start, end]) => (
      start <= error.offset && error.offset <= end
    ))
  ));
  return {
    valid: (
      !denialContent &&
      !invalidRawNode &&
      !invalidSelector &&
      !unownedParseError
    ),
    hasUsableDeclaration
  };
}

const validation = validateAst(ast, parseErrors);

if (
  denialComment ||
  !validation.valid ||
  !validation.hasUsableDeclaration
) {
  process.exit(1);
}
