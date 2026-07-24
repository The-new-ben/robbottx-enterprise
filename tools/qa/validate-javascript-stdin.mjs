import fs from 'node:fs';
import { parseModule, parseScript } from 'meriyah';

const source = fs.readFileSync(0, 'utf8');
const moduleMode = process.argv.includes('--module');

let program;
try {
  program = moduleMode
    ? parseModule(source, { next: true })
    : parseScript(source, { next: true });
} catch {
  process.exit(1);
}

if (program.body.length === 0) {
  process.exit(1);
}

function normalizedWords(value) {
  return String(value)
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[^a-z0-9]+/gi, ' ')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, ' ');
}

function hasDenialSemantics(value) {
  const normalized = normalizedWords(value);
  return (
    /\baccess (?:is )?denied\b/.test(normalized) ||
    /\baccessdenied\b/.test(normalized) ||
    /\bforbidden\b/.test(normalized) ||
    /\bunauthori[sz]ed\b/.test(normalized) ||
    /\b(?:error|http|status(?: code)?) (?:401|403)\b/.test(normalized) ||
    /\b(?:401|403)(?: access denied| error| forbidden| unauthori[sz]ed)?\b/.test(normalized)
  );
}

function memberName(node, strings) {
  if (!node || node.type !== 'MemberExpression') {
    return null;
  }
  if (!node.computed && node.property.type === 'Identifier') {
    return node.property.name;
  }
  return staticString(node.property, strings);
}

function staticString(node, strings) {
  if (!node) {
    return null;
  }
  if (node.type === 'Literal') {
    return ['string', 'number'].includes(typeof node.value)
      ? String(node.value)
      : null;
  }
  if (node.type === 'Identifier') {
    return strings.has(node.name) ? strings.get(node.name) : null;
  }
  if (
    node.type === 'TemplateLiteral' &&
    node.quasis.length === node.expressions.length + 1
  ) {
    let value = '';
    for (let index = 0; index < node.quasis.length; index += 1) {
      value += node.quasis[index].value.cooked ?? '';
      if (index < node.expressions.length) {
        const expression = staticString(node.expressions[index], strings);
        if (expression === null) {
          return null;
        }
        value += expression;
      }
    }
    return value;
  }
  if (node.type === 'BinaryExpression' && node.operator === '+') {
    const left = staticString(node.left, strings);
    const right = staticString(node.right, strings);
    return left === null || right === null ? null : left + right;
  }
  if (
    node.type === 'CallExpression' &&
    node.callee.type === 'Identifier' &&
    [
      'String',
      'atob',
      'decodeURI',
      'decodeURIComponent'
    ].includes(node.callee.name) &&
    node.arguments.length === 1
  ) {
    const argument = staticString(node.arguments[0], strings);
    if (argument === null) {
      return null;
    }
    if (node.callee.name === 'String') {
      return argument;
    }
    try {
      if (node.callee.name === 'decodeURI') {
        return decodeURI(argument);
      }
      if (node.callee.name === 'decodeURIComponent') {
        return decodeURIComponent(argument);
      }
      return Buffer.from(argument, 'base64').toString('utf8');
    } catch {
      return null;
    }
  }
  if (
    node.type === 'CallExpression' &&
    node.callee.type === 'MemberExpression' &&
    memberName(node.callee, strings) === 'join' &&
    node.callee.object.type === 'ArrayExpression'
  ) {
    const separator = node.arguments.length === 0
      ? ','
      : staticString(node.arguments[0], strings);
    const values = node.callee.object.elements.map(
      (element) => staticString(element, strings)
    );
    return separator === null || values.includes(null)
      ? null
      : values.join(separator);
  }
  if (
    node.type === 'CallExpression' &&
    node.callee.type === 'MemberExpression' &&
    node.callee.object.type === 'Identifier' &&
    node.callee.object.name === 'document' &&
    memberName(node.callee, strings) === 'createTextNode' &&
    node.arguments.length === 1
  ) {
    return staticString(node.arguments[0], strings);
  }
  if (
    node.type === 'CallExpression' &&
    node.callee.type === 'MemberExpression' &&
    node.callee.object.type === 'Identifier' &&
    node.callee.object.name === 'String' &&
    memberName(node.callee, strings) === 'fromCharCode'
  ) {
    const codes = node.arguments.map((argument) => (
      argument.type === 'Literal' &&
      typeof argument.value === 'number' &&
      Number.isInteger(argument.value)
        ? argument.value
        : null
    ));
    return codes.includes(null)
      ? null
      : String.fromCharCode(...codes);
  }
  if (
    node.type === 'CallExpression' &&
    node.callee.type === 'MemberExpression' &&
    memberName(node.callee, strings) === 'concat'
  ) {
    const base = staticString(node.callee.object, strings);
    const values = node.arguments.map(
      (argument) => staticString(argument, strings)
    );
    return base === null || values.includes(null)
      ? null
      : base.concat(...values);
  }
  if (
    node.type === 'NewExpression' &&
    node.callee.type === 'Identifier' &&
    node.callee.name === 'Text' &&
    node.arguments.length === 1
  ) {
    return staticString(node.arguments[0], strings);
  }
  return null;
}

function referenceKind(node, context) {
  if (!node) {
    return null;
  }
  if (node.type === 'Identifier') {
    if (node.name === 'document') {
      return 'document';
    }
    return context.references.get(node.name) ?? null;
  }
  if (node.type === 'MemberExpression') {
    const objectKind = referenceKind(node.object, context);
    const property = memberName(node, context.strings);
    if (
      ['globalThis', 'self', 'window'].includes(
        node.object.type === 'Identifier' ? node.object.name : ''
      ) &&
      property === 'document'
    ) {
      return 'document';
    }
    if (
      objectKind === 'document' &&
      ['body', 'documentElement'].includes(property)
    ) {
      return property;
    }
  }
  if (
    node.type === 'CallExpression' &&
    node.callee.type === 'MemberExpression'
  ) {
    const objectKind = referenceKind(node.callee.object, context);
    const method = memberName(node.callee, context.strings);
    const selector = staticString(node.arguments[0], context.strings);
    if (
      objectKind === 'document' &&
      method === 'querySelector'
    ) {
      if (selector === 'body') {
        return 'body';
      }
      if (selector === 'html') {
        return 'documentElement';
      }
      return 'connectedElement';
    }
    if (objectKind === 'document' && method === 'getElementById') {
      return 'connectedElement';
    }
    if (objectKind === 'document' && method === 'createElement') {
      return 'createdElement';
    }
    if (
      ['body', 'connectedElement', 'createdElement'].includes(objectKind)
      && ['closest', 'querySelector'].includes(method)
    ) {
      return objectKind === 'createdElement'
        ? 'createdElement'
        : 'connectedElement';
    }
    if (
      node.callee.object.type === 'Identifier' &&
      node.callee.object.name === 'Object' &&
      method === 'assign'
    ) {
      return referenceKind(node.arguments[0], context);
    }
  }
  return null;
}

function referencedIdentifier(node) {
  return node?.type === 'Identifier' ? node.name : null;
}

function denialValue(node, context) {
  const value = staticString(node, context.strings);
  if (value !== null && hasDenialSemantics(value)) {
    return true;
  }
  if (
    node?.type === 'Identifier' &&
    context.denialReferences.has(node.name)
  ) {
    return true;
  }
  if (
    node?.type === 'CallExpression' &&
    node.callee.type === 'MemberExpression' &&
    node.callee.object.type === 'Identifier' &&
    node.callee.object.name === 'Object' &&
    memberName(node.callee, context.strings) === 'assign'
  ) {
    return node.arguments.slice(1).some((argument) => (
      argument.type === 'ObjectExpression' &&
      argument.properties.some((property) => (
        property.type === 'Property' &&
        property.kind === 'init' &&
        denialValue(property.value, context)
      ))
    ));
  }
  return false;
}

function safeDomContentValue(node, context) {
  if (
    node?.type === 'Identifier' &&
    context.safeDomContentReferences.has(node.name)
  ) {
    return true;
  }
  if (node?.type !== 'MemberExpression') {
    return false;
  }
  return (
    ['body', 'connectedElement', 'documentElement'].includes(
      referenceKind(node.object, context)
    ) &&
    [
      'innerHTML',
      'innerText',
      'outerHTML',
      'textContent'
    ].includes(memberName(node, context.strings))
  );
}

function markDenialReference(node, context) {
  const identifier = referencedIdentifier(node);
  if (identifier !== null) {
    context.denialReferences.add(identifier);
  }
}

function activeDenialSink(node, context) {
  if (!node) {
    return false;
  }
  if (
    node.type === 'AssignmentExpression' &&
    node.left.type === 'MemberExpression'
  ) {
    const target = referenceKind(node.left.object, context);
    const property = memberName(node.left, context.strings);
    const staticValue = staticString(node.right, context.strings);
    const isUnsafe = (
      (
        staticValue === null &&
        !safeDomContentValue(node.right, context)
      )
      || denialValue(node.right, context)
    );
    if (
      ['body', 'connectedElement', 'documentElement'].includes(target) &&
      [
        'innerHTML',
        'innerText',
        'outerHTML',
        'textContent'
      ].includes(property) &&
      isUnsafe
    ) {
      return true;
    }
    if (
      target === 'createdElement' &&
      [
        'innerHTML',
        'innerText',
        'outerHTML',
        'textContent'
      ].includes(property) &&
      isUnsafe
    ) {
      markDenialReference(node.left.object, context);
    }
  }
  if (
    node.type === 'CallExpression' &&
    node.callee.type === 'MemberExpression'
  ) {
    const target = referenceKind(node.callee.object, context);
    const method = memberName(node.callee, context.strings);
    const containsUnsafe = node.arguments.some(
      (argument) => (
        staticString(argument, context.strings) === null
        || denialValue(argument, context)
      )
    );
    if (
      (
        target === 'document' &&
        ['write', 'writeln'].includes(method) &&
        containsUnsafe
      ) ||
      (
        ['body', 'connectedElement', 'documentElement'].includes(target) &&
        [
          'append',
          'appendChild',
          'insertBefore',
          'insertAdjacentHTML',
          'insertAdjacentText',
          'prepend',
          'replaceChildren',
          'replaceWith'
        ].includes(method) &&
        containsUnsafe
      )
    ) {
      return true;
    }
    if (
      target === 'createdElement' &&
      [
        'append',
        'appendChild',
        'insertBefore',
        'insertAdjacentHTML',
        'insertAdjacentText',
        'prepend',
        'replaceChildren'
      ].includes(method) &&
      containsUnsafe
    ) {
      markDenialReference(node.callee.object, context);
    }
  }
  if (
    node.type === 'CallExpression' &&
    node.callee.type === 'MemberExpression' &&
    node.callee.object.type === 'Identifier' &&
    node.callee.object.name === 'Object' &&
    memberName(node.callee, context.strings) === 'assign'
  ) {
    const unsafeProperty = node.arguments.slice(1).some((argument) => (
      argument.type === 'ObjectExpression' &&
      argument.properties.some((property) => {
        if (
          property.type !== 'Property' ||
          property.kind !== 'init'
        ) {
          return false;
        }
        const name = property.computed
          ? staticString(property.key, context.strings)
          : (
            property.key.type === 'Identifier'
              ? property.key.name
              : staticString(property.key, context.strings)
          );
        return (
          [
            'innerHTML',
            'innerText',
            'outerHTML',
            'textContent'
          ].includes(name) &&
          (
            staticString(property.value, context.strings) === null
            || denialValue(property.value, context)
          )
        );
      })
    ));
    const target = referenceKind(node.arguments[0], context);
    if (
      unsafeProperty &&
      ['body', 'connectedElement', 'documentElement'].includes(target)
    ) {
      return true;
    }
    if (unsafeProperty && target === 'createdElement') {
      markDenialReference(node.arguments[0], context);
    }
  }
  if (
    node.type === 'CallExpression' &&
    node.callee.type === 'MemberExpression' &&
    node.callee.object.type === 'Identifier' &&
    node.callee.object.name === 'Object' &&
    memberName(node.callee, context.strings) === 'defineProperty'
  ) {
    const target = referenceKind(node.arguments[0], context);
    const property = staticString(node.arguments[1], context.strings);
    const descriptor = node.arguments[2];
    const unsafeDescriptor = (
      descriptor?.type !== 'ObjectExpression'
      || descriptor.properties.some((candidate) => (
        candidate.type === 'Property' &&
        (
          candidate.key.type === 'Identifier'
            ? candidate.key.name
            : staticString(candidate.key, context.strings)
        ) === 'value' &&
        (
          staticString(candidate.value, context.strings) === null
          || denialValue(candidate.value, context)
        )
      ))
    );
    if (
      [
        'innerHTML',
        'innerText',
        'outerHTML',
        'textContent'
      ].includes(property) &&
      unsafeDescriptor
    ) {
      if (
        ['body', 'connectedElement', 'documentElement'].includes(target)
      ) {
        return true;
      }
      if (target === 'createdElement') {
        markDenialReference(node.arguments[0], context);
      }
    }
  }
  return false;
}

function forkContext(context) {
  return {
    activeFunctions: new Set(context.activeFunctions),
    denialReferences: new Set(context.denialReferences),
    functions: new Map(context.functions),
    references: new Map(context.references),
    safeDomContentReferences: new Set(
      context.safeDomContentReferences
    ),
    strings: new Map(context.strings),
  };
}

function invokeFunction(callable, argumentsValue, context) {
  if (
    !callable ||
    ![
      'ArrowFunctionExpression',
      'FunctionDeclaration',
      'FunctionExpression'
    ].includes(callable.type) ||
    context.activeFunctions.has(callable)
  ) {
    return false;
  }
  const nested = forkContext(context);
  nested.activeFunctions.add(callable);
  callable.params.forEach((parameter, index) => {
    if (parameter.type !== 'Identifier' || index >= argumentsValue.length) {
      return;
    }
    const argument = argumentsValue[index];
    const stringValue = staticString(argument, context.strings);
    const reference = referenceKind(argument, context);
    if (stringValue !== null) {
      nested.strings.set(parameter.name, stringValue);
    }
    if (reference !== null) {
      nested.references.set(parameter.name, reference);
    }
    if (denialValue(argument, context)) {
      nested.denialReferences.add(parameter.name);
    }
    if (safeDomContentValue(argument, context)) {
      nested.safeDomContentReferences.add(parameter.name);
    }
    if (
      argument.type === 'Identifier' &&
      context.functions.has(argument.name)
    ) {
      nested.functions.set(
        parameter.name,
        context.functions.get(argument.name)
      );
    }
  });
  return callable.body.type === 'BlockStatement'
    ? analyzeStatements(callable.body.body, nested)
    : analyzeExpression(callable.body, nested);
}

function analyzeCallback(node, context) {
  if (!node) {
    return false;
  }
  if (
    ['ArrowFunctionExpression', 'FunctionExpression'].includes(node.type)
  ) {
    return invokeFunction(node, [], context);
  }
  if (node.type === 'Identifier' && context.functions.has(node.name)) {
    return invokeFunction(context.functions.get(node.name), [], context);
  }
  return analyzeExpression(node, context);
}

function analyzeExpression(node, context) {
  if (!node || activeDenialSink(node, context)) {
    return Boolean(node);
  }
  if (node.type === 'SequenceExpression') {
    return node.expressions.some((expression) =>
      analyzeExpression(expression, context)
    );
  }
  if (node.type === 'ConditionalExpression') {
    return (
      analyzeExpression(node.test, context) ||
      analyzeExpression(node.consequent, forkContext(context)) ||
      analyzeExpression(node.alternate, forkContext(context))
    );
  }
  if (['BinaryExpression', 'LogicalExpression'].includes(node.type)) {
    return (
      analyzeExpression(node.left, context) ||
      analyzeExpression(node.right, context)
    );
  }
  if (
    [
      'AwaitExpression',
      'ChainExpression',
      'SpreadElement',
      'UnaryExpression'
    ].includes(node.type)
  ) {
    return analyzeExpression(node.argument ?? node.expression, context);
  }
  if (node.type === 'AssignmentExpression') {
    if (
      node.left.type === 'Identifier' &&
      ['=', '&&=', '||=', '??='].includes(node.operator)
    ) {
      const stringValue = staticString(node.right, context.strings);
      const reference = referenceKind(node.right, context);
      if (stringValue !== null) {
        context.strings.set(node.left.name, stringValue);
      }
      if (reference !== null) {
        context.references.set(node.left.name, reference);
      }
      if (denialValue(node.right, context)) {
        context.denialReferences.add(node.left.name);
      }
      if (safeDomContentValue(node.right, context)) {
        context.safeDomContentReferences.add(node.left.name);
      }
      if (
        node.right.type === 'Identifier' &&
        context.functions.has(node.right.name)
      ) {
        context.functions.set(
          node.left.name,
          context.functions.get(node.right.name)
        );
      }
    }
    if (
      node.left.type === 'MemberExpression' &&
      /^on(?:DOMContentLoaded|load|readystatechange)$/iu.test(
        memberName(node.left, context.strings) || ''
      )
    ) {
      return analyzeCallback(node.right, context);
    }
    return analyzeExpression(node.right, context);
  }
  if (node.type === 'ArrayExpression') {
    return node.elements.some(
      (element) => analyzeExpression(element, context)
    );
  }
  if (node.type === 'ObjectExpression') {
    return node.properties.some((property) => (
      property.type === 'SpreadElement'
        ? analyzeExpression(property.argument, context)
        : (
          analyzeExpression(property.key, context) ||
          analyzeExpression(property.value, context)
        )
    ));
  }
  if (node.type === 'TemplateLiteral') {
    return node.expressions.some(
      (expression) => analyzeExpression(expression, context)
    );
  }
  if (node.type === 'NewExpression') {
    return node.arguments.some(
      (argument) => analyzeExpression(argument, context)
    );
  }
  if (node.type !== 'CallExpression') {
    return false;
  }
  const callable = node.callee;
  const invokedCallable = callable.type === 'SequenceExpression'
    ? callable.expressions[callable.expressions.length - 1]
    : callable;
  if (
    invokedCallable?.type === 'Identifier' &&
    invokedCallable.name === 'eval'
  ) {
    return true;
  }
  if (
    (
      callable.type === 'NewExpression' &&
      callable.callee.type === 'Identifier' &&
      callable.callee.name === 'Function'
    ) ||
    (
      callable.type === 'CallExpression' &&
      callable.callee.type === 'Identifier' &&
      callable.callee.name === 'Function'
    )
  ) {
    return true;
  }
  if (
    ['ArrowFunctionExpression', 'FunctionExpression'].includes(
      callable.type
    )
  ) {
    return invokeFunction(callable, node.arguments, context);
  }
  if (
    callable.type === 'Identifier' &&
    context.functions.has(callable.name)
  ) {
    return invokeFunction(
      context.functions.get(callable.name),
      node.arguments,
      context
    );
  }
  if (
    callable.type === 'Identifier' &&
    [
      'queueMicrotask',
      'requestAnimationFrame',
      'setImmediate',
      'setInterval',
      'setTimeout'
    ].includes(callable.name) &&
    (
      staticString(node.arguments[0], context.strings) !== null
      || analyzeCallback(node.arguments[0], context)
    )
  ) {
    return true;
  }
  if (
    callable.type === 'MemberExpression' &&
    ['catch', 'finally', 'then'].includes(
      memberName(callable, context.strings)
    ) &&
    node.arguments.some((argument) => analyzeCallback(argument, context))
  ) {
    return true;
  }
  if (
    callable.type === 'MemberExpression' &&
    memberName(callable, context.strings) === 'addEventListener'
  ) {
    const eventName = staticString(node.arguments[0], context.strings);
    const callback = node.arguments[1];
    if (
      ['DOMContentLoaded', 'load', 'readystatechange'].includes(eventName) &&
      analyzeCallback(callback, context)
    ) {
      return true;
    }
  }
  if (analyzeExpression(callable, context)) {
    return true;
  }
  return node.arguments.some((argument) =>
    analyzeExpression(argument, context)
  );
}

function analyzeVariableDeclaration(statement, context) {
  for (const declaration of statement.declarations) {
    if (!declaration.init) {
      continue;
    }
    if (declaration.id.type === 'ObjectPattern') {
      const sourceKind = referenceKind(declaration.init, context);
      if (sourceKind === 'document') {
        for (const property of declaration.id.properties) {
          if (
            property.type !== 'Property' ||
            property.value.type !== 'Identifier'
          ) {
            continue;
          }
          const name = property.computed
            ? staticString(property.key, context.strings)
            : (
              property.key.type === 'Identifier'
                ? property.key.name
                : staticString(property.key, context.strings)
            );
          if (['body', 'documentElement'].includes(name)) {
            context.references.set(property.value.name, name);
          }
        }
      }
      if (analyzeExpression(declaration.init, context)) {
        return true;
      }
      continue;
    }
    if (declaration.id.type !== 'Identifier') {
      continue;
    }
    if (
      ['ArrowFunctionExpression', 'FunctionExpression'].includes(
        declaration.init.type
      )
    ) {
      context.functions.set(declaration.id.name, declaration.init);
      continue;
    }
    if (
      declaration.init.type === 'Identifier' &&
      context.functions.has(declaration.init.name)
    ) {
      context.functions.set(
        declaration.id.name,
        context.functions.get(declaration.init.name)
      );
    }
    if (analyzeExpression(declaration.init, context)) {
      return true;
    }
    const stringValue = staticString(declaration.init, context.strings);
    const reference = referenceKind(declaration.init, context);
    if (stringValue !== null) {
      context.strings.set(declaration.id.name, stringValue);
    }
    if (reference !== null) {
      context.references.set(declaration.id.name, reference);
    }
    if (denialValue(declaration.init, context)) {
      context.denialReferences.add(declaration.id.name);
    }
    if (safeDomContentValue(declaration.init, context)) {
      context.safeDomContentReferences.add(declaration.id.name);
    }
  }
  return false;
}

function analyzeStatement(statement, context) {
  if (!statement) {
    return false;
  }
  if (statement.type === 'FunctionDeclaration') {
    if (statement.id?.name) {
      context.functions.set(statement.id.name, statement);
    }
    return false;
  }
  if (statement.type === 'VariableDeclaration') {
    return analyzeVariableDeclaration(statement, context);
  }
  if (statement.type === 'ExpressionStatement') {
    return analyzeExpression(statement.expression, context);
  }
  if (statement.type === 'BlockStatement') {
    return analyzeStatements(statement.body, context);
  }
  if (statement.type === 'IfStatement') {
    return (
      analyzeExpression(statement.test, context) ||
      analyzeStatement(statement.consequent, forkContext(context)) ||
      analyzeStatement(statement.alternate, forkContext(context))
    );
  }
  if (statement.type === 'TryStatement') {
    return (
      analyzeStatement(statement.block, forkContext(context)) ||
      analyzeStatement(statement.handler?.body, forkContext(context)) ||
      analyzeStatement(statement.finalizer, forkContext(context))
    );
  }
  if (
    [
      'DoWhileStatement',
      'ForInStatement',
      'ForOfStatement',
      'ForStatement',
      'LabeledStatement',
      'WhileStatement',
      'WithStatement'
    ].includes(statement.type)
  ) {
    return (
      analyzeExpression(statement.test, context) ||
      analyzeExpression(statement.init, context) ||
      analyzeExpression(statement.update, context) ||
      analyzeExpression(statement.left, context) ||
      analyzeExpression(statement.right, context) ||
      analyzeStatement(statement.body, forkContext(context))
    );
  }
  if (statement.type === 'SwitchStatement') {
    return (
      analyzeExpression(statement.discriminant, context) ||
      statement.cases.some((switchCase) =>
        analyzeStatements(
        switchCase.consequent,
        forkContext(context)
      )
      )
    );
  }
  if (
    ['ReturnStatement', 'ThrowStatement'].includes(statement.type)
  ) {
    return analyzeExpression(statement.argument, context);
  }
  if (
    ['ExportDefaultDeclaration', 'ExportNamedDeclaration'].includes(
      statement.type
    )
  ) {
    if (statement.declaration?.type === 'VariableDeclaration') {
      return analyzeVariableDeclaration(
        statement.declaration,
        context
      );
    }
    if (statement.declaration?.type === 'FunctionDeclaration') {
      return analyzeStatement(statement.declaration, context);
    }
    return analyzeExpression(statement.declaration, context);
  }
  return false;
}

function analyzeStatements(statements, context) {
  for (const statement of statements) {
    if (
      statement.type === 'FunctionDeclaration' &&
      statement.id?.name
    ) {
      context.functions.set(statement.id.name, statement);
    }
  }
  for (const statement of statements) {
    if (analyzeStatement(statement, context)) {
      return true;
    }
  }
  return false;
}

function walkSyntax(root, visitor) {
  const stack = [root];
  const reviewed = new Set();
  while (stack.length > 0) {
    const node = stack.pop();
    if (
      node === null ||
      typeof node !== 'object' ||
      reviewed.has(node)
    ) {
      continue;
    }
    reviewed.add(node);
    if (typeof node.type === 'string') {
      visitor(node);
    }
    for (const value of Object.values(node)) {
      if (Array.isArray(value)) {
        stack.push(...value);
      } else if (value !== null && typeof value === 'object') {
        stack.push(value);
      }
    }
  }
}

function directString(node) {
  if (node?.type === 'Literal' && typeof node.value === 'string') {
    return node.value;
  }
  if (
    node?.type === 'TemplateLiteral' &&
    node.expressions.length === 0 &&
    node.quasis.length === 1
  ) {
    return node.quasis[0].value.cooked ?? '';
  }
  return null;
}

function directMemberName(node) {
  if (node?.type !== 'MemberExpression') {
    return null;
  }
  if (!node.computed && node.property.type === 'Identifier') {
    return node.property.name;
  }
  return directString(node.property);
}

function directSelector(node, aliases) {
  if (node?.type === 'Identifier') {
    return aliases.get(node.name) ?? null;
  }
  if (node?.type === 'MemberExpression') {
    const property = directMemberName(node);
    if (['classList', 'style'].includes(property)) {
      return directSelector(node.object, aliases);
    }
  }
  if (
    node?.type === 'CallExpression' &&
    node.callee.type === 'MemberExpression' &&
    node.callee.object.type === 'Identifier' &&
    node.callee.object.name === 'document'
  ) {
    const method = directMemberName(node.callee);
    const value = directString(node.arguments[0]);
    if (method === 'querySelector' && value !== null) {
      return value;
    }
    if (method === 'getElementById' && value !== null) {
      return `#${value}`;
    }
  }
  return null;
}

function criticalCommerceSelector(value) {
  return (
    typeof value === 'string' &&
    /(?:\bform(?:\.|#|\[|\s)*(?:cart|checkout)\b|woocommerce-(?:cart-form|form-login)|add-to-cart|place_order|woocommerce_checkout_place_order|billing_|shipping_|cart\[|product_title|\.stock\b|\.products\b|woocommerce-info)/iu
      .test(value)
  );
}

function callbackCancelsAction(callback) {
  let cancels = false;
  walkSyntax(callback, (node) => {
    if (
      node.type === 'CallExpression' &&
      node.callee.type === 'MemberExpression' &&
      directMemberName(node.callee) === 'preventDefault'
    ) {
      cancels = true;
    }
    if (
      node.type === 'ReturnStatement' &&
      node.argument?.type === 'Literal' &&
      node.argument.value === false
    ) {
      cancels = true;
    }
  });
  return cancels;
}

function hasCriticalCommerceMutation(root) {
  const aliases = new Map();
  walkSyntax(root, (node) => {
    if (
      node.type === 'VariableDeclarator' &&
      node.id.type === 'Identifier'
    ) {
      const selector = directSelector(node.init, aliases);
      if (selector !== null) {
        aliases.set(node.id.name, selector);
      }
    }
    if (
      node.type === 'AssignmentExpression' &&
      node.left.type === 'Identifier'
    ) {
      const selector = directSelector(node.right, aliases);
      if (selector !== null) {
        aliases.set(node.left.name, selector);
      }
    }
  });

  let invalid = false;
  walkSyntax(root, (node) => {
    if (invalid) {
      return;
    }
    if (
      node.type === 'AssignmentExpression' &&
      node.left.type === 'MemberExpression'
    ) {
      const selector = directSelector(node.left.object, aliases);
      const property = directMemberName(node.left);
      const value = node.right.type === 'Literal'
        ? node.right.value
        : directString(node.right);
      const targetIsStyle = (
        node.left.object.type === 'MemberExpression' &&
        directMemberName(node.left.object) === 'style'
      );
      if (
        criticalCommerceSelector(selector) &&
        (
          (
            ['disabled', 'hidden', 'inert'].includes(property) &&
            value === true
          ) ||
          (
            ['innerHTML', 'outerHTML', 'textContent'].includes(property) &&
            value === ''
          ) ||
          (
            targetIsStyle &&
            (
              (property === 'display' && value === 'none') ||
              (
                property === 'visibility' &&
                ['collapse', 'hidden'].includes(value)
              ) ||
              (property === 'contentVisibility' && value === 'hidden') ||
              (
                ['height', 'opacity', 'width'].includes(property) &&
                ['0', '0%', '0px', 0].includes(value)
              ) ||
              (property === 'pointerEvents' && value === 'none')
            )
          )
        )
      ) {
        invalid = true;
      }
    }
    if (
      node.type !== 'CallExpression' ||
      node.callee.type !== 'MemberExpression'
    ) {
      return;
    }
    const selector = directSelector(node.callee.object, aliases);
    if (!criticalCommerceSelector(selector)) {
      return;
    }
    const method = directMemberName(node.callee);
    if (['remove', 'replaceChildren', 'replaceWith'].includes(method)) {
      invalid = true;
      return;
    }
    if (method === 'removeAttribute') {
      const attribute = directString(node.arguments[0]);
      if (
        [
          'action',
          'class',
          'method',
          'name',
          'type',
          'value'
        ].includes(attribute)
      ) {
        invalid = true;
        return;
      }
    }
    if (method === 'setAttribute') {
      const attribute = directString(node.arguments[0]);
      const value = directString(node.arguments[1]);
      if (
        ['aria-hidden', 'disabled', 'hidden', 'inert'].includes(attribute) ||
        (
          attribute === 'style' &&
          /(?:display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0(?:\D|$))/iu
            .test(value ?? '')
        )
      ) {
        invalid = true;
        return;
      }
    }
    if (
      method === 'add' &&
      node.callee.object.type === 'MemberExpression' &&
      directMemberName(node.callee.object) === 'classList' &&
      node.arguments.some((argument) => (
        /^(?:hidden|is-hidden|out-of-stock|unavailable)$/iu
          .test(directString(argument) ?? '')
      ))
    ) {
      invalid = true;
      return;
    }
    if (
      method === 'addEventListener' &&
      ['click', 'submit'].includes(directString(node.arguments[0])) &&
      callbackCancelsAction(node.arguments[1])
    ) {
      invalid = true;
    }
  });
  return invalid;
}

if (hasCriticalCommerceMutation(program)) {
  process.exit(1);
}

if (
  Buffer.byteLength(source, 'utf8') <= 16 * 1024 &&
  analyzeStatements(program.body, {
    activeFunctions: new Set(),
    denialReferences: new Set(),
    functions: new Map(),
    references: new Map(),
    safeDomContentReferences: new Set(),
    strings: new Map(),
  })
) {
  process.exit(1);
}
